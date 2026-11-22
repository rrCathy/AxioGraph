import { useEffect, useRef, useState, useCallback } from 'react'
import cytoscape, { Core } from 'cytoscape'
import { readThemePalette, buildCyStyle } from '../theme/themePalette'
import { THEME_EVENT } from '../theme/theme'
import { entityKeyOf, ENTITY_META, type EntityKey } from '../theme/entityMeta'
import GraphA11yPanel from './graph/GraphA11yPanel'
import RecyclePanel from './graph/RecyclePanel'
import { useAppStore } from '../stores/appStore'
import { searchNodes, getGraph, getTagList, batchDeleteNodes, batchAddTags, recycleRestore } from '../services/api'
import { useI18n } from '../i18n/useI18n'

// ─── Force simulation constants ───
const REPULSION = 8000
const ATTRACTION_K = 0.005
const REST_LENGTH = 150
const DAMPING = 0.80
const CENTER_GRAVITY = 0.0008
const MAX_VELOCITY = 6
const EPSILON = 1

export default function GraphView() {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const rafRef = useRef<number | null>(null)
  const startTimerRef = useRef<number | null>(null)
  const pinnedRef = useRef<Set<string>>(new Set())
  const velRef = useRef<Map<string, [number, number]>>(new Map())
  const runningRef = useRef(true)

  const [simRunning, setSimRunning] = useState(true)
  const { graphData, setGraphData, selectedBookId, books, selectNode, selectBook, lang, selectedNodeId } = useAppStore()
  const selectedBook = books.find((b) => b.id === selectedBookId)
  const { t } = useI18n()

  // The graph tab must load its own data: previously only the books-tab
  // "查看图谱" button fetched it, so switching straight to the graph tab
  // after promoting nodes showed an endless spinner ("打不开").
  const [graphLoading, setGraphLoading] = useState(false)
  const [loadSeq, setLoadSeq] = useState(0)
  useEffect(() => {
    if (!selectedBookId || graphData) { setGraphLoading(false); return }
    let cancelled = false
    setGraphLoading(true)
    getGraph(selectedBookId)
      .then((d) => { if (!cancelled) setGraphData(d) })
      .catch(() => { /* keep the empty state; user can retry */ })
      .finally(() => { if (!cancelled) setGraphLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBookId, graphData, loadSeq])

  // Translate a raw relation_type to the display label based on current language
  const getRelationLabel = useCallback((relationType: string): string => {
    const key = `graph.relations.${relationType}` as const
    return t(key)
  }, [t])

  // ─── Search state ───
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [searchOpen, setSearchOpen] = useState(false)
  const [searching, setSearching] = useState(false)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [typeFilter, setTypeFilter] = useState<EntityKey | null>(null)
  const [listMode, setListMode] = useState(false)

  // ─── Graph management: select mode / tag filter / recycle bin ───
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [tagFilter, setTagFilter] = useState<string | null>(null) // "组:值"
  const [tagGroups, setTagGroups] = useState<Record<string, string[]>>({})
  const [recycleOpen, setRecycleOpen] = useState(false)
  const [gvMsg, setGvMsg] = useState('')
  const [gvUndo, setGvUndo] = useState<string[] | null>(null) // deleted ids
  const [batchBusy, setBatchBusy] = useState(false)
  const [tagDialogOpen, setTagDialogOpen] = useState(false)
  const [tagGroupSel, setTagGroupSel] = useState('学科')
  const [tagValueDraft, setTagValueDraft] = useState('')
  // the cytoscape tap closure captures this ref — state alone would go stale
  const selectModeRef = useRef(false)
  useEffect(() => { selectModeRef.current = selectMode }, [selectMode])

  const refreshGraph = useCallback(() => {
    if (!selectedBookId) return
    getGraph(selectedBookId).then(setGraphData).catch(() => {})
  }, [selectedBookId, setGraphData])

  useEffect(() => {
    if (!selectedBookId) { setTagGroups({}); return }
    getTagList(selectedBookId).then(setTagGroups).catch(() => {})
  }, [selectedBookId, graphData])

  useEffect(() => { if (!selectMode) { setSelectedIds(new Set()) } }, [selectMode])

  // Canvas cannot read CSS variables: re-apply concrete colours on theme change.
  useEffect(() => {
    const onChange = () => {
      const cy = cyRef.current
      if (cy) cy.style(buildCyStyle(readThemePalette()))
    }
    window.addEventListener(THEME_EVENT, onChange)
    return () => window.removeEventListener(THEME_EVENT, onChange)
  }, [])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.batch(() => {
      cy.nodes().forEach((n) => {
        const typeDim = typeFilter !== null && n.data('entity_key') !== typeFilter
        let tagDim = false
        if (tagFilter) {
          const [g, v] = tagFilter.split(':')
          let tags: Array<{ g: string; v: string }> = []
          try { tags = JSON.parse(n.data('tags') || '[]') } catch { /* ignore */ }
          tagDim = !tags.some((tp) => tp.g === g && tp.v === v)
        }
        n.toggleClass('dimmed', typeDim || tagDim)
        n.toggleClass('ag-selected', selectedIds.has(n.id()))
      })
      cy.edges().toggleClass('dimmed', typeFilter !== null || tagFilter !== null)
    })
  }, [typeFilter, tagFilter, selectedIds, graphData])

  // Debounced search
  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (!searchQuery.trim() || !selectedBookId) {
      setSearchResults([])
      setSearchOpen(false)
      return
    }
    setSearching(true)
    searchTimerRef.current = setTimeout(async () => {
      try {
        const data = await searchNodes(selectedBookId, searchQuery.trim())
        const nodes = data.nodes || data || []
        setSearchResults(Array.isArray(nodes) ? nodes.slice(0, 10) : [])
        setSearchOpen(true)
      } catch {
        setSearchResults([])
      } finally {
        setSearching(false)
      }
    }, 300)
    return () => { if (searchTimerRef.current) clearTimeout(searchTimerRef.current) }
  }, [searchQuery, selectedBookId])

  // Close search dropdown on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSearchOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const handleSearchResultClick = (nodeId: string) => {
    selectNode(nodeId)
    setSearchOpen(false)
    setSearchQuery('')
    // Pan to node in cytoscape
    if (cyRef.current && !cyRef.current.destroyed()) {
      const target = cyRef.current.getElementById(nodeId)
      if (target.length) {
        cyRef.current.animate({
          center: { eles: target },
          zoom: Math.max(cyRef.current.zoom(), 1.2),
          duration: 500,
        })
        // Brief highlight flash
        target.addClass('searched-flash')
        setTimeout(() => target.removeClass('searched-flash'), 1500)
      }
    }
  }

  const forceTick = useCallback((cy: Core) => {
    if (!runningRef.current || cy.destroyed()) return

    const nodes = cy.nodes()
    const edges = cy.edges()
    const N = nodes.length
    if (N < 2) { rafRef.current = requestAnimationFrame(() => forceTick(cy)); return }

    // Snapshot positions
    const px = new Float64Array(N)
    const py = new Float64Array(N)
    for (let i = 0; i < N; i++) {
      const p = nodes[i].position()
      px[i] = p.x
      py[i] = p.y
    }

    const fx = new Float64Array(N)
    const fy = new Float64Array(N)

    // Repulsion — all pairs
    for (let i = 0; i < N; i++) {
      for (let j = i + 1; j < N; j++) {
        const dx = px[i] - px[j]
        const dy = py[i] - py[j]
        const d2 = dx * dx + dy * dy
        if (d2 < 1) continue
        const d = Math.sqrt(d2)
        const f = REPULSION / d2
        fx[i] += (dx / d) * f
        fy[i] += (dy / d) * f
        fx[j] -= (dx / d) * f
        fy[j] -= (dy / d) * f
      }
    }

    // Attraction — edges (use node id → index map since cytoscape types lack .index())
    const idxMap = new Map<string, number>()
    for (let i = 0; i < N; i++) idxMap.set(nodes[i].id(), i)

    edges.forEach((e) => {
      const si = idxMap.get(e.source().id())
      const ti = idxMap.get(e.target().id())
      if (si === undefined || ti === undefined) return
      const dx = px[ti] - px[si]
      const dy = py[ti] - py[si]
      const d = Math.sqrt(dx * dx + dy * dy)
      if (d < EPSILON) return
      const f = ATTRACTION_K * (d - REST_LENGTH)
      fx[si] += (dx / d) * f
      fy[si] += (dy / d) * f
      fx[ti] -= (dx / d) * f
      fy[ti] -= (dy / d) * f
    })

    // Center gravity toward centroid
    let cx = 0, cntY = 0
    for (let i = 0; i < N; i++) { cx += px[i]; cntY += py[i] }
    cx /= N; cntY /= N
    for (let i = 0; i < N; i++) {
      fx[i] -= (px[i] - cx) * CENTER_GRAVITY
      fy[i] -= (py[i] - cntY) * CENTER_GRAVITY
    }

    // Integrate with semi-implicit Euler + apply back to cytoscape.
    // batch() coalesces the per-node position notifies into one render pass —
    // without it a 200-node graph triggers 200 style recalcs per frame.
    const pinned = pinnedRef.current
    const vel = velRef.current
    cy.batch(() => {
      for (let i = 0; i < N; i++) {
        const id = nodes[i].id()
        if (pinned.has(id)) {
          vel.set(id, [0, 0])
          continue
        }
        let [vx, vy] = vel.get(id) || [0, 0]
        vx = (vx + fx[i]) * DAMPING
        vy = (vy + fy[i]) * DAMPING
        const sp = Math.sqrt(vx * vx + vy * vy)
        if (sp > MAX_VELOCITY) { vx = (vx / sp) * MAX_VELOCITY; vy = (vy / sp) * MAX_VELOCITY }
        vel.set(id, [vx, vy])
        nodes[i].position({ x: px[i] + vx, y: py[i] + vy })
      }
    })

    rafRef.current = requestAnimationFrame(() => forceTick(cy))
  }, [])

  useEffect(() => {
    if (!containerRef.current || !graphData) return
    if (cyRef.current) cyRef.current.destroy()

    // Stop previous sim
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    if (startTimerRef.current) { window.clearTimeout(startTimerRef.current); startTimerRef.current = null }
    velRef.current.clear()
    pinnedRef.current.clear()

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      wheelSensitivity: 0, // Disabled — custom normalized handler below
      minZoom: 0.03,
      maxZoom: 5.0,
      style: buildCyStyle(readThemePalette()),
      // Initial scatter — force simulation will take over
      layout: { name: 'random' },
    })

    graphData.elements.nodes.forEach((n) => {
      const key = entityKeyOf(n.data.entity_type)
      cy.add({
        group: 'nodes',
        data: {
          ...n.data,
          entity_key: key,
          label: `${ENTITY_META[key].abbr} · ${n.data.name}`,
        },
      })
    })
    graphData.elements.edges.forEach((e) => cy.add({
      group: 'edges',
      data: { ...e.data, label: getRelationLabel(e.data.relation_type) },
    }))

    // Below 28px, shapes collapse into dots: switch to a uniform LOD.
    cy.on('zoom', () => {
      const low = cy.zoom() < 0.78
      cy.batch(() => cy.nodes().toggleClass('lod-low', low))
    })

    // Tap → select node (or toggle batch selection in select mode)
    cy.on('tap', 'node', (evt) => {
      if (selectModeRef.current) {
        setSelectedIds((prev) => {
          const next = new Set(prev)
          if (next.has(evt.target.id())) next.delete(evt.target.id())
          else next.add(evt.target.id())
          return next
        })
      }
      selectNode(evt.target.id())
    })
    cy.on('tap', (evt) => { if (evt.target === cy && !selectModeRef.current) selectNode(null) })

    // Drag → pin node so physics doesn't fight user
    cy.on('grab', 'node', (evt) => pinnedRef.current.add(evt.target.id()))
    cy.on('free', 'node', (evt) => {
      pinnedRef.current.delete(evt.target.id())
      velRef.current.set(evt.target.id(), [0, 0]) // reset velocity on release
    })

    // ─── Custom normalized wheel zoom ───
    // Cytoscape's built-in wheel handling doesn't distinguish touchpad pinch
    // from mouse wheel, causing extreme sensitivity after pinch zoom.
    // We disable it (wheelSensitivity: 0) and normalize here.
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      if (!cy || cy.destroyed()) return

      // Normalize delta to [-1, 1] regardless of device (touchpad pinch
      // fires many small events; mouse wheel fires few large events).
      const rawDelta = e.deltaY || e.deltaX
      const cap = Math.abs(rawDelta) > 50 ? 120 : 50 // mouse ~120, touchpad <50
      const normalized = Math.sign(rawDelta) * Math.min(Math.abs(rawDelta), cap) / cap

      // Gentle zoom: 8% per normalized unit
      const zoomFactor = 1 - normalized * 0.08
      const newZoom = cy.zoom() * zoomFactor
      if (newZoom < 0.03 || newZoom > 5.0) return

      cy.zoom({
        level: newZoom,
        renderedPosition: { x: e.offsetX, y: e.offsetY },
      })
    }
    containerRef.current!.addEventListener('wheel', onWheel, { passive: false })

    // Cose layout for initial placement
    cy.layout({ name: 'cose', idealEdgeLength: 120, nodeOverlap: 20, animate: true } as any).run()

    // Start force simulation once cose settles (2s delay)
    startTimerRef.current = window.setTimeout(() => {
      if (cy.destroyed()) return
      runningRef.current = true  // force simulation starts ON after load
      forceTick(cy)
    }, 1500)

    cyRef.current = cy

    return () => {
      runningRef.current = false
      if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
      if (startTimerRef.current) { window.clearTimeout(startTimerRef.current); startTimerRef.current = null }
      containerRef.current?.removeEventListener('wheel', onWheel)
      // cytoscape's renderer keeps its own rAF alive across destroy() and
      // throws "Cannot read properties of null (reading 'notify')" when a
      // frame lands mid-teardown. stop() halts that loop first.
      try {
        cy.stop()
        cy.destroy()
      } catch { /* already gone */ }
      cyRef.current = null
    }
  }, [graphData, forceTick])

  // Update edge labels when language changes
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || cy.destroyed()) return
    cy.edges().forEach((edge) => {
      const rel = edge.data('relation_type')
      if (rel) edge.data('label', getRelationLabel(rel))
    })
  }, [lang, getRelationLabel])

  const toggleSimulation = () => {
    const next = !runningRef.current
    runningRef.current = next
    setSimRunning(next)
    if (next && cyRef.current && !cyRef.current.destroyed()) {
      forceTick(cyRef.current)
    }
  }

  // ─── Batch ops on the selected set ───
  const batchDelete = async () => {
    if (!selectedBookId || selectedIds.size === 0 || batchBusy) return
    setBatchBusy(true)
    try {
      const ids = [...selectedIds]
      const r = await batchDeleteNodes(selectedBookId, ids)
      setSelectedIds(new Set())
      refreshGraph()
      setGvUndo(r.deleted || [])
      setGvMsg(t('gm.deleted').replace('{n}', String(r.deleted?.length ?? 0)))
    } catch (e) {
      setGvMsg(String(e).slice(0, 110))
    } finally {
      setBatchBusy(false)
    }
  }

  const undoBatchDelete = async () => {
    if (!gvUndo) return
    await recycleRestore(gvUndo)
    setGvUndo(null)
    setGvMsg(t('gm.undone'))
    refreshGraph()
  }

  const applyBatchTags = async () => {
    if (!selectedBookId || selectedIds.size === 0 || !tagValueDraft.trim() || batchBusy) return
    setBatchBusy(true)
    try {
      await batchAddTags(selectedBookId, [...selectedIds],
        [{ g: tagGroupSel, v: tagValueDraft.trim() }])
      setTagDialogOpen(false)
      setTagValueDraft('')
      refreshGraph()
      getTagList(selectedBookId).then(setTagGroups).catch(() => {})
      setGvMsg(t('gm.tagged')
        .replace('{n}', String(selectedIds.size))
        .replace('{g}', tagGroupSel)
        .replace('{v}', tagValueDraft.trim()))
    } catch (e) {
      setGvMsg(String(e).slice(0, 110))
    } finally {
      setBatchBusy(false)
    }
  }

  /** Batch filter → select: pull every node matching the current filters
   *  into the selection set (works with or without select mode). */
  const selectFiltered = () => {
    if (!graphData) return
    const next = new Set(selectedIds)
    for (const n of graphData.elements.nodes) {
      const d = n.data
      const typeOk = typeFilter === null || entityKeyOf(d.entity_type) === typeFilter
      let tagOk = true
      if (tagFilter) {
        const [g, v] = tagFilter.split(':')
        let tags: Array<{ g: string; v: string }> = []
        try { tags = JSON.parse(d.tags || '[]') } catch { /* ignore */ }
        tagOk = tags.some((tp) => tp.g === g && tp.v === v)
      }
      if (typeOk && tagOk) next.add(d.id)
    }
    setSelectedIds(next)
    setSelectMode(true)
  }

  const nodeCount = graphData?.elements.nodes.length || 0
  const edgeCount = graphData?.elements.edges.length || 0

  // ─── Empty states ───
  if (!selectedBookId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-sm px-6 py-12 rounded-2xl bg-surface-card/50 border border-border-subtle">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-surface-hover flex items-center justify-center text-2xl">{'\u{1F517}'}</div>
          <p className="text-text-secondary font-medium mb-1">{t('app.noGraph')}</p>
          <p className="text-sm text-text-muted">
            {t('app.noGraphHint')}
          </p>
        </div>
      </div>
    )
  }
  if (!graphData) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-sm px-6 py-12 rounded-2xl bg-surface-card/50 border border-border-subtle">
          {graphLoading ? (
            <>
              <div className="w-10 h-10 mx-auto mb-3 rounded-full border-2 border-accent-purple border-t-transparent animate-spin" />
              <p className="text-text-secondary text-sm">{t('app.loading')} <span className="text-text-primary font-medium">{selectedBook?.title}</span>...</p>
            </>
          ) : (
            <>
              <p className="text-text-secondary text-sm mb-3">{t('app.extractionFailed')}</p>
              <button
                onClick={() => setLoadSeq((n) => n + 1)}
                className="px-4 py-2 text-xs font-medium bg-surface-hover hover:bg-surface-overlay text-text-secondary rounded-lg transition-colors"
              >
                {t('app.reload')}
              </button>
            </>
          )}
        </div>
      </div>
    )
  }
  if (nodeCount === 0 && edgeCount === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-sm px-6 py-12 rounded-2xl bg-surface-card/50 border border-border-subtle">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-amber-500/10 flex items-center justify-center text-2xl">{'\u26A0\uFE0F'}</div>
          <p className="text-text-secondary font-medium mb-1">{t('app.emptyGraph')}</p>
          <p className="text-sm text-text-muted mb-4">
            {selectedBook?.status?.startsWith('error')
              ? `${t('app.extractionFailed')}：${selectedBook.status.replace('error:', '')}`
              : t('app.noMathFound')}
          </p>
          <button
            onClick={() => selectBook(selectedBookId)}
            className="px-4 py-2 text-xs font-medium bg-surface-hover hover:bg-surface-overlay text-text-secondary rounded-lg transition-colors"
          >
            {t('app.reload')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="relative w-full h-full">
      {/* Management controls — BOTTOM-LEFT: the a11y panel owns the top-left
          corner and would cover these buttons (user report). flex-col-reverse
          keeps the main bar hugging the bottom while dialogs stack upward. */}
      <div className="absolute bottom-3 left-3 z-10 max-w-[min(640px,calc(100%-24px))] flex flex-col-reverse gap-1.5 items-start">
        <div className="bg-surface-card/90 backdrop-blur-sm rounded-lg px-3 py-1.5 border border-border-subtle flex items-center gap-3 flex-wrap">
          <span className="text-xs text-text-muted">
            <span className="text-text-primary font-medium">{nodeCount}</span> nodes
          </span>
          <span className="w-px h-3 bg-border-subtle" />
          <span className="text-xs text-text-muted">
            <span className="text-text-primary font-medium">{edgeCount}</span> edges
          </span>
          <span className="w-px h-3 bg-border-subtle" />
          <button
            onClick={toggleSimulation}
            className={`px-2 py-0.5 text-xs font-medium rounded transition ${
              simRunning ? 'bg-accent-green/20 text-accent-green' : 'bg-amber-500/20 text-amber-400'
            }`}
            title={simRunning ? 'Pause force simulation' : 'Resume force simulation'}
          >
            {simRunning ? '● Live' : '▶ Paused'}
          </button>
          <span className="w-px h-3 bg-border-subtle" />
          <button
            onClick={() => setSelectMode((v) => !v)}
            className={`px-2 py-0.5 text-xs font-medium rounded transition ${
              selectMode ? 'bg-accent-purple/25 text-accent-purple' : 'bg-surface-hover text-text-muted hover:text-text-primary'
            }`}
            title={t('gm.selectModeTitle')}
          >
            {selectMode ? '☑ ' + t('gm.selectMode') : t('gm.selectMode')}
          </button>
          <select
            value={tagFilter ?? ''}
            onChange={(e) => setTagFilter(e.target.value || null)}
            className="px-1.5 py-0.5 text-xs rounded bg-surface-hover text-text-muted border border-border-subtle max-w-[150px]"
            aria-label={t('gm.tagFilter')}
          >
            <option value="">{t('gm.tagFilter')}</option>
            {Object.entries(tagGroups).flatMap(([g, vals]) =>
              vals.map((v) => <option key={`${g}:${v}`} value={`${g}:${v}`}>{g}:{v}</option>),
            )}
          </select>
          {tagFilter && (
            <button
              onClick={selectFiltered}
              className="px-2 py-0.5 text-xs font-medium rounded bg-surface-hover text-text-muted hover:text-text-primary"
              title={t('gm.selectFilteredTitle')}
            >
              {t('gm.selectFiltered')}
            </button>
          )}
          <span className="w-px h-3 bg-border-subtle" />
          <button
            onClick={() => setRecycleOpen((v) => !v)}
            className={`px-2 py-0.5 text-xs font-medium rounded transition ${
              recycleOpen ? 'bg-amber-500/20 text-amber-400' : 'bg-surface-hover text-text-muted hover:text-text-primary'
            }`}
          >
            {t('gm.recycle')}
          </button>
        </div>

        {/* Selection toolbar (select mode) */}
        {selectMode && selectedIds.size > 0 && (
          <div className="bg-surface-card/95 backdrop-blur-sm rounded-lg px-3 py-1.5 border border-accent-purple/50 flex items-center gap-2 flex-wrap">
            <span className="text-xs font-medium text-accent-purple">
              {t('gm.selected').replace('{n}', String(selectedIds.size))}
            </span>
            <button
              onClick={() => setTagDialogOpen(true)}
              className="px-2 py-0.5 text-xs font-medium rounded bg-surface-hover text-text-primary hover:bg-surface-overlay"
            >
              {t('gm.batchTag')}
            </button>
            <button
              onClick={() => void batchDelete()}
              disabled={batchBusy}
              className="px-2 py-0.5 text-xs font-medium rounded bg-red-500/15 text-red-400 hover:bg-red-500/25 disabled:opacity-50"
            >
              {batchBusy ? '…' : t('gm.batchDelete')}
            </button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="px-2 py-0.5 text-xs rounded text-text-dim hover:text-text-primary"
            >
              {t('gm.clearSelection')}
            </button>
          </div>
        )}

        {/* Tag dialog (batch labelling) */}
        {tagDialogOpen && (
          <div className="bg-surface-card/95 backdrop-blur-sm rounded-lg px-3 py-2 border border-border-subtle flex items-center gap-2 flex-wrap">
            <span className="text-xs text-text-muted">{t('gm.tagGroup')}</span>
            <select
              value={tagGroupSel}
              onChange={(e) => setTagGroupSel(e.target.value)}
              className="px-1.5 py-0.5 text-xs rounded bg-surface-hover text-text-primary border border-border-subtle"
            >
              {['学科', '章节', '自定义', ...Object.keys(tagGroups).filter((g) => !['学科', '章节', '自定义'].includes(g))]
                .map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
            {tagGroupSel === '自定义' && (
              <input
                value={tagValueDraft}
                onChange={(e) => { setTagValueDraft(e.target.value); setTagGroupSel(e.target.value.split(':')[0] || '自定义') }}
                placeholder={t('gm.customGroup')}
                className="px-1.5 py-0.5 text-xs rounded bg-surface-hover text-text-primary border border-border-subtle w-24"
              />
            )}
            <input
              value={tagValueDraft}
              onChange={(e) => setTagValueDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void applyBatchTags() }}
              placeholder={t('gm.tagValue')}
              className="px-1.5 py-0.5 text-xs rounded bg-surface-hover text-text-primary border border-border-subtle w-32"
            />
            <button
              onClick={() => void applyBatchTags()}
              disabled={batchBusy || !tagValueDraft.trim()}
              className="px-2 py-0.5 text-xs font-medium rounded bg-accent-purple/25 text-accent-purple disabled:opacity-50"
            >
              {t('gm.applyTag')}
            </button>
            <button
              onClick={() => { setTagDialogOpen(false); setTagValueDraft('') }}
              className="px-2 py-0.5 text-xs rounded text-text-dim hover:text-text-primary"
            >
              {t('gm.cancel')}
            </button>
          </div>
        )}

        {/* Action feedback + undo */}
        {(gvMsg || gvUndo) && (
          <div className="bg-surface-card/95 backdrop-blur-sm rounded-lg px-3 py-1.5 border border-border-subtle flex items-center gap-2">
            <span className="text-xs text-text-muted truncate max-w-[300px]">{gvMsg}</span>
            {gvUndo && (
              <button
                onClick={() => void undoBatchDelete()}
                className="px-2 py-0.5 text-xs font-medium rounded bg-accent-purple/25 text-accent-purple"
              >
                {t('gm.undoDelete')}
              </button>
            )}
            <button
              onClick={() => { setGvMsg(''); setGvUndo(null) }}
              className="text-text-dim hover:text-text-primary text-xs"
              aria-label={t('gm.dismiss')}
            >✕</button>
          </div>
        )}
      </div>

      {/* Hint */}
      <div className="absolute bottom-3 right-3 z-10">
        <span className="text-[10px] text-text-dim bg-surface-base/80 backdrop-blur-sm rounded px-2 py-1">
          {t('graph.dragHint')}
        </span>
      </div>

      {/* Recycle bin (bottom-right, per user preference) */}
      <RecyclePanel
        bookId={selectedBookId || ''}
        open={recycleOpen}
        onClose={() => setRecycleOpen(false)}
        onChanged={refreshGraph}
      />

      {/* Search bar */}
      <div className="absolute top-3 right-3 z-20">
        <div className="relative">
          <div className="flex items-center bg-surface-card/90 backdrop-blur-sm rounded-lg border border-border-subtle px-2.5 py-1.5 gap-1.5">
            <span className="text-xs text-text-dim">{searching ? '\u23F3' : '\u{1F50D}'}</span>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onFocus={() => searchResults.length > 0 && setSearchOpen(true)}
              placeholder={t('graph.searchPlaceholder')}
              className="bg-transparent text-xs text-text-primary w-36 outline-none placeholder:text-text-dim"
            />
            {searchQuery && (
              <button
                onClick={() => { setSearchQuery(''); setSearchOpen(false) }}
                className="text-text-dim hover:text-text-primary text-xs"
              >
                {'\u2715'}
              </button>
            )}
          </div>

          {/* Results dropdown */}
          {searchOpen && searchResults.length > 0 && (
            <div className="absolute top-full mt-1 right-0 w-64 max-h-64 overflow-y-auto bg-surface-card rounded-lg border border-border-subtle shadow-lg">
              {searchResults.map((node: any) => (
                <button
                  key={node.id}
                  onClick={() => handleSearchResultClick(node.id)}
                  className="w-full text-left px-3 py-2 hover:bg-surface-hover transition-colors border-b border-border-subtle last:border-0"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-text-primary truncate">
                      {node.name}
                    </span>
                    {node.entity_type && (
                      <span className="text-2xs px-1.5 py-0.5 rounded-full bg-surface-overlay text-text-muted shrink-0">
                        {node.entity_type}
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}

          {searchOpen && searchQuery && searchResults.length === 0 && !searching && (
            <div className="absolute top-full mt-1 right-0 w-64 bg-surface-card rounded-lg border border-border-subtle shadow-lg px-3 py-3 text-xs text-text-muted text-center">
              {t('graph.noResults')}
            </div>
          )}
        </div>
      </div>

      <GraphA11yPanel
        graphData={graphData}
        typeFilter={typeFilter}
        setTypeFilter={setTypeFilter}
        listMode={listMode}
        setListMode={setListMode}
        selectedNodeId={selectedNodeId}
        onSelect={(id) => {
          selectNode(id)
          const cy = cyRef.current
          if (cy && cy.$id(id).length) {
            cy.$(':selected').unselect()
            cy.$id(id).select()
            cy.animate({ center: { eles: cy.$id(id) } }, { duration: 150 })
          }
        }}
      />
      <div ref={containerRef} className="cytoscape-container" />
    </div>
  )
}
