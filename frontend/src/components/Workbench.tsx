import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../stores/appStore'
import { useI18n } from '../i18n/useI18n'
import * as api from '../services/api'
import type { Candidate, ConfirmedNode, PageDetail, PageInfo } from '../types'
import Button from './ui/Button'
import EmptyState from './ui/EmptyState'
import ConfirmDialog from './ui/ConfirmDialog'
import { EntityBadge, StatusBadge } from './ui/Badge'
import PageTextEditor from './PageTextEditor'
import { useLongTask } from '../hooks/useLongTask'
import {
  QuoteStrip, PageSheet, LongTaskStatus, UndoToast,
  MergePreview, RelationNote, ConfirmedSummary,
} from './workbench/WorkbenchPanels'

type RightTab = 'text' | 'candidates'

interface UndoState { label: string; run: () => void }

export default function Workbench() {
  const { books, selectedBookId, selectBook, setStatus, setAlert,
          confirmedSummaryOpen, setConfirmedSummaryOpen } = useAppStore()
  const { t } = useI18n()
  const bookId = selectedBookId

  const [pages, setPages] = useState<PageInfo[]>([])
  const [page, setPage] = useState<PageDetail | null>(null)
  const [pageNo, setPageNo] = useState(1)
  const [windowSize, setWindowSize] = useState(1)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [nodes, setNodes] = useState<ConfirmedNode[]>([])
  const [tab, setTab] = useState<RightTab>('text')
  const [msg, setMsg] = useState('')
  const [quoteDraft, setQuoteDraft] = useState('')
  const [dirty, setDirty] = useState(false)
  const [mergeFor, setMergeFor] = useState<string | null>(null)
  const [dropped, setDropped] = useState(0)
  const [undo, setUndo] = useState<UndoState | null>(null)
  const [pendingPage, setPendingPage] = useState<number | null>(null)
  const [confirmReimport, setConfirmReimport] = useState(false)
  const [mergeTarget, setMergeTarget] = useState<{ candidateId: string; nodeId: string } | null>(null)
  const [narrow, setNarrow] = useState(() => window.innerWidth < 1024)
  const [narrowView, setNarrowView] = useState<'page' | 'text'>('text')

  const { state: task, start, setPhase, stop, elapsedLabel } = useLongTask(75)
  const abortRef = useRef<AbortController | null>(null)
  const hardTimer = useRef<number | null>(null)
  const ocrWorkerRef = useRef<{ terminate: () => Promise<unknown> } | null>(null)
  const editorFocusRef = useRef<HTMLDivElement>(null)

  const total = pages.length
  const endPage = Math.min(pageNo + windowSize - 1, total || pageNo)

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 1024)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

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

  useEffect(() => {
    if (!task.active || task.elapsedSec === 0 || task.elapsedSec % 10 !== 0) return
    setStatus(`${task.phase} · ${elapsedLabel}`)
  }, [task.active, task.elapsedSec, task.phase, elapsedLabel, setStatus])

  useEffect(() => {
    if (!undo) return
    const timer = window.setTimeout(() => setUndo(null), 8000)
    return () => window.clearTimeout(timer)
  }, [undo])

  const cancelRunningTask = useCallback(() => {
    abortRef.current?.abort()
    ocrWorkerRef.current?.terminate()
    ocrWorkerRef.current = null
    if (hardTimer.current !== null) window.clearTimeout(hardTimer.current)
    stop()
    setMsg(t('workbench.cancelled'))
    setStatus(t('workbench.cancelled'))
  }, [stop, setStatus, t])

  const analyze = async () => {
    if (!bookId || !total || task.active) return
    const controller = new AbortController()
    abortRef.current = controller
    start('extract', `${t('workbench.analyzing')} p${pageNo}–p${endPage}`)
    hardTimer.current = window.setTimeout(() => controller.abort(), 120000)
    try {
      const r = await api.extractWindow(bookId, pageNo, endPage, controller.signal)
      await loadCandidates()
      setTab('candidates')
      setDropped(r.relations_dropped ?? 0)
      setMsg(`${r.candidates?.length ?? 0} 个候选 · p${pageNo}–p${endPage}`)
      setStatus(`${r.candidates?.length ?? 0} 个候选`)
    } catch (e) {
      const err = e as Error
      if (err.name === 'AbortError') {
        setMsg(t('workbench.cancelled'))
        setStatus(t('workbench.cancelled'))
      } else {
        setAlert(err.message)
        setMsg(err.message)
      }
    } finally {
      if (hardTimer.current !== null) window.clearTimeout(hardTimer.current)
      abortRef.current = null
      stop()
    }
  }

  const runOcr = async () => {
    if (!bookId || task.active) return
    start('ocr-download', '首次需联网下载中文语言包（仅需一次）')
    try {
      const { createWorker } = await import('tesseract.js')
      const worker = await createWorker('chi_sim+eng')
      ocrWorkerRef.current = worker
      setPhase('识别中')
      const url = `${window.location.origin}${api.pageImageUrl(bookId, pageNo)}`
      const { data } = await worker.recognize(url)
      await worker.terminate()
      ocrWorkerRef.current = null
      const r = await api.submitOcr(bookId, pageNo, data.text || '', data.confidence || 0)
      setMsg(r.needs_manual ? t('workbench.ocrFailed') : t('workbench.ocrDone'))
      setStatus(r.needs_manual ? t('workbench.ocrFailed') : t('workbench.ocrDone'))
      await loadPage(); await loadPages()
      setTab('text')
      setNarrowView('text')
    } catch (e) {
      setAlert(`OCR: ${String(e).slice(0, 100)}`)
      setMsg(`OCR: ${String(e).slice(0, 100)}`)
    } finally {
      if (ocrWorkerRef.current) { await ocrWorkerRef.current.terminate(); ocrWorkerRef.current = null }
      stop()
    }
  }

  const skipOcr = () => {
    setTab('text')
    setNarrowView('text')
    setMsg(t('workbench.manualInput'))
    const prose = editorFocusRef.current?.querySelector('.ProseMirror') as HTMLElement | null
    prose?.focus()
  }

  const reimport = async () => {
    if (!bookId) return
    setConfirmReimport(false)
    start('import', t('workbench.importing'))
    try {
      const r = await api.importPages(bookId)
      await loadPages()
      setPageNo(1)
      setPage(await api.getPage(bookId, 1))
      setMsg(t('workbench.pagesImported').replace('{n}', String(r.page_count)))
    } catch (e) { setAlert(String(e)) }
    finally { stop() }
  }

  const saveText = async (text: string) => {
    if (!bookId) return
    await api.savePageText(bookId, pageNo, text)
    await loadPage(); await loadPages()
    setMsg(t('workbench.saved'))
    setStatus(t('workbench.saved'))
  }

  const pushUndo = (label: string, token: string | undefined, refresh: () => Promise<void>) => {
    setUndo({
      label,
      run: async () => {
        if (!token) { setAlert(t('workbench.undoFailed')); return }
        const ok = await api.undoAction(token).catch(() => false)
        if (!ok) { setAlert(t('workbench.undoFailed')); return }
        await refresh()
        setUndo(null)
      },
    })
  }

  const confirm = async (c: Candidate) => {
    const preview = await api.previewCandidate(c.id).catch(() => null)
    const res = await api.confirmCandidate(c.id, quoteDraft || undefined)
    setQuoteDraft('')
    await loadCandidates(); await loadNodes()
    setMsg(`${res.action === 'merged' ? '已合并' : '已确认'} · ${res.node_id?.slice(0, 8) ?? ''}`)
    setStatus(`${res.action === 'merged' ? '已合并' : '已确认'}「${c.name}」`)
    const count = res.relations_dropped ?? preview?.relations_dropped?.length ?? 0
    setDropped(count)
    pushUndo(`已确认「${c.name}」`, res.undo_token, async () => { await loadCandidates(); await loadNodes() })
  }

  const reject = async (c: Candidate) => {
    setCandidates((prev) => prev.filter((x) => x.id !== c.id))
    const res = await api.rejectCandidate(c.id)
    setStatus(`已驳回「${c.name}」`)
    pushUndo(`已驳回「${c.name}」`, res.undo_token, loadCandidates)
  }

  const doMerge = async () => {
    if (!mergeTarget) return
    await api.mergeCandidate(mergeTarget.candidateId, mergeTarget.nodeId)
    setMergeTarget(null)
    setMergeFor(null)
    await loadCandidates(); await loadNodes()
    setStatus('已合并到既有节点')
  }

  const goPage = (n: number) => {
    if (n < 1 || n > total) return
    if (dirty) { setPendingPage(n); return }
    setPageNo(n)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const editable = target?.closest('.ProseMirror, input, textarea, select, [contenteditable="true"]')
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); void analyze(); return }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && undo) { e.preventDefault(); void undo.run(); return }
      if (editable) return
      if (e.key === 'ArrowLeft') goPage(pageNo - 1)
      else if (e.key === 'ArrowRight') goPage(pageNo + 1)
      else if (e.key === 'Escape') {
        if (undo) setUndo(null)
        else if (quoteDraft) setQuoteDraft('')
        else if (task.active) cancelRunningTask()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const sameNameNode = (c: Candidate) =>
    nodes.find((n) => n.name === c.name && n.entity_type === c.entity_type)

  const candidatePanel = (
    <div className="flex-1 overflow-auto p-3">
      {dropped > 0 && <div className="mb-2"><RelationNote dropped={dropped} /></div>}
      {candidates.length === 0 ? (
        <EmptyState>{t('workbench.noCandidates')}</EmptyState>
      ) : (
        <div className="flex flex-col gap-cardgap">
          {candidates.map((c) => {
            const twin = sameNameNode(c)
            return (
              <div key={c.id} className="rounded-card border border-ag-line1 bg-ag-bg3 p-card">
                <div className="flex items-center gap-2">
                  <EntityBadge type={c.entity_type} />
                  <span className="text-h3 font-medium text-ag-ink1 flex-1 truncate">{c.name}</span>
                  <span className="ag-mono text-micro text-ag-ink3">p{c.page_start}-{c.page_end}</span>
                </div>
                {c.quote && (
                  <p className="ag-quote mt-2 text-caption text-ag-ink3 line-clamp-3">“{c.quote}”</p>
                )}
                <details className="mt-2">
                  <summary className="text-caption text-ag-ink3 cursor-pointer">content</summary>
                  <pre className="mt-1 text-micro whitespace-pre-wrap break-words bg-ag-bg2 p-2 rounded-btn max-h-40 overflow-auto">{c.content}</pre>
                </details>
                {c.relations?.length > 0 && (
                  <div className="mt-2 text-micro text-ag-ink3 truncate">
                    {c.relations.map((r) => `${r.type} → ${r.target}`).join(' · ')}
                  </div>
                )}
                {twin && (
                  <div className="mt-2">
                    <MergePreview targetName={twin.name} pageEnd={c.page_end} />
                  </div>
                )}
                <div className="mt-3 flex gap-2 flex-wrap">
                  <Button size="sm" variant="primary" onClick={() => void confirm(c)}>{t('workbench.confirm')}</Button>
                  <Button size="sm" onClick={() => void reject(c)}>{t('workbench.reject')}</Button>
                  <Button size="sm" variant="ghost" onClick={() => setMergeFor(mergeFor === c.id ? null : c.id)}>
                    {t('workbench.merge')}
                  </Button>
                  {c.status === 'pending' && page?.status === 'bad_page' && (
                    <Button size="sm" variant="ghost" onClick={skipOcr}>{t('workbench.skipOcr')}</Button>
                  )}
                </div>
                {mergeFor === c.id && (
                  <select
                    className="ag-focus-ring mt-2 w-full text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1"
                    defaultValue=""
                    onChange={(e) => e.target.value && setMergeTarget({ candidateId: c.id, nodeId: e.target.value })}
                  >
                    <option value="" disabled>{t('workbench.merge')}</option>
                    {nodes.map((n) => <option key={n.id} value={n.id}>{n.name} · p{n.page_start}</option>)}
                  </select>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )

  return (
    <div className="relative flex flex-col h-full min-h-0">
      <div className="shrink-0 flex items-center gap-2.5 px-4 h-topbar border-b border-ag-line1 bg-ag-bg1 overflow-x-auto">
        <select
          value={bookId ?? ''}
          onChange={(e) => selectBook(e.target.value)}
          className="ag-focus-ring text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-1 max-w-[190px] truncate"
          aria-label={t('workbench.selectBook')}
        >
          <option value="" disabled>{t('workbench.selectBook')}</option>
          {books.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
        </select>
        <div className="w-px h-5 bg-ag-line2 shrink-0" />
        <Button size="sm" onClick={() => goPage(pageNo - 1)} disabled={!total || pageNo <= 1}>‹</Button>
        <span className="ag-mono text-caption text-ag-ink2 whitespace-nowrap">{pageNo} / {total || '–'}</span>
        <Button size="sm" onClick={() => goPage(pageNo + 1)} disabled={!total || pageNo >= total}>›</Button>
        <span className="text-caption text-ag-ink3 whitespace-nowrap">{t('workbench.window')}</span>
        <select
          value={windowSize}
          onChange={(e) => setWindowSize(Number(e.target.value))}
          className="ag-focus-ring text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-1.5 py-1"
          aria-label={t('workbench.window')}
        >
          {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <span className="ag-mono text-micro text-ag-ink3 whitespace-nowrap">p{pageNo}–p{endPage}</span>
        <Button size="sm" variant="primary" disabled={!bookId || !total || task.active} onClick={() => void analyze()}>
          {t('workbench.analyze')}
        </Button>
        <Button size="sm" disabled={!bookId || !total || task.active} onClick={() => void runOcr()}>
          {t('workbench.ocr')}
        </Button>
        <Button size="sm" variant="ghost" disabled={!bookId || task.active} onClick={() => setConfirmReimport(true)}>
          {t('workbench.reimport')}
        </Button>
        {page && <StatusBadge status={page.status} />}
        {msg && <span className="ml-auto text-caption text-ag-ink3 truncate max-w-[260px]">{msg}</span>}
      </div>

      {task.active && (
        <LongTaskStatus state={task} elapsedLabel={elapsedLabel} onCancel={cancelRunningTask} />
      )}

      {narrow && (
        <div className="shrink-0 flex border-b border-ag-line1 bg-ag-bg1">
          {([['page', t('workbench.showPage')], ['text', t('workbench.showText')]] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setNarrowView(k)}
              className={`ag-focus-ring flex-1 py-2 text-caption border-b-2 ${narrowView === k ? 'border-ag-cinnabar text-ag-ink1' : 'border-transparent text-ag-ink3'}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {(!narrow || narrowView === 'page') && (
          <div className={`${narrow ? 'w-full' : 'w-[46%]'} flex flex-col min-w-0 bg-ag-bg0`}>
            {bookId && page ? (
              <PageSheet
                bookId={bookId}
                pageNo={pageNo}
                blocks={page.blocks}
                quote={quoteDraft}
                pageWidth={page.page_width}
                pageHeight={page.page_height}
                onBlockClick={() => { setTab('text'); setNarrowView('text') }}
              />
            ) : (
              <div className="p-6"><EmptyState>{t('workbench.noBook')}</EmptyState></div>
            )}
          </div>
        )}
        {!narrow && <div className="ag-gutter" aria-hidden="true" />}
        {(!narrow || narrowView === 'text') && (
          <div className={`${narrow ? 'w-full' : 'w-[54%]'} flex flex-col min-w-0 bg-ag-bg2`} ref={editorFocusRef}>
            <QuoteStrip quote={quoteDraft} onClear={() => setQuoteDraft('')} />
            <div className="shrink-0 flex border-b border-ag-line1 bg-ag-bg1">
              {([['text', t('workbench.textTab')], ['candidates', `${t('workbench.candidates')} (${candidates.length})`]] as const).map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => setTab(k)}
                  className={`ag-focus-ring px-4 py-2 text-caption border-b-2 ${tab === k ? 'border-ag-cinnabar text-ag-ink1 font-medium' : 'border-transparent text-ag-ink3 hover:text-ag-ink1'}`}
                >
                  {label}
                </button>
              ))}
            </div>
            {tab === 'text' ? (
              page ? (
                <div className="flex-1 min-h-0">
                  <PageTextEditor
                    text={page.text}
                    onSave={(text) => void saveText(text)}
                    onQuote={setQuoteDraft}
                    onDirtyChange={setDirty}
                    saving={false}
                  />
                </div>
              ) : (
                <div className="p-6"><EmptyState>{t('workbench.noPageText')}</EmptyState></div>
              )
            ) : candidatePanel}
            <ConfirmedSummary
              nodes={nodes}
              open={confirmedSummaryOpen}
              onToggle={() => setConfirmedSummaryOpen(!confirmedSummaryOpen)}
            />
          </div>
        )}
      </div>

      {undo && <UndoToast label={undo.label} onUndo={() => void undo.run()} />}

      <ConfirmDialog
        open={confirmReimport}
        title={t('workbench.reimportTitle')}
        description={t('workbench.reimportDesc')}
        confirmLabel={t('workbench.reimport')}
        destructive
        onConfirm={() => void reimport()}
        onCancel={() => setConfirmReimport(false)}
      />
      <ConfirmDialog
        open={mergeTarget !== null}
        title={t('workbench.merge')}
        description="此操作会改变节点归属与页码范围。"
        confirmLabel={t('workbench.confirm')}
        onConfirm={() => void doMerge()}
        onCancel={() => setMergeTarget(null)}
      />
      <ConfirmDialog
        open={pendingPage !== null}
        title={t('workbench.dirtyTitle')}
        description={t('workbench.dirtyDesc')}
        confirmLabel={t('workbench.discard')}
        cancelLabel={t('workbench.keep')}
        destructive
        onConfirm={() => { setDirty(false); setPageNo(pendingPage!); setPendingPage(null) }}
        onCancel={() => setPendingPage(null)}
      />
    </div>
  )
}
