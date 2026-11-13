import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../../services/api'
import { useI18n } from '../../i18n/useI18n'
import Button from '../ui/Button'
import type { BookStructure, TocItem } from '../../types'

interface Props {
  bookId: string
  /** Changing this key makes the panel reload its saved structure. */
  refreshKey?: number
  onJump: (pdfPage: number) => void
  /** Fired after 确认入图, so callers can refresh chapter-dependent data. */
  onConfirmed?: () => void
}

function mergeToc(existing: TocItem[], incoming: TocItem[]): TocItem[] {
  const seen = new Set(existing.map((it) => `${it.title}::${it.book_page}`))
  const merged = [...existing]
  for (const it of incoming) {
    const key = `${it.title}::${it.book_page}`
    if (it.title && !seen.has(key)) {
      merged.push(it)
      seen.add(key)
    }
  }
  return merged
}

/** Compact, single-screen book-structure editor for the LEFT function column.
 *  The TOC table is the hero (fills the panel); metadata lives in one tight
 *  row at the bottom. No page scrolling — the table scrolls internally. */
export default function StructurePanel({ bookId, refreshKey = 0, onJump, onConfirmed }: Props) {
  const { t } = useI18n()
  const [st, setSt] = useState<BookStructure | null>(null)
  const [toc, setToc] = useState<TocItem[]>([])
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [offset, setOffset] = useState('')
  const [detecting, setDetecting] = useState(false)
  const [busy, setBusy] = useState<'' | 'parse' | 'save' | 'confirm'>('')
  const [msg, setMsg] = useState('')
  const [tocPageInput, setTocPageInput] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  const applyStructure = useCallback((s: BookStructure) => {
    setSt(s)
    setToc(s.toc || [])
    setTitle(s.title || '')
    setAuthor(s.author || '')
    setOffset(s.offset != null ? String(s.offset) : '')
  }, [])

  const load = useCallback(async () => {
    if (!bookId) return
    applyStructure(await api.getStructure(bookId))
    setMsg('')
  }, [bookId, applyStructure])

  useEffect(() => {
    if (bookId) void load()
  }, [bookId, refreshKey, load])

  useEffect(() => () => abortRef.current?.abort(), [])

  const detect = async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setDetecting(true)
    setMsg('')
    try {
      const r = await api.detectStructure(bookId, controller.signal, crypto.randomUUID())
      if (r.cancelled) {
        setMsg('识别已取消')
        void load()
      } else {
        applyStructure(r)
        setMsg(t('workbench.structDetectDone').replace('{n}', String((r.toc || []).length)))
      }
    } catch (e) {
      const err = e as Error
      if (err.name === 'AbortError') setMsg('识别已取消')
      else setMsg(`识别失败: ${err.message.slice(0, 140)}`)
    } finally {
      setDetecting(false)
      abortRef.current = null
    }
  }

  const parsePage = async () => {
    const n = Number(tocPageInput)
    if (!n || n < 1) return
    setBusy('parse')
    setMsg('')
    try {
      const r = await api.parseTocPage(bookId, n)
      const items: TocItem[] = r.items || []
      if (items.length === 0) {
        setMsg('该页未解析出目录条目')
      } else {
        setToc((prev) => mergeToc(prev, items))
        setMsg(t('workbench.structParseDone').replace('{n}', String(items.length)))
      }
    } catch (e) {
      setMsg(`解析失败: ${(e as Error).message.slice(0, 140)}`)
    } finally {
      setBusy('')
    }
  }

  const buildPayload = () => ({
    title: title.trim() || null,
    author: author.trim() || null,
    publisher: st?.publisher ?? null,
    offset: offset.trim() === '' ? null : Number(offset),
    source: st?.source ?? 'manual',
    toc,
  })

  const save = async (): Promise<boolean> => {
    try {
      applyStructure(await api.saveStructure(bookId, buildPayload()))
      return true
    } catch (e) {
      setMsg(`保存失败: ${(e as Error).message.slice(0, 140)}`)
      return false
    }
  }

  const saveAndReport = async () => {
    setBusy('save')
    setMsg('')
    if (await save()) setMsg(t('workbench.structSaved'))
    setBusy('')
  }

  const confirm = async () => {
    setBusy('confirm')
    setMsg('')
    if (!(await save())) {
      setBusy('')
      return
    }
    try {
      const r = await api.confirmStructure(bookId)
      setMsg(t('workbench.structChapterNodes').replace('{n}', String(r.chapters_created)))
      setSt((prev) => (prev ? { ...prev, confirmed: true } : prev))
      onConfirmed?.()
    } catch (e) {
      setMsg(`${t('workbench.structConfirmNoToc')} — ${(e as Error).message.slice(0, 100)}`)
    } finally {
      setBusy('')
    }
  }

  const applyOffset = () => {
    const off = Number(offset)
    if (offset.trim() === '' || Number.isNaN(off)) return
    setToc((prev) => prev.map((it) =>
      it.book_page != null && it.pdf_page == null
        ? { ...it, pdf_page: it.book_page + off }
        : it,
    ))
  }

  const updateItem = (idx: number, patch: Partial<TocItem>) =>
    setToc((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)))

  const inputCls = 'ag-focus-ring bg-ag-bg2 border border-ag-line2 rounded-btn px-1.5 py-1 text-caption text-ag-ink1 min-w-0'

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* actions row — always visible, no scrolling to reach anything */}
      <div className="shrink-0 flex items-center gap-1.5 px-2 py-1.5 border-b border-ag-line1 flex-wrap">
        <Button size="sm" variant="primary" loading={detecting} disabled={detecting} onClick={() => void detect()}>
          {detecting ? t('workbench.structDetecting') : t('workbench.structDetect')}
        </Button>
        <input
          type="number" min={1} value={tocPageInput}
          onChange={(e) => setTocPageInput(e.target.value)}
          className={`${inputCls} w-14`}
          aria-label={t('workbench.structTocPage')}
          placeholder={t('workbench.structTocPage')}
        />
        <Button size="sm" loading={busy === 'parse'} disabled={busy !== '' || !tocPageInput} onClick={() => void parsePage()}>
          {t('workbench.structParse')}
        </Button>
        <span className="ml-auto text-micro ag-mono text-ag-ink3">
          {st?.source ? (st.source === 'bookmark'
            ? t('workbench.structSourceBookmark')
            : st.source === 'text'
              ? t('workbench.structSourceText')
              : st.source === 'vision'
                ? t('workbench.structSourceVision')
                : t('workbench.structSourceManual')) : ''}
        </span>
      </div>

      {/* hero: the TOC table fills all remaining height */}
      <div className="flex-1 min-h-0 flex flex-col px-2 pt-1.5">
        {toc.length === 0 ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="ag-empty text-caption text-ag-ink3 text-center px-3">
              {t('workbench.structEmpty')}
            </div>
          </div>
        ) : (
          <>
            <div className="shrink-0 flex items-center gap-1 px-1 py-1 text-micro text-ag-ink3 ag-mono border-b border-ag-line1">
              <span className="w-9 shrink-0">{t('workbench.structLevel')}</span>
              <span className="flex-1">{t('workbench.structTitle')}</span>
              <span className="w-12 shrink-0 text-right">{t('workbench.structBookPage')}</span>
              <span className="w-12 shrink-0 text-right">{t('workbench.structPdfPage')}</span>
              <span className="w-10 shrink-0" />
            </div>
            <div className="flex-1 min-h-0 overflow-auto">
              {toc.map((it, idx) => (
                <div key={idx} className="flex items-center gap-1 px-1 py-0.5 border-b border-ag-line1 last:border-b-0">
                  <select
                    value={it.level}
                    onChange={(e) => updateItem(idx, { level: Number(e.target.value) })}
                    className={`${inputCls} w-9 shrink-0 px-0.5`}
                    aria-label={t('workbench.structLevel')}
                  >
                    {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                  <input
                    value={it.title}
                    onChange={(e) => updateItem(idx, { title: e.target.value })}
                    className={`${inputCls} flex-1`}
                    style={{ marginLeft: (it.level - 1) * 10 }}
                  />
                  <input
                    type="number"
                    value={it.book_page ?? ''}
                    onChange={(e) => updateItem(idx, { book_page: e.target.value === '' ? null : Number(e.target.value) })}
                    className={`${inputCls} w-12 shrink-0 text-right`}
                  />
                  <input
                    type="number"
                    value={it.pdf_page ?? ''}
                    onChange={(e) => updateItem(idx, { pdf_page: e.target.value === '' ? null : Number(e.target.value) })}
                    className={`${inputCls} w-12 shrink-0 text-right`}
                  />
                  {it.pdf_page != null && it.pdf_page > 0 ? (
                    <button
                      onClick={() => onJump(it.pdf_page!)}
                      className="ag-focus-ring w-10 shrink-0 text-micro text-ag-cinnabar hover:underline"
                    >
                      {t('workbench.structJump')}
                    </button>
                  ) : (
                    <span className="w-10 shrink-0" />
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* metadata + commit row — compact, single screen */}
      <div className="shrink-0 border-t border-ag-line1 px-2 py-1.5 flex flex-col gap-1.5">
        <div className="grid grid-cols-[auto_1fr_auto_1fr] items-center gap-x-1.5 gap-y-1 text-caption text-ag-ink3">
          <span className="shrink-0">{t('workbench.structTitle')}</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} />
          <span className="shrink-0">{t('workbench.structAuthor')}</span>
          <input value={author} onChange={(e) => setAuthor(e.target.value)} className={inputCls} />
        </div>
        <div className="flex items-center gap-1.5 text-caption text-ag-ink3">
          <span className="shrink-0">{t('workbench.structOffset')}</span>
          <input
            value={offset}
            onChange={(e) => setOffset(e.target.value)}
            placeholder={t('workbench.structOffsetNone')}
            className={`${inputCls} w-16`}
          />
          <Button size="sm" variant="ghost" onClick={applyOffset}>{t('workbench.structApplyOffset')}</Button>
          {st?.offset_confidence != null && st.offset_confidence > 0 && (
            <span className="ag-mono text-micro">×{st.offset_confidence}</span>
          )}
          {st?.confirmed && (
            <span className="ml-auto text-caption text-ag-statusConfirmed">✓✓ {t('workbench.structConfirmed')}</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-caption text-ag-ink2 flex-1 truncate" aria-live="polite">{msg}</span>
          <Button size="sm" loading={busy === 'save'} disabled={busy !== '' || detecting} onClick={() => void saveAndReport()}>
            {t('workbench.structSave')}
          </Button>
          <Button size="sm" variant="primary" loading={busy === 'confirm'} disabled={busy !== '' || detecting} onClick={() => void confirm()}>
            {t('workbench.structConfirm')}
          </Button>
        </div>
      </div>
    </div>
  )
}
