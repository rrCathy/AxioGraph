import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../stores/appStore'
import { useI18n } from '../i18n/useI18n'
import * as api from '../services/api'
import type { AutoStatus, Candidate, ConfirmedNode, PageDetail, PageInfo, TocItem } from '../types'
import Button from './ui/Button'
import EmptyState from './ui/EmptyState'
import ConfirmDialog from './ui/ConfirmDialog'
import { EntityBadge, StatusBadge } from './ui/Badge'
import PageTextEditor from './PageTextEditor'
import { useLongTask } from '../hooks/useLongTask'
import {
  QuoteStrip, PageViewer, LayoutBar, EnvironmentList, LongTaskStatus, UndoToast,
  MergePreview, RelationNote, ConfirmedSummary,
} from './workbench/WorkbenchPanels'
import StructurePanel from './workbench/StructurePanel'
import TocList from './workbench/TocList'
import PromoteDialog from './workbench/PromoteDialog'
import type { PromoteInit } from './workbench/PromoteDialog'
import AskDialog from './workbench/AskDialog'
import AiReviewPanel from './workbench/AiReviewPanel'

type RightTab = 'text' | 'candidates' | 'ai'
type LeftTab = 'toc' | 'structure'

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
  const [showAllCandidates, setShowAllCandidates] = useState(false)
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
  const [narrow, setNarrow] = useState(() => window.innerWidth < 1200)
  const [narrowView, setNarrowView] = useState<'page' | 'text'>('text')

  // Left function column: tab + narrow-screen drawer visibility
  const [leftTab, setLeftTab] = useState<LeftTab>('toc')
  const [funcOpen, setFuncOpen] = useState(false)
  const [structRefreshKey, setStructRefreshKey] = useState(0)
  const [autoOpen, setAutoOpen] = useState(false)
  const [moreActionsOpen, setMoreActionsOpen] = useState(false)
  const [autoStatus, setAutoStatus] = useState<AutoStatus | null>(null)
  const autoStatusRef = useRef<AutoStatus | null>(null)
  const [autoRange, setAutoRange] = useState({ start: 1, end: 0 })
  const [autoWindowSize, setAutoWindowSize] = useState(2)
  const [autoChapters, setAutoChapters] = useState<TocItem[] | null>(null)
  const [structuredText, setStructuredText] = useState(true)
  const [envPanelOpen, setEnvPanelOpen] = useState(false)
  const [activeEnvIndex, setActiveEnvIndex] = useState<number | null>(null)
  const [promoteInit, setPromoteInit] = useState<(PromoteInit & { sourceLabel: string }) | null>(null)
  const [askSelection, setAskSelection] = useState<string | null>(null)
  const [aiRefreshKey, setAiRefreshKey] = useState(0)
  const [aiBusy, setAiBusy] = useState(false)

  const { state: task, start, setPhase, stop, elapsedLabel } = useLongTask(75)
  const abortRef = useRef<AbortController | null>(null)
  const hardTimer = useRef<number | null>(null)
  const ocrWorkerRef = useRef<{ terminate: () => Promise<unknown> } | null>(null)
  const taskIdRef = useRef<string | null>(null)
  const editorFocusRef = useRef<HTMLDivElement>(null)

  const total = pages.length
  const endPage = Math.min(pageNo + windowSize - 1, total || pageNo)

  // Candidates are page-scoped: only show those produced by the window the
  // user is actually looking at. A cover page must never inherit pending
  // items extracted from chapter pages weeks ago.
  const windowCandidates = useMemo(
    () => candidates.filter((c) =>
      Number(c.page_start) <= endPage && Number(c.page_end) >= pageNo),
    [candidates, pageNo, endPage],
  )
  const visibleCandidates = showAllCandidates ? candidates : windowCandidates
  const otherPending = candidates.length - windowCandidates.length

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 1200)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const loadPages = useCallback(async () => {
    if (!bookId) { setPages([]); return }
    const r = await api.listPages(bookId)
    setPages(r.pages || [])
  }, [bookId])

  // Visited pages stay in a small LRU cache so flipping back and forth is
  // instant; a request serial guards against stale responses overtaking the
  // page the user has already navigated to.
  const pageCacheRef = useRef<Map<string, PageDetail>>(new Map())
  const pageReqRef = useRef(0)
  const invalidatePage = useCallback((n?: number) => {
    if (!bookId) return
    if (n == null) {
      for (const k of [...pageCacheRef.current.keys()]) {
        if (k.startsWith(`${bookId}#`)) pageCacheRef.current.delete(k)
      }
    } else {
      pageCacheRef.current.delete(`${bookId}#${n}`)
    }
  }, [bookId])

  const [pageLoading, setPageLoading] = useState(false)
  // Geometry of the ORIGINAL page, fetched on its own cheap endpoint. Keeping
  // it out of `page` lets the image appear before recognition finishes. It is
  // kept across flips (same book = same page size) so the picture never blinks.
  const [pageGeom, setPageGeom] = useState<{ w: number; h: number } | null>(null)
  const loadPage = useCallback(async (target?: number) => {
    const n = target ?? pageNo
    if (!bookId) { setPage(null); setPageGeom(null); return }
    const key = `${bookId}#${n}`
    const cached = pageCacheRef.current.get(key)
    if (cached) {
      setPage(cached)
      if (cached.page_width && cached.page_height) {
        setPageGeom({ w: cached.page_width, h: cached.page_height })
      }
      setPageLoading(false)
      return
    }
    const req = ++pageReqRef.current
    setPageLoading(true)
    // Clear only the extracted text, never the original page image. Showing
    // the previous page's text under a new page reads as "recognition lagged".
    setPage(null)
    setActiveEnvIndex(null)
    setEnvPanelOpen(false)
    // Stage 1 (milliseconds): geometry -> the rendered page shows up at once.
    void api.getPageMeta(bookId, n).then((meta) => {
      if (pageReqRef.current !== req) return
      if (meta.page_width && meta.page_height) {
        setPageGeom({ w: meta.page_width, h: meta.page_height })
      }
    }).catch(() => { /* the image still renders at the default zoom */ })
    // Stage 2 (seconds on an uncached page): layout recognition + editable text.
    try {
      const data = await api.getPage(bookId, n)
      if (pageReqRef.current !== req) return // user moved on; drop stale data
      pageCacheRef.current.set(key, data)
      if (pageCacheRef.current.size > 60) {
        const oldest = pageCacheRef.current.keys().next().value
        if (oldest != null) pageCacheRef.current.delete(oldest)
      }
      setPage(data)
      if (data.page_width && data.page_height) {
        setPageGeom({ w: data.page_width, h: data.page_height })
      }
    } catch {
      if (pageReqRef.current === req) setPage(null)
    } finally {
      if (pageReqRef.current === req) setPageLoading(false)
    }
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

  useEffect(() => { setPageNo(1); setPageGeom(null); loadPages() }, [bookId, loadPages])
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

  useEffect(() => { autoStatusRef.current = autoStatus }, [autoStatus])

  const cancelRunningTask = useCallback(() => {
    if (taskIdRef.current) {
      void api.cancelTask(taskIdRef.current).catch(() => {})
      taskIdRef.current = null
    }
    abortRef.current?.abort()
    ocrWorkerRef.current?.terminate()
    ocrWorkerRef.current = null
    if (hardTimer.current !== null) window.clearTimeout(hardTimer.current)
    stop()
    setMsg('请求已取消，服务端将在写入前停止')
    setStatus('请求已取消，服务端将在写入前停止')
  }, [stop, setStatus])

  const analyze = async () => {
    if (!bookId || !total || task.active) return
    const controller = new AbortController()
    abortRef.current = controller
    const taskId = crypto.randomUUID()
    taskIdRef.current = taskId
    start('extract', `${t('workbench.analyzing')} p${pageNo}–p${endPage}`)
    hardTimer.current = window.setTimeout(() => controller.abort(), 120000)
    try {
      const r = await api.extractWindow(bookId, pageNo, endPage, controller.signal, taskId)
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
      taskIdRef.current = null
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
      invalidatePage(pageNo)
      await loadPage(pageNo); await loadPages()
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

  const runVisionOcr = async () => {
    if (!bookId || !total || task.active) return
    const controller = new AbortController()
    abortRef.current = controller
    const taskId = crypto.randomUUID()
    taskIdRef.current = taskId
    start('ocr-recognize', t('workbench.visionOcr'))
    hardTimer.current = window.setTimeout(() => controller.abort(), 240000)
    try {
      const r = await api.visionOcr(bookId, pageNo, taskId, controller.signal)
      if (r.cancelled) {
        setMsg(t('workbench.cancelled'))
        setStatus(t('workbench.cancelled'))
      } else if (r.ok) {
        setMsg(r.needs_manual ? t('workbench.visionFailed') : t('workbench.visionDone'))
        setStatus(r.needs_manual ? t('workbench.visionFailed') : t('workbench.visionDone'))
        invalidatePage(pageNo)
        await loadPage(pageNo)
        await loadPages()
        setTab('text')
        setNarrowView('text')
      } else {
        setMsg(t('workbench.visionFailed'))
        setStatus(t('workbench.visionFailed'))
      }
    } catch (e) {
      const err = e as Error
      if (err.name === 'AbortError') {
        setMsg(t('workbench.cancelled'))
        setStatus(t('workbench.cancelled'))
      } else {
        setAlert(`vision OCR: ${err.message.slice(0, 120)}`)
        setMsg(t('workbench.visionFailed'))
      }
    } finally {
      if (hardTimer.current !== null) window.clearTimeout(hardTimer.current)
      abortRef.current = null
      taskIdRef.current = null
      stop()
    }
  }

  const startAuto = async (from: number, to: number) => {
    if (!bookId || !total || autoStatusRef.current?.status === 'running') return
    const s = Math.max(1, Math.min(from, total))
    const e = Math.max(s, Math.min(to, total))
    setAutoRange({ start: s, end: e })
    try {
      const r = await api.startAutoExtract(bookId, s, e, autoWindowSize)
      setAutoStatus({
        task_id: r.task_id, book_id: bookId, status: 'running',
        range: [s, e], window_size: r.window_size ?? autoWindowSize,
        window_total: r.window_total, window_done: 0,
        current_window: null, failed_windows: [], next_window: s,
      })
      setMsg('')
      setStatus(`${t('workbench.autoTitle')}: p${s}–p${e}`)
    } catch (err) {
      setAlert((err as Error).message.slice(0, 140))
    }
  }

  const stopAuto = () => {
    const cur = autoStatusRef.current
    if (cur?.task_id) void api.cancelTask(cur.task_id).catch(() => {})
    setMsg('已请求停止；当前窗口在写入前即停')
    setStatus('已请求停止')
  }

  const onChapterSelect = (idxStr: string) => {
    if (!autoChapters || idxStr === '') return
    const idx = Number(idxStr)
    const ch = autoChapters[idx]
    const next = autoChapters[idx + 1]
    if (!ch?.pdf_page) return
    const s = ch.pdf_page
    const e = next?.pdf_page ? Math.min(next.pdf_page - 1, total || s) : (total || s)
    setAutoRange({ start: s, end: Math.max(s, e) })
  }

  // Poll the auto task every 3s while it runs; refresh candidates on finish.
  useEffect(() => {
    const taskId = autoStatus?.task_id
    if (!taskId || autoStatus?.status !== 'running') return
    const timer = window.setInterval(async () => {
      const cur = autoStatusRef.current
      if (!cur || cur.status !== 'running' || !bookId) return
      const s = await api.getAutoStatus(bookId, taskId).catch(() => null)
      if (!s) return
      setAutoStatus(s)
      if (s.status !== 'running') {
        await loadCandidates()
        if (s.status === 'done') {
          setMsg(`${t('workbench.autoDone')}${s.failed_windows.length ? ` · ${t('workbench.autoFailed').replace('{n}', String(s.failed_windows.length))}` : ''}`)
          setStatus(t('workbench.autoDone'))
        } else if (s.status === 'cancelled') {
          setMsg(t('workbench.autoCancelled'))
          setStatus(t('workbench.autoCancelled'))
        } else if (s.status === 'error') {
          setAlert(s.error || 'auto extract error')
        }
      }
    }, 3000)
    return () => window.clearInterval(timer)
  }, [autoStatus?.task_id, autoStatus?.status, bookId, loadCandidates, setStatus, setAlert, t])

  // Opening the auto bar loads chapter ranges (if the structure is confirmed).
  useEffect(() => {
    if (!autoOpen || !bookId) return
    setAutoRange((r) => ({ ...r, start: pageNo, end: total || pageNo }))
    api.getStructure(bookId)
      .then((s) => {
        const chapters = (s?.toc || []).filter((it: TocItem) => it.pdf_page && it.pdf_page > 0)
        setAutoChapters(chapters.length ? chapters : null)
      })
      .catch(() => setAutoChapters(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpen, bookId])

  const reimport = async () => {
    if (!bookId) return
    setConfirmReimport(false)
    start('import', t('workbench.importing'))
    try {
      const r = await api.importPages(bookId)
      await loadPages()
      pageCacheRef.current.clear() // page index rebuilt: drop every cached page
      setPageNo(1)
      setPage(await api.getPage(bookId, 1))
      setMsg(t('workbench.pagesImported').replace('{n}', String(r.page_count)))
    } catch (e) { setAlert(String(e)) }
    finally { stop() }
  }

  const saveText = async (text: string) => {
    if (!bookId) return
    await api.savePageText(bookId, pageNo, text)
    invalidatePage(pageNo)
    await loadPage(pageNo); await loadPages()
    setMsg(t('workbench.saved'))
    setStatus(t('workbench.saved'))
  }

  // ── Promote / ask (selection in text, or environment row) ────────────

  const envKindToEntityType = (kind: string) => {
    const map: Record<string, string> = {
      axiom: 'AXIOM', theorem: 'THEOREM', lemma: 'LEMMA',
      proposition: 'PROPOSITION', corollary: 'COROLLARY',
      definition: 'DEFINITION', example: 'EXAMPLE', remark: 'REMARK',
      conjecture: 'CONJECTURE', claim: 'CLAIM', fact: 'FACT',
      assumption: 'ASSUMPTION', principle: 'PRINCIPLE',
      notation: 'NOTATION', convention: 'CONCEPT',
      problem: 'CONCEPT', warning: 'CONCEPT', exercise: 'CONCEPT',
      proof: 'PROOF',
    }
    return map[kind] ?? 'CONCEPT'
  }

  const promoteSelection = (text: string) => {
    const firstLine = text.split('\n')[0].trim()
    setPromoteInit({
      entityType: 'DEFINITION',
      name: firstLine.slice(0, 40) || t('promote.title'),
      content: text,
      quote: text.slice(0, 300),
      pageStart: pageNo,
      pageEnd: pageNo,
      sourceLabel: `p${pageNo} 划选 · ${text.length} 字`,
    })
  }

  const promoteEnvironment = (i: number) => {
    const env = page?.environments?.[i]
    if (!env) return
    const kindLabel = env.label || env.kind
    const name = [kindLabel, env.number].filter(Boolean).join(' ')
      + (env.title ? ` ${env.title}` : '')
    setPromoteInit({
      entityType: envKindToEntityType(env.kind),
      name: name.trim().slice(0, 60) || kindLabel,
      content: env.text,
      quote: env.text.split('\n')[0].slice(0, 300),
      pageStart: pageNo,
      pageEnd: pageNo,
      sourceLabel: `p${pageNo} 环境 · ${kindLabel}${env.number ? ' ' + env.number : ''}`,
    })
    setActiveEnvIndex(i)
    setEnvPanelOpen(true)
  }

  const onPromoteDone = async (r: { node_id: string; action: string; undo_token: string; name: string }) => {
    setPromoteInit(null)
    await loadNodes()
    const label = `${r.action === 'merged' ? '已合并到既有节点' : '已入图'}「${r.name}」`
    setMsg(label)
    setStatus(label)
    // Promote actions undo through their own endpoint, not the candidate one.
    setUndo({
      label,
      run: async () => {
        const ok = await api.undoPromote(r.undo_token).catch(() => false)
        if (!ok) { setAlert(t('workbench.undoFailed')); return }
        await loadNodes()
        setUndo(null)
      },
    })
  }

  // ── AI auto-flow: manual "已读" trigger per page ─────────────────────

  const markPageRead = async () => {
    if (!bookId || aiBusy) return
    setAiBusy(true)
    start('extract', t('ai.reading').replace('{n}', String(pageNo)))
    try {
      const r = await api.aiReadPage(bookId, pageNo)
      setAiRefreshKey((k) => k + 1)
      setTab('ai')
      if (r.reason) {
        setMsg(r.reason)
        setStatus(r.reason)
      } else if ((r.items ?? 0) === 0) {
        const label = t('ai.readEmpty')
        setMsg(label)
        setStatus(label)
      } else {
        const label = t('ai.readDone')
          .replace('{n}', String(r.items ?? 0))
          .replace('{m}', String(r.edges ?? 0))
        setMsg(label)
        setStatus(label)
      }
    } catch (e) {
      // 502 here is almost always the local model server (down / 429).
      const raw = String((e as Error).message || e)
      const label = `${t('ai.readFailed')} · ${raw.slice(0, 90)}`
      setMsg(label)
      setStatus(label)
      setAlert(t('ai.readFailed'))
    } finally {
      setAiBusy(false)
      stop()
    }
  }

  const doRelayout = async () => {
    if (!bookId) return
    try {
      await api.relayout(bookId)
      invalidatePage()
      await loadPage()
      setMsg('版面已按 PDF 重排')
      setStatus('版面已重排')
    } catch (e) {
      setAlert(String(e))
    }
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
        else if (autoStatusRef.current?.status === 'running') stopAuto()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const sameNameNode = (c: Candidate) =>
    nodes.find((n) => n.name === c.name && n.entity_type === c.entity_type)

  const candidatePanel = (
    <div className="flex-1 overflow-auto p-3">
      <div className="flex items-center justify-between gap-2 mb-2 text-micro text-ag-ink3">
        <span className="ag-mono">
          {showAllCandidates
            ? t('workbench.candidatesAll').replace('{n}', String(candidates.length))
            : t('workbench.candidatesWindow')
                .replace('{s}', String(pageNo)).replace('{e}', String(endPage))}
        </span>
        {candidates.length > 0 && (
          <button
            onClick={() => setShowAllCandidates((v) => !v)}
            className="ag-focus-ring text-ag-cinnabar hover:underline"
          >
            {showAllCandidates
              ? t('workbench.candidatesOnlyWindow')
              : t('workbench.candidatesShowAll').replace('{n}', String(candidates.length))}
          </button>
        )}
      </div>
      {dropped > 0 && <div className="mb-2"><RelationNote dropped={dropped} /></div>}
      {visibleCandidates.length === 0 ? (
        <EmptyState>
          {!showAllCandidates && otherPending > 0
            ? t('workbench.noCandidatesHere').replace('{n}', String(otherPending))
            : t('workbench.noCandidates')}
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-cardgap">
          {visibleCandidates.map((c) => {
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
      {/* Compact control strip: book, page nav, window, status (36px — the
          app-level nav above already carries the identity row). */}
      <div className="shrink-0 flex items-center gap-2 px-3 h-9 border-b border-ag-line1 bg-ag-bg1">
        <select
          value={bookId ?? ''}
          onChange={(e) => selectBook(e.target.value)}
          className="ag-focus-ring text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-2 py-0.5 max-w-[190px] truncate"
          aria-label={t('workbench.selectBook')}
        >
          <option value="" disabled>{t('workbench.selectBook')}</option>
          {books.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
        </select>
        <div className="w-px h-4 bg-ag-line2 shrink-0" />
        <button
          onClick={() => goPage(pageNo - 1)}
          disabled={!total || pageNo <= 1}
          className="ag-focus-ring w-6 h-6 grid place-items-center text-caption text-ag-ink2 rounded-btn border border-transparent hover:border-ag-line2 hover:text-ag-ink1 disabled:opacity-40"
          aria-label="上一页"
        >‹</button>
        <span className="ag-mono text-caption text-ag-ink2 whitespace-nowrap">{pageNo} / {total || '–'}</span>
        <button
          onClick={() => goPage(pageNo + 1)}
          disabled={!total || pageNo >= total}
          className="ag-focus-ring w-6 h-6 grid place-items-center text-caption text-ag-ink2 rounded-btn border border-transparent hover:border-ag-line2 hover:text-ag-ink1 disabled:opacity-40"
          aria-label="下一页"
        >›</button>
        <div className="w-px h-4 bg-ag-line2 shrink-0" />
        <span className="text-caption text-ag-ink3 whitespace-nowrap">{t('workbench.window')}</span>
        <select
          value={windowSize}
          onChange={(e) => setWindowSize(Number(e.target.value))}
          className="ag-focus-ring text-caption bg-ag-bg2 border border-ag-line2 rounded-btn px-1 py-0.5"
          aria-label={t('workbench.window')}
        >
          {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <span className="ag-mono text-micro text-ag-ink3 whitespace-nowrap">
          {windowSize === 1 ? `p${pageNo}` : `p${pageNo}–p${endPage}`}
        </span>
        <div className="ml-auto flex items-center gap-2 min-w-0">
          {page && <StatusBadge status={page.status} />}
          {msg && <span className="text-caption text-ag-ink3 truncate max-w-[240px]">{msg}</span>}
          {narrow && (
            <Button size="sm" variant="ghost" onClick={() => setFuncOpen(!funcOpen)} aria-label={t('workbench.funcTitle')} disabled={!bookId}>
              ☰
            </Button>
          )}
        </div>
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
      {/* Left function column — docked on wide screens, drawer on narrow.
          Hidden entirely while no book is selected: dead buttons would just
          be noise; the main pane's empty state carries the call to action. */}
      {bookId && (!narrow || funcOpen) && (
        <>
          {narrow && funcOpen && (
            <div className="absolute inset-0 z-30 bg-black/40" onClick={() => setFuncOpen(false)} aria-hidden="true" />
          )}
          <aside
            className={narrow
              ? 'absolute left-0 top-0 bottom-0 z-40 w-[300px] border-r border-ag-line2 bg-ag-bg1'
              : 'shrink-0 w-[300px] border-r border-ag-line1 bg-ag-bg1 flex flex-col min-h-0'}
            aria-label={t('workbench.funcTitle')}
          >
            {/* Primary actions sit above the tabs — the reader's daily loop
                is these two buttons, not a third tab holding them. */}
            <div className="shrink-0 flex flex-col gap-1.5 px-2.5 py-2.5 border-b border-ag-line1">
              <Button
                variant="primary"
                className="w-full"
                disabled={!total || task.active}
                onClick={() => void analyze()}
              >
                {t('workbench.analyze')}
              </Button>
              <Button
                className="w-full"
                disabled={!total || task.active || aiBusy}
                loading={aiBusy}
                onClick={() => void markPageRead()}
              >
                {t('ai.readBtn')}
              </Button>
              {/* Low-frequency / debug actions live behind a disclosure. */}
              {!moreActionsOpen && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="w-full"
                  onClick={() => setMoreActionsOpen(true)}
                >
                  {t('workbench.moreActions')} ▾
                </Button>
              )}
              {moreActionsOpen && (
                <>
                  <div className="grid grid-cols-2 gap-1.5">
                    <Button size="sm" disabled={!total || task.active} onClick={() => void runVisionOcr()}>
                      {t('workbench.visionOcr')}
                    </Button>
                    <Button size="sm" disabled={!total || task.active} onClick={() => void runOcr()}>
                      {t('workbench.ocr')}
                    </Button>
                  </div>
                  <Button
                    size="sm"
                    variant={autoOpen ? 'primary' : 'ghost'}
                    disabled={!total}
                    onClick={() => setAutoOpen(!autoOpen)}
                  >
                    {autoOpen ? t('workbench.autoClose') : t('workbench.autoTitle')}
                  </Button>
                  <Button size="sm" variant="ghost" disabled={task.active} onClick={() => setConfirmReimport(true)}>
                    {t('workbench.reimport')}
                  </Button>
                  <Button size="sm" variant="ghost" className="w-full" onClick={() => setMoreActionsOpen(false)}>
                    {t('workbench.moreActions')} ▴
                  </Button>
                </>
              )}
            </div>

            {autoOpen && (
              <div className="shrink-0 mx-2.5 mb-2.5 rounded-card border border-ag-line2 bg-ag-bg2 p-2.5 flex flex-col gap-2">
                <span className="text-caption font-medium text-ag-ink2">{t('workbench.autoTitle')}</span>
                {autoChapters && (
                  <select
                    defaultValue=""
                    onChange={(e) => onChapterSelect(e.target.value)}
                    className="ag-focus-ring text-caption bg-ag-bg3 border border-ag-line2 rounded-btn px-2 py-1 w-full min-w-0 truncate"
                    aria-label={t('workbench.autoChapter')}
                  >
                    <option value="" disabled>{t('workbench.autoChapter')}</option>
                    {autoChapters.map((c, i) => (
                      <option key={i} value={i}>
                        {'\u3000'.repeat(Math.max(0, c.level - 1))}{c.title} (p{c.pdf_page})
                      </option>
                    ))}
                  </select>
                )}
                <div className="flex items-center gap-1.5 text-caption text-ag-ink3">
                  <span className="shrink-0">{t('workbench.autoRangeFrom')}</span>
                  <input
                    type="number" min={1} max={total || undefined} value={autoRange.start}
                    onChange={(e) => setAutoRange((r) => ({ ...r, start: Number(e.target.value) }))}
                    className="ag-focus-ring text-caption ag-mono bg-ag-bg3 border border-ag-line2 rounded-btn px-1.5 py-1 w-14"
                    aria-label={t('workbench.autoRangeFrom')}
                  />
                  <span className="shrink-0">–</span>
                  <input
                    type="number" min={1} max={total || undefined} value={autoRange.end}
                    onChange={(e) => setAutoRange((r) => ({ ...r, end: Number(e.target.value) }))}
                    className="ag-focus-ring text-caption ag-mono bg-ag-bg3 border border-ag-line2 rounded-btn px-1.5 py-1 w-14"
                    aria-label={t('workbench.autoRangeTo')}
                  />
                  <select
                    value={autoWindowSize}
                    onChange={(e) => setAutoWindowSize(Number(e.target.value))}
                    className="ag-focus-ring text-caption bg-ag-bg3 border border-ag-line2 rounded-btn px-1 py-1"
                    aria-label={t('workbench.window')}
                  >
                    {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
                {autoStatus?.status === 'running' ? (
                  <div className="flex flex-col gap-1.5">
                    <span className="text-caption text-ag-ink2 ag-mono" aria-live="polite">
                      {t('workbench.autoProgress')
                        .replace('{done}', String(Math.min(autoStatus.window_done + 1, autoStatus.window_total)))
                        .replace('{total}', String(autoStatus.window_total))}
                    </span>
                    {autoStatus.current_window && (
                      <span className="text-caption text-ag-ink3 ag-mono">
                        {t('workbench.autoCurrent')
                          .replace('{s}', String(autoStatus.current_window[0]))
                          .replace('{e}', String(autoStatus.current_window[1]))}
                      </span>
                    )}
                    {autoStatus.failed_windows.length > 0 && (
                      <span className="text-caption text-ag-statusOcr">
                        {t('workbench.autoFailed').replace('{n}', String(autoStatus.failed_windows.length))}
                      </span>
                    )}
                    <Button size="sm" onClick={stopAuto}>{t('workbench.autoStop')}</Button>
                  </div>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    <Button size="sm" variant="primary" disabled={!total} onClick={() => void startAuto(autoRange.start, autoRange.end)}>
                      {t('workbench.autoStart')}
                    </Button>
                    {autoStatus && (autoStatus.status === 'cancelled' || autoStatus.status === 'error') && autoStatus.next_window != null && (
                      <Button size="sm" onClick={() => void startAuto(autoStatus.next_window!, autoStatus.range[1])}>
                        {t('workbench.autoResume')}
                      </Button>
                    )}
                    {autoStatus && autoStatus.failed_windows.length > 0 && (
                      <span className="text-caption text-ag-statusOcr">
                        {t('workbench.autoFailed').replace('{n}', String(autoStatus.failed_windows.length))}
                      </span>
                    )}
                    {autoStatus && autoStatus.status === 'done' && (
                      <span className="text-caption text-ag-ink3 ag-mono">
                        {autoStatus.window_done}/{autoStatus.window_total}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="shrink-0 flex items-center border-b border-ag-line1">
              {([['toc', t('workbench.tocTitle')], ['structure', t('workbench.structure')]] as [LeftTab, string][]).map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => setLeftTab(k)}
                  aria-selected={leftTab === k}
                  className={`ag-focus-ring flex-1 py-1.5 text-caption border-b-2 transition-colors ${
                    leftTab === k ? 'border-ag-cinnabar text-ag-ink1 font-medium' : 'border-transparent text-ag-ink3 hover:text-ag-ink1'
                  }`}
                >
                  {label}
                </button>
              ))}
              {narrow && (
                <button
                  onClick={() => setFuncOpen(false)}
                  className="ag-focus-ring shrink-0 px-3 py-2 text-caption text-ag-ink3 hover:text-ag-ink1"
                  aria-label={t('workbench.structClose')}
                >
                  ✕
                </button>
              )}
            </div>

            <div className="flex-1 min-h-0 flex flex-col">
              {leftTab === 'toc' && (
                <div className="flex-1 min-h-0 overflow-auto">
                  <TocList
                    bookId={bookId ?? ''}
                    pageNo={pageNo}
                    refreshKey={structRefreshKey}
                    onJump={(p) => goPage(Math.max(1, Math.min(p, total || p)))}
                    onOpenStructure={() => setLeftTab('structure')}
                  />
                </div>
              )}
              {leftTab === 'structure' && (
                <StructurePanel
                  bookId={bookId ?? ''}
                  refreshKey={structRefreshKey}
                  onJump={(p) => goPage(Math.max(1, Math.min(p, total || p)))}
                  onConfirmed={() => setStructRefreshKey((k) => k + 1)}
                />
              )}
            </div>

            <div className="shrink-0 px-2.5 py-2 text-micro text-ag-ink3 leading-relaxed border-t border-ag-line1">
              {t('workbench.funcHint')}
            </div>
          </aside>
        </>
      )}

        {(!narrow || narrowView === 'page') && (
          <div className={`${narrow ? 'w-full' : 'flex-1'} flex flex-col min-w-0 bg-ag-bg0`}>
            {bookId ? (
              <PageViewer
                bookId={bookId}
                pageNo={pageNo}
                blocks={page?.blocks ?? []}
                quote={quoteDraft}
                pageWidth={page?.page_width ?? pageGeom?.w}
                pageHeight={page?.page_height ?? pageGeom?.h}
                onBlockClick={() => { setTab('text'); setNarrowView('text') }}
                environments={page?.environments ?? []}
                activeIndex={activeEnvIndex}
                onPick={(i) => {
                  setActiveEnvIndex(i)
                  setEnvPanelOpen(true)
                  setTab('text')
                }}
              />
            ) : (
              <div className="p-6"><EmptyState>{t('workbench.noBook')}</EmptyState></div>
            )}
          </div>
        )}
        {!narrow && <div className="ag-gutter" aria-hidden="true" />}
        {(!narrow || narrowView === 'text') && (
          <div className={`${narrow ? 'w-full' : 'w-[460px] shrink-0'} flex flex-col min-w-0 bg-ag-bg2`} ref={editorFocusRef}>
            <QuoteStrip quote={quoteDraft} onClear={() => setQuoteDraft('')} />
            <div className="shrink-0 flex border-b border-ag-line1 bg-ag-bg1">
              {([['text', t('workbench.textTab')], ['candidates', `${t('workbench.candidates')} (${visibleCandidates.length})`], ['ai', t('ai.tab')]] as const).map(([k, label]) => (
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
              <div className="flex-1 min-h-0 flex flex-col">
                {pageLoading && (
                  <div className="shrink-0 flex items-center gap-2 px-3 py-1 border-b border-ag-line1 bg-ag-bg2" role="status">
                    <span className="inline-block w-1.5 h-1.5 rounded-dot bg-ag-cinnabar animate-pulse" aria-hidden="true" />
                    <span className="text-caption text-ag-ink3">
                      {t('workbench.loadingPage').replace('{n}', String(pageNo))}
                    </span>
                  </div>
                )}
                {page ? (
                  <>
                    <LayoutBar
                      layout={page.layout}
                      environments={page.environments}
                      structured={structuredText}
                      onToggle={setStructuredText}
                      onRelayout={() => void doRelayout()}
                      onShowEnvs={(v) => { setEnvPanelOpen(v); setTab('text') }}
                    />
                    {envPanelOpen && (
                      <EnvironmentList
                        environments={page.environments ?? []}
                        activeIndex={activeEnvIndex}
                        onPick={setActiveEnvIndex}
                        onClose={() => { setEnvPanelOpen(false); setActiveEnvIndex(null) }}
                        onPromote={promoteEnvironment}
                      />
                    )}
                    <div className="flex-1 min-h-0">
                      <PageTextEditor
                        text={structuredText ? (page.layout_text || page.text) : page.text}
                        onSave={(text) => void saveText(text)}
                        onQuote={setQuoteDraft}
                        onPromote={promoteSelection}
                        onAsk={setAskSelection}
                        onDirtyChange={setDirty}
                        saving={false}
                      />
                    </div>
                  </>
                ) : pageLoading ? (
                  // The original page is already visible; only the extracted
                  // text is still being recognized. A skeleton says exactly
                  // that instead of implying the page failed to load.
                  <div className="flex-1 min-h-0 flex flex-col justify-center gap-3 px-8" aria-hidden="true">
                    {[92, 78, 96, 84, 60].map((w, i) => (
                      <div key={i} className="h-2 rounded-dot bg-ag-line1 opacity-70"
                           style={{ width: `${w}%` }} />
                    ))}
                  </div>
                ) : (
                  <div className="p-6"><EmptyState>{t('workbench.noPageText')}</EmptyState></div>
                )}
              </div>
            ) : tab === 'ai' ? (
              <AiReviewPanel
                bookId={bookId ?? ''}
                refreshKey={aiRefreshKey}
                onChanged={() => { void loadNodes() }}
              />
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

      {promoteInit && bookId && (
        <PromoteDialog
          open
          bookId={bookId}
          init={promoteInit}
          sourceLabel={promoteInit.sourceLabel}
          onClose={() => setPromoteInit(null)}
          onDone={(r) => void onPromoteDone(r)}
        />
      )}
      {askSelection !== null && bookId && (
        <AskDialog
          open
          bookId={bookId}
          pageNo={pageNo}
          selection={askSelection}
          onClose={() => setAskSelection(null)}
        />
      )}

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
