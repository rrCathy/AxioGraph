import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../../services/api'
import { useI18n } from '../../i18n/useI18n'
import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'
import type { BookStructure, TocItem } from '../../types'

interface Props {
  bookId: string
  pageNo: number
  /** Changing this key makes the list reload its saved structure. */
  refreshKey?: number
  onJump: (pdfPage: number) => void
  /** Shown when no TOC exists yet — usually "open the structure tab". */
  onOpenStructure: () => void
}

interface TocNode {
  item: TocItem
  pdf: number | null
  children: TocNode[]
}

/** Resolvable PDF page of a TOC entry: explicit pdf_page wins, otherwise
 *  book_page + the structure offset. Null when nothing is computable. */
function pdfPageOf(it: TocItem, offset: number | null): number | null {
  if (it.pdf_page != null && it.pdf_page > 0) return it.pdf_page
  if (it.book_page != null && it.book_page > 0) return it.book_page + (offset ?? 0)
  return null
}

function buildTree(toc: TocItem[], offset: number | null): TocNode[] {
  const roots: TocNode[] = []
  const stack: TocNode[] = []
  for (const item of toc) {
    const node: TocNode = { item, pdf: pdfPageOf(item, offset), children: [] }
    while (stack.length && stack[stack.length - 1].item.level >= item.level) stack.pop()
    if (stack.length === 0) roots.push(node)
    else stack[stack.length - 1].children.push(node)
    stack.push(node)
  }
  return roots
}

function subtreeHasPage(node: TocNode, pageNo: number): boolean {
  if (node.pdf != null && Math.round(node.pdf) === pageNo) return true
  return node.children.some((c) => subtreeHasPage(c, pageNo))
}

/** Embedded TOC outline for the LEFT function column: the saved book
 *  structure as a collapsible tree with entry numbers; the current page's
 *  path stays expanded, deeper levels start collapsed. */
export default function TocList({ bookId, pageNo, refreshKey = 0, onJump, onOpenStructure }: Props) {
  const { t } = useI18n()
  const [st, setSt] = useState<BookStructure | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!bookId) return
    let cancelled = false
    setLoading(true)
    api.getStructure(bookId)
      .then((s) => { if (!cancelled) setSt(s) })
      .catch(() => { if (!cancelled) setSt(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [bookId, refreshKey])

  const offset = st?.offset ?? null
  const fullToc = st?.toc_full?.length ? st.toc_full : (st?.toc || [])
  const tree = useMemo(
    () => buildTree(fullToc, offset),
    [fullToc, offset],
  )

  // Collapse rule: levels deeper than the first start collapsed unless the
  // current page lives inside them; a click stores an explicit override.
  const [collapsedMap, setCollapsedMap] = useState<Record<string, boolean>>({})

  const isCollapsed = useCallback((node: TocNode, path: string): boolean => {
    const over = collapsedMap[path]
    if (over !== undefined) return over
    return !subtreeHasPage(node, pageNo) && node.item.level > 1
  }, [collapsedMap, pageNo])

  const toggle = useCallback((path: string, node: TocNode) => {
    setCollapsedMap((prev) => ({ ...prev, [path]: !isCollapsed(node, path) }))
  }, [isCollapsed])

  const jumpWith = useCallback((node: TocNode) => {
    if (node.pdf != null && node.pdf >= 1) onJump(node.pdf)
  }, [onJump])

  const renderNode = (node: TocNode, path: string): JSX.Element => {
    const hasKids = node.children.length > 0
    const collapsed = hasKids && isCollapsed(node, path)
    const current = node.pdf != null && Math.round(node.pdf) === pageNo
    return (
      <li key={path}>
        <div
          className={`flex items-baseline pr-3 text-caption transition-colors ${
            current ? 'bg-ag-quoteBg text-ag-ink1 font-medium' : 'text-ag-ink2 hover:bg-ag-bg2 hover:text-ag-ink1'
          }`}
          style={{ paddingLeft: 8 + (node.item.level - 1) * 14 }}
        >
          {hasKids ? (
            <button
              onClick={() => toggle(path, node)}
              aria-expanded={!collapsed}
              aria-label={collapsed ? t('workbench.tocExpand') : t('workbench.tocCollapse')}
              className="ag-focus-ring w-4 h-4 shrink-0 grid place-items-center text-ag-ink3 hover:text-ag-ink1"
            >
              {collapsed ? '▸' : '▾'}
            </button>
          ) : (
            <span className="w-4 shrink-0" />
          )}
          <button
            onClick={() => jumpWith(node)}
            disabled={node.pdf == null}
            title={node.pdf != null ? `${t('workbench.structJump')} p${node.pdf}` : t('workbench.tocNoPage')}
            aria-current={current ? 'true' : undefined}
            className={`ag-focus-ring flex-1 min-w-0 flex items-baseline gap-1.5 py-1 text-left ${node.pdf == null ? 'cursor-default' : ''}`}
          >
            {node.item.no && (
              <span className="ag-mono text-micro text-ag-ink3 shrink-0">{node.item.no}</span>
            )}
            <span className={`flex-1 min-w-0 truncate ${node.item.level === 1 ? 'font-medium' : ''}`}>
              {node.item.title || '—'}
            </span>
            {node.pdf != null && (
              <span className="ag-mono text-micro text-ag-ink3 shrink-0">p{Math.round(node.pdf)}</span>
            )}
          </button>
        </div>
        {hasKids && !collapsed && (
          <ul>
            {node.children.map((c, i) => renderNode(c, `${path}/${i}`))}
          </ul>
        )}
      </li>
    )
  }

  if (loading) {
    return <div className="p-4 text-caption text-ag-ink3">{t('workbench.tocLoading')}</div>
  }
  const toc = fullToc
  if (toc.length === 0) {
    return (
      <div className="p-4 flex flex-col gap-3">
        <EmptyState>{t('workbench.tocEmpty')}</EmptyState>
        <Button size="sm" variant="primary" onClick={onOpenStructure}>
          {t('workbench.tocGoStructure')}
        </Button>
      </div>
    )
  }

  return (
    <ul className="py-1" aria-label={t('workbench.tocTitle')}>
      {tree.map((n, i) => renderNode(n, `${i}`))}
    </ul>
  )
}
