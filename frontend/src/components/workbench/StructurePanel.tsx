import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
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

type EditTarget =
  | { kind: 'title' | 'author' | 'offset' }
  | { kind: 'toc'; idx: number }
  | null

/** The structure editor deliberately shows top-level entries only; the full
 *  multi-level outline belongs to the separate TOC navigation tab. */
function topLevel(items: TocItem[]): TocItem[] {
  return items.filter((it) => (it.level ?? 1) <= 1)
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

/** Flat entry list for the LEFT function column. Book title, author and every
 *  TOC entry are peers in one list — no table grid. A row turns into inputs
 *  only while that single row is being edited. */
export default function StructurePanel({ bookId, refreshKey = 0, onJump, onConfirmed }: Props) {
  const { t } = useI18n()
  const [st, setSt] = useState<BookStructure | null>(null)
  const [toc, setToc] = useState<TocItem[]>([])
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [offset, setOffset] = useState('')
  const [editing, setEditing] = useState<EditTarget>(null)
  const [detecting, setDetecting] = useState(false)
  const [busy, setBusy] = useState<'' | 'parse' | 'save' | 'confirm'>('')
  const [msg, setMsg] = useState('')
  const [tocPageInput, setTocPageInput] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  const applyStructure = useCallback((s: BookStructure) => {
    // Old saved structures kept every level in `toc` and had no `toc_full`.
    // Normalize on read: editor gets level-1 only, navigation keeps the full
    // outline (so saving afterwards cannot flatten the TOC tab).
    const full = s.toc_full?.length ? s.toc_full : (s.toc || [])
    const normalized: BookStructure = { ...s, toc: topLevel(s.toc || []), toc_full: full }
    setSt(normalized)
    setToc(normalized.toc)
    setTitle(s.title || '')
    setAuthor(s.author || '')
    setOffset(s.offset != null ? String(s.offset) : '')
    setEditing(null)
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
      const items = topLevel((r.items || []) as TocItem[])
      if (items.length === 0) {
        setMsg('该页未解析出目录条目')
      } else {
        setToc((prev) => mergeToc(prev, items))
        setSt((prev) => prev
          ? { ...prev, toc_full: mergeToc(prev.toc_full || [], items) }
          : prev)
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
    toc_full: st?.toc_full ?? [],
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

  const inputCls = 'ag-focus-ring bg-ag-bg2 border border-ag-line2 rounded-btn px-1.5 py-0.5 text-caption text-ag-ink1 min-w-0'
  const rowCls = 'group flex items-baseline gap-1.5 px-2 py-1 text-caption text-ag-ink2 hover:bg-ag-bg2 rounded-btn'
  const labelCls = 'ag-mono text-micro text-ag-ink3 shrink-0'

  const onEditKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === 'Escape') setEditing(null)
  }
  const editButton = (target: NonNullable<EditTarget>) => (
    <button
      onClick={() => setEditing(target)}
      aria-label={t('workbench.structEdit')}
      className="ag-focus-ring opacity-0 group-hover:opacity-100 focus:opacity-100 text-micro text-ag-ink3 hover:text-ag-cinnabar shrink-0"
    >
      {t('workbench.structEdit')}
    </button>
  )
  const doneButton = (
    <button onClick={() => setEditing(null)} className="ag-focus-ring text-micro text-ag-cinnabar hover:underline shrink-0">
      {t('workbench.structEditDone')}
    </button>
  )

  const renderMetaRow = (kind: 'title' | 'author', label: string,
                         value: string, onChange: (v: string) => void) => {
    const active = editing?.kind === kind
    return (
      <li key={kind} className={rowCls}>
        <span className={`${labelCls} w-9`}>{label}</span>
        {active ? (
          <input
            autoFocus
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onBlur={() => setEditing(null)}
            onKeyDown={onEditKey}
            aria-label={label}
            className={`${inputCls} flex-1`}
          />
        ) : (
          <span className="flex-1 min-w-0 truncate text-ag-ink1" title={value}>{value || '—'}</span>
        )}
        {active ? doneButton : editButton({ kind })}
      </li>
    )
  }

  const renderTocRow = (it: TocItem, idx: number) => {
    const active = editing?.kind === 'toc' && editing.idx === idx
    const pdf = it.pdf_page != null && it.pdf_page > 0 ? it.pdf_page : null
    return (
      <li key={idx} className={rowCls}>
        <span className={`${labelCls} w-9 truncate`} title={it.no ?? ''}>{it.no || '·'}</span>
        {active ? (
          <>
            <input
              autoFocus
              value={it.title}
              onChange={(e) => updateItem(idx, { title: e.target.value })}
              onKeyDown={onEditKey}
              aria-label={t('workbench.structTitle')}
              className={`${inputCls} flex-1`}
            />
            <input
              type="number" value={it.book_page ?? ''}
              onChange={(e) => updateItem(idx, { book_page: e.target.value === '' ? null : Number(e.target.value) })}
              onKeyDown={onEditKey}
              aria-label={t('workbench.structBookPage')}
              className={`${inputCls} w-11 text-micro`}
            />
            <input
              type="number" value={it.pdf_page ?? ''}
              onChange={(e) => updateItem(idx, { pdf_page: e.target.value === '' ? null : Number(e.target.value) })}
              onKeyDown={onEditKey}
              aria-label={t('workbench.structPdfPage')}
              className={`${inputCls} w-11 text-micro`}
            />
          </>
        ) : (
          <button
            onClick={() => pdf && onJump(pdf)}
            disabled={!pdf}
            title={it.title}
            className="ag-focus-ring flex-1 min-w-0 flex items-baseline gap-1.5 text-left"
          >
            <span className="flex-1 min-w-0 truncate">{it.title || '—'}</span>
            {pdf && <span className="ag-mono text-micro text-ag-ink3 shrink-0">p{pdf}</span>}
          </button>
        )}
        {active ? doneButton : editButton({ kind: 'toc', idx })}
      </li>
    )
  }

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
          className={`${inputCls} w-14 text-micro`}
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

      {/* one flat list: title / author / front matter / chapters are all peers */}
      <div className="flex-1 min-h-0 overflow-auto py-1">
        {toc.length > 0 && (
          <div className="px-2 pb-1 text-micro text-ag-ink3">
            {t('workbench.structTopOnly').replace('{n}', String(toc.length))}
          </div>
        )}
        <ul aria-label={t('workbench.structureTitle')}>
          {renderMetaRow('title', t('workbench.structTitle'), title, setTitle)}
          {renderMetaRow('author', t('workbench.structAuthor'), author, setAuthor)}
          {toc.length === 0
            ? <li className="px-2 py-3 text-micro text-ag-ink3">{t('workbench.structEmpty')}</li>
            : toc.map(renderTocRow)}
        </ul>
      </div>

      {/* offset + commit footer */}
      <div className="shrink-0 border-t border-ag-line1 px-2 py-1.5 flex flex-col gap-1">
        <div className="flex items-center gap-1.5 text-micro text-ag-ink3 min-w-0">
          <span className="shrink-0">{t('workbench.structOffset')}</span>
          {editing?.kind === 'offset' ? (
            <input
              autoFocus value={offset}
              onChange={(e) => setOffset(e.target.value)}
              onBlur={() => setEditing(null)}
              onKeyDown={onEditKey}
              placeholder={t('workbench.structOffsetNone')}
              className={`${inputCls} w-16 text-micro`}
            />
          ) : (
            <button
              onClick={() => setEditing({ kind: 'offset' })}
              className="ag-focus-ring flex-1 min-w-0 truncate text-left hover:text-ag-ink1"
            >
              {offset.trim() === '' ? t('workbench.structOffsetNone') : offset}
            </button>
          )}
          <Button size="sm" variant="ghost" onClick={applyOffset}>{t('workbench.structApplyOffset')}</Button>
          {st?.offset_confidence != null && st.offset_confidence > 0 && (
            <span className="ag-mono text-micro">×{st.offset_confidence}</span>
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
