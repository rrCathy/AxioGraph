import { useEffect, useRef, useState, useCallback } from 'react'
import cytoscape, { Core } from 'cytoscape'
import { useAppStore } from '../stores/appStore'
import { searchNodes } from '../services/api'
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
  const pinnedRef = useRef<Set<string>>(new Set())
  const velRef = useRef<Map<string, [number, number]>>(new Map())
  const runningRef = useRef(true)

  const [simRunning, setSimRunning] = useState(true)
  const { graphData, selectedBookId, books, selectNode, selectBook, lang } = useAppStore()
  const selectedBook = books.find((b) => b.id === selectedBookId)
  const { t } = useI18n()

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

    // Integrate with semi-implicit Euler + apply back to cytoscape
    const pinned = pinnedRef.current
    const vel = velRef.current
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

    rafRef.current = requestAnimationFrame(() => forceTick(cy))
  }, [])

  useEffect(() => {
    if (!containerRef.current || !graphData) return
    if (cyRef.current) cyRef.current.destroy()

    // Stop previous sim
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    velRef.current.clear()
    pinnedRef.current.clear()

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      wheelSensitivity: 0, // Disabled — custom normalized handler below
      minZoom: 0.03,
      maxZoom: 5.0,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': 'data(color)',
            'label': 'data(name)',
            'color': '#e4e4e7',
            'font-size': '10px',
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-margin-y': 4,
            'width': 36,
            'height': 36,
            'border-width': 2,
            'border-color': 'data(color)',
            'border-opacity': 0.5,
            'text-wrap': 'wrap',
            'text-max-width': '110px',
            'font-family': '"Noto Sans SC", "Microsoft YaHei", "SimHei", "PingFang SC", Inter, sans-serif',
          },
        },
        { selector: 'node[entity_type="THEOREM"]', style: { 'shape': 'round-rectangle', 'width': 44, 'height': 36 } },
        { selector: 'node[entity_type="DEFINITION"]', style: { 'shape': 'round-rectangle' } },
        { selector: 'node[entity_type="AXIOM"]', style: { 'shape': 'diamond' } },
        { selector: 'node[entity_type="EXAMPLE"]', style: { 'shape': 'ellipse', 'width': 42, 'height': 36 } },
        {
          selector: 'node[entity_type="LEMMA"]',
          style: { 'shape': 'round-rectangle', 'width': 40, 'height': 36, 'border-style': 'dashed' },
        },
        {
          selector: 'edge',
          style: {
            'width': 1.75, 'line-color': '#52525b', 'target-arrow-color': '#52525b',
            'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
            'label': 'data(label)', 'font-size': '9px',             'color': '#c4b5fd', 'text-rotation': 'autorotate',
            'text-background-color': '#0b0e14', 'text-background-opacity': 0.7, 'text-background-padding': '2px',
          },
        },
        { selector: 'edge[relation_type="DEPENDS_ON"]', style: { 'line-color': '#60a5fa', 'target-arrow-color': '#60a5fa' } },
        {
          selector: 'edge[relation_type="GENERALIZES"]',
          style: { 'line-color': '#a78bfa', 'target-arrow-color': '#a78bfa', 'line-style': 'dashed' },
        },
        {
          selector: 'edge[relation_type="PROVES"]',
          style: { 'line-color': '#34d399', 'target-arrow-color': '#34d399', 'line-style': 'dotted', 'width': 2 },
        },
        {
          selector: 'edge[relation_type="BUILDS_ON"]',
          style: { 'line-color': '#fbbf24', 'target-arrow-color': '#fbbf24', 'line-style': 'dashed' },
        },
        {
          selector: 'edge[relation_type="EXAMPLE_OF"]',
          style: { 'line-color': '#fb923c', 'target-arrow-color': '#fb923c', 'line-style': 'dotted' },
        },
        {
          selector: ':selected',
          style: {
            'border-color': '#818cf8', 'border-width': 3, 'border-opacity': 1,
            'shadow-blur': 12, 'shadow-color': '#818cf8', 'shadow-opacity': 0.4,
          } as any,
        },
      ],
      // Initial scatter — force simulation will take over
      layout: { name: 'random' },
    })

    graphData.elements.nodes.forEach((n) => cy.add({ group: 'nodes', data: n.data }))
    graphData.elements.edges.forEach((e) => cy.add({
      group: 'edges',
      data: { ...e.data, label: getRelationLabel(e.data.relation_type) },
    }))

    // Tap → select node
    cy.on('tap', 'node', (evt) => selectNode(evt.target.id()))
    cy.on('tap', (evt) => { if (evt.target === cy) selectNode(null) })

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
    setTimeout(() => {
      if (cy.destroyed()) return
      runningRef.current = true  // force simulation starts ON after load
      forceTick(cy)
    }, 1500)

    cyRef.current = cy

    return () => {
      runningRef.current = false
      if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
      containerRef.current?.removeEventListener('wheel', onWheel)
      cy.destroy()
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
          <div className="w-10 h-10 mx-auto mb-3 rounded-full border-2 border-accent-purple border-t-transparent animate-spin" />
          <p className="text-text-secondary text-sm">{t('app.loading')} <span className="text-text-primary font-medium">{selectedBook?.title}</span>...</p>
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
      {/* Stats + Sim Toggle */}
      <div className="absolute top-3 left-3 z-10 bg-surface-card/90 backdrop-blur-sm rounded-lg px-3 py-1.5 border border-border-subtle flex items-center gap-3">
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
      </div>

      {/* Hint */}
      <div className="absolute bottom-3 right-3 z-10">
        <span className="text-[10px] text-text-dim bg-surface-base/80 backdrop-blur-sm rounded px-2 py-1">
          {t('graph.dragHint')}
        </span>
      </div>

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

      <div ref={containerRef} className="cytoscape-container" />
    </div>
  )
}
