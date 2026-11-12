import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../../services/api'
import { useI18n } from '../../i18n/useI18n'
import Button from '../ui/Button'
import type { BookStructure, TocItem } from '../../types'

interface Props {
  bookId: string
  open: boolean
  onClose: () => void
  onJump: (pdfPage: number) => void
}

/** Escape closes while focus is outside inputs (matches app-wide shortcut). */
function useEscape(onClose: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const target = e.target as HTMLElement | null
      const editable = target?.closest('input, textarea, select, [contenteditable="true"]')
      if (!editable) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, active])
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

export default function BookStructurePanel({ bookId, open, onClose, onJump }: Props) {
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

  useEscape(onClose, open)

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
    if (open && bookId) void load()
  }, [open, bookId, load])

  useEffect(() => () => abortRef.current?.abort(), [])

  if (!open) return null

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

  const sourceLabel = st?.source === 'bookmark'
    ? t('workbench.structSourceBookmark')
    : st?.source === 'vision'
      ? t('workbench.structSourceVision')
      : t('workbench.structSourceManual')

  const inputCls = 'ag-focus-ring bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1 text-caption text-ag-ink1'

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('workbench.structureTitle')}
        className="flex flex-col w-[min(780px,94vw)] max-h-[90vh] rounded-overlay border border-ag-line2 bg-ag-bg3"
      >
        <div className="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-ag-line1">
          <h2 className="text-h2 font-medium text-ag-ink1 flex-1">
            {t('workbench.structureTitle')}
            {st?.confirmed && <span className="ml-2 text-caption text-ag-statusConfirmed">✓✓ {t('workbench.structConfirmed')}</span>}
          </h2>
          {st?.source && (
            <span className="text-caption text-ag-ink3 ag-mono">{t('workbench.structSource')}: {sourceLabel}</span>
          )}
          <Button size="sm" variant="ghost" onClick={onClose}>{t('workbench.structClose')}</Button>
        </div>

        <div className="flex-1 overflow-auto px-4 py-3">
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <Button size="sm" variant="primary" loading={detecting} disabled={detecting} onClick={() => void detect()}>
              {detecting ? t('workbench.structDetecting') : t('workbench.structDetect')}
            </Button>
            <span className="text-caption text-ag-ink3">{t('workbench.structTocPage')}</span>
            <input
              type="number" min={1} value={tocPageInput}
              onChange={(e) => setTocPageInput(e.target.value)}
              className={`${inputCls} w-20`}
              aria-label={t('workbench.structTocPage')}
            />
            <Button size="sm" loading={busy === 'parse'} disabled={busy !== '' || !tocPageInput} onClick={() => void parsePage()}>
              {t('workbench.structParse')}
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-2 mb-3">
            <label className="flex items-center gap-2 text-caption text-ag-ink3">
              <span className="shrink-0">{t('workbench.structTitle')}</span>
              <input value={title} onChange={(e) => setTitle(e.target.value)} className={`${inputCls} flex-1 min-w-0`} />
            </label>
            <label className="flex items-center gap-2 text-caption text-ag-ink3">
              <span className="shrink-0">{t('workbench.structAuthor')}</span>
              <input value={author} onChange={(e) => setAuthor(e.target.value)} className={`${inputCls} flex-1 min-w-0`} />
            </label>
          </div>

          <div className="flex items-center gap-2 mb-3 flex-wrap text-caption text-ag-ink3">
            <span>{t('workbench.structOffset')}</span>
            <input
              value={offset}
              onChange={(e) => setOffset(e.target.value)}
              placeholder={t('workbench.structOffsetNone')}
              className={`${inputCls} w-24`}
            />
            <Button size="sm" variant="ghost" onClick={applyOffset}>按偏移补齐 PDF 页</Button>
            {st?.offset_confidence != null && st.offset_confidence > 0 && (
              <span className="ag-mono">锚点 ×{st.offset_confidence}</span>
            )}
          </div>

          <div className="flex items-center justify-between mb-1.5">
            <span className="text-caption font-medium text-ag-ink3 tracking-wider">{t('workbench.structToc')}</span>
            <Button size="sm" variant="ghost" onClick={() => setToc((prev) => [...prev, { level: 1, title: '', book_page: null, pdf_page: null }])}>
              + {t('workbench.structAddRow')}
            </Button>
          </div>

          {toc.length === 0 ? (
            <div className="mb-3"><EmptyHint /></div>
          ) : (
            <div className="rounded-card border border-ag-line1 overflow-hidden mb-3">
              <div className="flex items-center gap-2 px-2 py-1.5 bg-ag-bg2 text-micro text-ag-ink3 ag-mono border-b border-ag-line1">
                <span className="w-10 shrink-0">{t('workbench.structLevel')}</span>
                <span className="flex-1">{t('workbench.structTitle')}</span>
                <span className="w-16 shrink-0 text-right">{t('workbench.structBookPage')}</span>
                <span className="w-16 shrink-0 text-right">{t('workbench.structPdfPage')}</span>
                <span className="w-12 shrink-0" />
              </div>
              <div className="max-h-[34vh] overflow-auto">
                {toc.map((it, idx) => (
                  <div key={idx} className="flex items-center gap-2 px-2 py-1 border-b border-ag-line1 last:border-b-0">
                    <select
                      value={it.level}
                      onChange={(e) => updateItem(idx, { level: Number(e.target.value) })}
                      className={`${inputCls} w-10 shrink-0 px-1`}
                      aria-label={t('workbench.structLevel')}
                    >
                      {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                    <input
                      value={it.title}
                      onChange={(e) => updateItem(idx, { title: e.target.value })}
                      className={`${inputCls} flex-1 min-w-0`}
                      style={{ marginLeft: (it.level - 1) * 12 }}
                    />
                    <input
                      type="number"
                      value={it.book_page ?? ''}
                      onChange={(e) => updateItem(idx, { book_page: e.target.value === '' ? null : Number(e.target.value) })}
                      className={`${inputCls} w-16 shrink-0 text-right`}
                    />
                    <input
                      type="number"
                      value={it.pdf_page ?? ''}
                      onChange={(e) => updateItem(idx, { pdf_page: e.target.value === '' ? null : Number(e.target.value) })}
                      className={`${inputCls} w-16 shrink-0 text-right`}
                    />
                    {it.pdf_page != null && it.pdf_page > 0 ? (
                      <button
                        onClick={() => onJump(it.pdf_page!)}
                        className="ag-focus-ring w-12 shrink-0 text-caption text-ag-cinnabar hover:underline"
                      >
                        {t('workbench.structJump')}
                      </button>
                    ) : (
                      <span className="w-12 shrink-0" />
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="shrink-0 flex items-center gap-2 px-4 py-3 border-t border-ag-line1 bg-ag-bg2">
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

function EmptyHint() {
  const { t } = useI18n()
  return (
    <div className="ag-empty text-caption text-ag-ink3">
      {t('workbench.structEmpty')}
    </div>
  )
}
