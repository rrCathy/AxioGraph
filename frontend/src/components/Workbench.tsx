import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAppStore } from '../stores/appStore'
import { useI18n } from '../i18n/useI18n'
import * as api from '../services/api'
import type { Candidate, ConfirmedNode, PageDetail, PageInfo } from '../types'
import PageTextEditor from './PageTextEditor'

type RightTab = 'text' | 'candidates' | 'nodes'

const btn = 'px-2.5 py-1 text-xs rounded-md border border-border-subtle text-text-secondary hover:text-text-primary hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
const primary = 'px-3 py-1 text-xs rounded-md bg-accent-blue text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors'

export default function Workbench() {
  const { books, selectedBookId, selectBook } = useAppStore()
  const { t } = useI18n()
  const bookId = selectedBookId

  const [pages, setPages] = useState<PageInfo[]>([])
  const [page, setPage] = useState<PageDetail | null>(null)
  const [pageNo, setPageNo] = useState(1)
  const [windowSize, setWindowSize] = useState(1)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [nodes, setNodes] = useState<ConfirmedNode[]>([])
  const [tab, setTab] = useState<RightTab>('text')
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState('')
  const [quoteDraft, setQuoteDraft] = useState('')
  const [mergeFor, setMergeFor] = useState<string | null>(null)

  const total = pages.length
  const endPage = Math.min(pageNo + windowSize - 1, total || pageNo)

  const loadPages = useCallback(async () => {
    if (!bookId) { setPages([]); return }
    const r = await api.listPages(bookId)
    setPages(r.pages || [])
  }, [bookId])

  const loadPage = useCallback(async () => {
    if (!bookId) { setPage(null); return }
    try { setPage(await api.getPage(bookId, pageNo)) }
    catch { setPage(null) }
  }, [bookId, pageNo])

  const loadCandidates = useCallback(async () => {
    if (!bookId) { setCandidates([]); return }
    const r = await api.listCandidates(bookId)
    setCandidates(r.candidates || [])
  }, [bookId])

  const loadNodes = useCallback(async () => {
    if (!bookId) { setNodes([]); return }
    const r = await api.listConfirmedNodes(bookId)
    setNodes(r.nodes || [])
  }, [bookId])

  useEffect(() => { setPageNo(1); loadPages() }, [bookId, loadPages])
  useEffect(() => { loadPage() }, [loadPage])
  useEffect(() => { loadCandidates(); loadNodes() }, [bookId, loadCandidates, loadNodes])

  const highlight = useMemo(() => {
    if (!page?.blocks?.length || !quoteDraft || !page.page_width || !page.page_height) return null
    const key = quoteDraft.slice(0, 12)
    return page.blocks.find((b) => b.text.includes(key)) || null
  }, [page, quoteDraft])

  const reimport = async () => {
    if (!bookId) return
    setBusy('import'); setMsg(t('workbench.importing'))
    try {
      const r = await api.importPages(bookId)
      await loadPages()
      setPageNo(1)
      setPage(await api.getPage(bookId, 1))
      setMsg(t('workbench.pagesImported').replace('{n}', String(r.page_count)))
    } catch (e) { setMsg(String(e)) }
    finally { setBusy(null) }
  }

  const analyze = async () => {
    if (!bookId || busy) return
    setBusy('extract'); setMsg(t('workbench.analyzing'))
    try {
      const r = await api.extractWindow(bookId, pageNo, endPage)
      await loadCandidates()
      setTab('candidates')
      setMsg(`${r.candidates?.length ?? 0} / ${r.raw_count ?? 0} candidates (p${pageNo}-p${endPage})`)
    } catch (e) { setMsg(String(e)) }
    finally { setBusy(null) }
  }

  const runOcr = async () => {
    if (!bookId || busy) return
    setBusy('ocr'); setMsg(t('workbench.ocrRunning'))
    try {
      const { createWorker } = await import('tesseract.js')
      const worker = await createWorker('chi_sim+eng')
      const url = `${window.location.origin}${api.pageImageUrl(bookId, pageNo)}`
      const { data } = await worker.recognize(url)
      await worker.terminate()
      const r = await api.submitOcr(bookId, pageNo, data.text || '', data.confidence || 0)
      setMsg(r.needs_manual ? t('workbench.ocrFailed') : t('workbench.ocrDone'))
      await loadPage(); await loadPages()
      setTab('text')
    } catch (e) { setMsg(`OCR: ${String(e).slice(0, 100)}`) }
    finally { setBusy(null) }
  }

  const saveText = async (text: string) => {
    if (!bookId) return
    await api.savePageText(bookId, pageNo, text)
    await loadPage(); await loadPages()
    setMsg(t('workbench.saved'))
  }

  const confirm = async (c: Candidate) => {
    const r = await api.confirmCandidate(c.id, quoteDraft || undefined)
    setQuoteDraft('')
    await loadCandidates(); await loadNodes()
    setMsg(`${r.action || 'confirmed'}${r.edges_added ? ` · ${r.edges_added} edges` : ''}`)
  }

  const reject = async (id: string) => {
    await api.rejectCandidate(id)
    await loadCandidates()
  }

  const merge = async (candidateId: string, nodeId: string) => {
    if (!nodeId) return
    await api.mergeCandidate(candidateId, nodeId)
    setMergeFor(null)
    await loadCandidates(); await loadNodes()
    setMsg('merged')
  }

  const statusLabel = (s: string) => t(`workbench.st.${s}`)

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 flex items-center gap-2.5 px-4 h-12 border-b border-border-subtle bg-surface-raised overflow-x-auto">
        <span className="font-medium text-sm text-text-primary whitespace-nowrap">{t('workbench.title')}</span>
        <select
          value={bookId ?? ''}
          onChange={(e) => selectBook(e.target.value)}
          className="text-xs bg-surface-overlay border border-border-subtle rounded-md px-2 py-1 max-w-[190px] truncate"
        >
          <option value="" disabled>{t('workbench.selectBook')}</option>
          {books.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
        </select>
        <div className="w-px h-5 bg-border-medium shrink-0" />
        <button className={btn} disabled={!total || pageNo <= 1} onClick={() => setPageNo((n) => n - 1)}>‹</button>
        <span className="text-xs tabular-nums whitespace-nowrap">{pageNo} / {total || '–'}</span>
        <button className={btn} disabled={!total || pageNo >= total} onClick={() => setPageNo((n) => n + 1)}>›</button>
        <span className="text-2xs text-text-muted whitespace-nowrap">{t('workbench.window')}</span>
        <select value={windowSize} onChange={(e) => setWindowSize(Number(e.target.value))}
          className="text-xs bg-surface-overlay border border-border-subtle rounded-md px-1.5 py-1">
          {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <span className="text-2xs text-text-dim whitespace-nowrap">p{pageNo}–p{endPage}</span>
        <button className={primary} disabled={!bookId || !total || !!busy} onClick={analyze}>
          {busy === 'extract' ? t('workbench.analyzing') : t('workbench.analyze')}
        </button>
        <button className={btn} disabled={!bookId || !total || !!busy} onClick={runOcr}>
          {busy === 'ocr' ? t('workbench.ocrRunning') : t('workbench.ocr')}
        </button>
        <button className={btn} disabled={!bookId || !!busy} onClick={reimport}>
          {busy === 'import' ? t('workbench.importing') : t('workbench.reimport')}
        </button>
        {msg && <span className="ml-auto text-2xs text-text-muted truncate max-w-[280px]">{msg}</span>}
      </div>

      <div className="flex-1 flex min-h-0">
        <div className="w-1/2 flex flex-col border-r border-border-subtle min-h-0">
          <div className="shrink-0 px-3 py-1.5 text-2xs text-text-muted border-b border-border-subtle flex gap-3">
            <span>{t('workbench.source')} · p{pageNo}</span>
            {page && <span>{t('workbench.quality')}: {page.quality}</span>}
            {page && <span className="px-1.5 rounded bg-surface-overlay">{statusLabel(page.status)}</span>}
            {page?.ocr_confidence != null && <span>OCR {Math.round(page.ocr_confidence)}%</span>}
          </div>
          {page?.status === 'bad_page' && (
            <div className="shrink-0 px-3 py-2 text-2xs bg-amber-50 border-b border-amber-200 text-amber-900">
              {t('workbench.badPage')}
            </div>
          )}
          <div className="flex-1 overflow-auto bg-surface-overlay">
            {bookId && page && (
              <div className="relative mx-auto" style={{ maxWidth: 780 }}>
                <img src={api.pageImageUrl(bookId, pageNo)} alt={`page ${pageNo}`} className="w-full block" />
                {highlight && page.page_width && page.page_height && (
                  <div className="absolute pointer-events-none border-2 border-amber-500 bg-amber-300/20"
                    style={{
                      left: `${(highlight.x0 / page.page_width) * 100}%`,
                      top: `${(highlight.y0 / page.page_height) * 100}%`,
                      width: `${((highlight.x1 - highlight.x0) / page.page_width) * 100}%`,
                      height: `${((highlight.y1 - highlight.y0) / page.page_height) * 100}%`,
                    }} />
                )}
              </div>
            )}
            {!bookId && <div className="p-8 text-sm text-text-muted text-center">{t('workbench.noBook')}</div>}
          </div>
        </div>

        <div className="w-1/2 flex flex-col min-h-0">
          <div className="shrink-0 flex border-b border-border-subtle bg-surface-raised">
            {([['text', t('workbench.textTab')],
               ['candidates', `${t('workbench.candidates')} (${candidates.length})`],
               ['nodes', `${t('workbench.nodes')} (${nodes.length})`]] as [RightTab, string][])
              .map(([key, label]) => (
                <button key={key} onClick={() => setTab(key)}
                  className={`px-4 py-2 text-xs border-b-2 transition-colors ${tab === key
                    ? 'border-accent-blue text-text-primary font-medium'
                    : 'border-transparent text-text-muted hover:text-text-primary'}`}>
                  {label}
                </button>
              ))}
          </div>

          {tab === 'text' && page && (
            <PageTextEditor
              text={page.text}
              onSave={saveText}
              onQuote={setQuoteDraft}
              saving={busy === 'save'}
              labels={{
                quote: t('workbench.quote'),
                save: t('workbench.save'),
                saved: t('workbench.saved'),
                selected: (n) => `${t('workbench.selected')} ${n}`,
                chars: (n) => `${n} ${t('workbench.chars')}`,
              }}
            />
          )}
          {tab === 'text' && !page && <div className="p-6 text-sm text-text-muted">{t('workbench.noBook')}</div>}

          {tab === 'candidates' && (
            <div className="flex-1 overflow-auto">
              {candidates.length === 0 && (
                <div className="p-6 text-sm text-text-muted text-center">{t('workbench.noCandidates')}</div>
              )}
              {candidates.map((c) => (
                <div key={c.id} className="p-3 border-b border-border-subtle">
                  <div className="flex items-center gap-2">
                    <span className="text-2xs px-1.5 py-0.5 rounded bg-surface-overlay text-text-muted">{c.entity_type}</span>
                    <span className="text-sm font-medium text-text-primary flex-1 truncate">{c.name}</span>
                    <span className="text-2xs text-text-dim">p{c.page_start}-{c.page_end}</span>
                  </div>
                  {c.quote && (
                    <p className="mt-1.5 text-2xs text-text-muted italic border-l-2 border-amber-400 pl-2 line-clamp-3">
                      “{c.quote}”
                    </p>
                  )}
                  <details className="mt-1.5">
                    <summary className="text-2xs text-text-dim cursor-pointer">content</summary>
                    <pre className="mt-1 text-2xs whitespace-pre-wrap break-words bg-surface-overlay p-2 rounded max-h-40 overflow-auto">{c.content}</pre>
                  </details>
                  {c.relations?.length > 0 && (
                    <div className="mt-1.5 text-2xs text-text-dim truncate">
                      {c.relations.map((r) => `${r.type} → ${r.target}`).join(' · ')}
                    </div>
                  )}
                  <div className="mt-2 flex gap-2 flex-wrap">
                    <button className={primary} onClick={() => confirm(c)}>{t('workbench.confirm')}</button>
                    <button className={btn} onClick={() => reject(c.id)}>{t('workbench.reject')}</button>
                    <button className={btn} onClick={() => setMergeFor(mergeFor === c.id ? null : c.id)}>{t('workbench.merge')}</button>
                  </div>
                  {mergeFor === c.id && (
                    <select
                      className="mt-2 w-full text-xs bg-surface-overlay border border-border-subtle rounded-md px-2 py-1"
                      defaultValue=""
                      onChange={(e) => merge(c.id, e.target.value)}
                    >
                      <option value="" disabled>{t('workbench.merge')}</option>
                      {nodes.map((n) => <option key={n.id} value={n.id}>{n.name} · p{n.page_start}</option>)}
                    </select>
                  )}
                </div>
              ))}
            </div>
          )}

          {tab === 'nodes' && (
            <div className="flex-1 overflow-auto">
              {nodes.length === 0 && <div className="p-6 text-sm text-text-muted text-center">{t('workbench.noNodes')}</div>}
              {nodes.map((n) => (
                <div key={n.id} className="px-3 py-2 border-b border-border-subtle flex items-center gap-2">
                  <span className="text-2xs px-1.5 rounded bg-surface-overlay text-text-muted">{n.entity_type}</span>
                  <span className="text-xs text-text-primary flex-1 truncate">{n.name}</span>
                  <span className="text-2xs text-text-dim">p{n.page_start}-{n.page_end}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {quoteDraft && (
        <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-t border-amber-200 bg-amber-50 text-2xs text-amber-900">
          <span className="font-medium">{t('workbench.quoteDraft')}:</span>
          <span className="flex-1 truncate">“{quoteDraft.slice(0, 140)}”</span>
          <button className="underline" onClick={() => setQuoteDraft('')}>{t('workbench.clear')}</button>
        </div>
      )}
    </div>
  )
}
