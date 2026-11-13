import { useCallback, useEffect, useState } from 'react'
import * as api from '../../services/api'
import { useI18n } from '../../i18n/useI18n'
import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'
import type { BookStructure, TocItem } from '../../types'

interface Props {
  bookId: string
  open: boolean
  pageNo: number
  onClose: () => void
  onJump: (pdfPage: number) => void
  onOpenStructure: () => void
}

/** Resolvable PDF page of a TOC entry: explicit pdf_page wins, otherwise
 *  book_page + the structure offset. Null when nothing is computable. */
function pdfPageOf(it: TocItem, offset: number | null): number | null {
  if (it.pdf_page != null && it.pdf_page > 0) return it.pdf_page
  if (it.book_page != null && it.book_page > 0) return it.book_page + (offset ?? 0)
  return null
}

/** Sliding TOC sidebar: the saved book structure as a clickable outline.
 *  Click an entry to jump to its page; the current page is highlighted. */
export default function TocPanel({ bookId, open, pageNo, onClose, onJump, onOpenStructure }: Props) {
  const { t } = useI18n()
  const [st, setSt] = useState<BookStructure | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !bookId) return
    let cancelled = false
    setLoading(true)
    api.getStructure(bookId)
      .then((s) => { if (!cancelled) setSt(s) })
      .catch(() => { if (!cancelled) setSt(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [open, bookId])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const target = e.target as HTMLElement | null
      if (!target?.closest('input, textarea, select, [contenteditable="true"]')) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const jumpWith = useCallback((it: TocItem) => {
    const p = pdfPageOf(it, st?.offset ?? null)
    if (p != null && p >= 1) onJump(p)
  }, [st?.offset, onJump])

  if (!open) return null

  const toc = st?.toc || []

  return (
    <div
      className="absolute left-0 top-0 bottom-0 z-40 flex flex-col w-[min(340px,86vw)] border-r border-ag-line2 bg-ag-bg3"
      role="dialog"
      aria-label={t('workbench.tocTitle')}
    >
      <div className="shrink-0 flex items-center gap-2 px-3 py-2.5 border-b border-ag-line1">
        <h2 className="text-h2 font-medium text-ag-ink1 flex-1">{t('workbench.tocTitle')}</h2>
        {st?.offset != null && (
          <span className="ag-mono text-micro text-ag-ink3" title={t('workbench.structOffset')}>
            {t('workbench.tocOffset')}{st.offset}
          </span>
        )}
        <Button size="sm" variant="ghost" onClick={onClose} aria-label={t('workbench.structClose')}>✕</Button>
      </div>

      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="p-4 text-caption text-ag-ink3">{t('workbench.tocLoading')}</div>
        ) : toc.length === 0 ? (
          <div className="p-4 flex flex-col gap-3">
            <EmptyState>{t('workbench.tocEmpty')}</EmptyState>
            <Button size="sm" variant="primary" onClick={onOpenStructure}>
              {t('workbench.tocGoStructure')}
            </Button>
          </div>
        ) : (
          <ul className="py-1.5" aria-label={t('workbench.tocTitle')}>
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
                    className={`ag-focus-ring w-full text-left flex items-baseline gap-2 px-3 py-1 text-caption transition-colors ${
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
        )}
      </div>
    </div>
  )
}
