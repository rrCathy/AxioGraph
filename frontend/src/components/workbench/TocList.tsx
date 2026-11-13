import { useCallback, useEffect, useState } from 'react'
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

/** Resolvable PDF page of a TOC entry: explicit pdf_page wins, otherwise
 *  book_page + the structure offset. Null when nothing is computable. */
function pdfPageOf(it: TocItem, offset: number | null): number | null {
  if (it.pdf_page != null && it.pdf_page > 0) return it.pdf_page
  if (it.book_page != null && it.book_page > 0) return it.book_page + (offset ?? 0)
  return null
}

/** Embedded TOC outline for the LEFT function column: the saved book
 *  structure as a clickable tree; current page highlighted. */
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

  const jumpWith = useCallback((it: TocItem) => {
    const p = pdfPageOf(it, st?.offset ?? null)
    if (p != null && p >= 1) onJump(p)
  }, [st?.offset, onJump])

  const toc = st?.toc || []

  if (loading) {
    return <div className="p-4 text-caption text-ag-ink3">{t('workbench.tocLoading')}</div>
  }
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
      {toc.map((it, i) => {
        const p = pdfPageOf(it, st?.offset ?? null)
        const current = p != null && Math.round(p) === pageNo
        return (
          <li key={i}>
            <button
              onClick={() => jumpWith(it)}
              disabled={p == null}
              title={p != null ? `${t('workbench.structJump')} p${p}` : t('workbench.tocNoPage')}
              aria-current={current ? 'true' : undefined}
              className={`ag-focus-ring w-full text-left flex items-baseline gap-2 pr-3 py-1 text-caption transition-colors ${
                current
                  ? 'bg-ag-quoteBg text-ag-ink1 font-medium'
                  : 'text-ag-ink2 hover:bg-ag-bg2 hover:text-ag-ink1'
              }`}
              style={{ paddingLeft: 12 + (it.level - 1) * 14 }}
            >
              <span className={`flex-1 min-w-0 truncate ${it.level === 1 ? 'font-medium' : ''}`}>
                {it.title || '—'}
              </span>
              {p != null && (
                <span className="ag-mono text-micro text-ag-ink3 shrink-0">p{Math.round(p)}</span>
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
