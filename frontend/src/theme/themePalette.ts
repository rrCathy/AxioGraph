import type { EntityKey } from './entityMeta'

export interface CyPalette {
  entity: Record<EntityKey, { color: string; bg: string }>
  line: string
  arrow: string
  cinnabar: string
  ink1: string
  ink3: string
  bg0: string
}

const FALLBACK: CyPalette = {
  entity: {
    def: { color: '#7C9EE8', bg: '#202734' },
    the: { color: '#B98BE0', bg: '#282533' },
    lem: { color: '#5FC4C0', bg: '#1D2C2F' },
    ex: { color: '#9CC46A', bg: '#242C24' },
    pro: { color: '#E08BA8', bg: '#2C252C' },
    cor: { color: '#D9AC63', bg: '#2C2924' },
    other: { color: '#8C8A82', bg: '#1B1F24' },
  },
  line: '#5E6875', arrow: '#8C8A82', cinnabar: '#E0664C',
  ink1: '#E8E4DB', ink3: '#8C8A82', bg0: '#090B0D',
}

function readVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim()
  return value || fallback
}

/** Cytoscape is a canvas: it cannot resolve CSS var() strings.
 *  Read concrete values once per theme, never inside zoom/rAF loops. */
export function readThemePalette(): CyPalette {
  const keys: EntityKey[] = ['def', 'the', 'lem', 'ex', 'pro', 'cor', 'other']
  const entity = {} as CyPalette['entity']
  for (const k of keys) {
    entity[k] = {
      color: readVar(`--ag-entity-${k}`, FALLBACK.entity[k].color),
      bg: readVar(`--ag-entity-${k}-bg`, FALLBACK.entity[k].bg),
    }
  }
  return {
    entity,
    line: readVar('--ag-line-3', FALLBACK.line),
    arrow: readVar('--ag-ink-3', FALLBACK.arrow),
    cinnabar: readVar('--ag-cinnabar', FALLBACK.cinnabar),
    ink1: readVar('--ag-ink-1', FALLBACK.ink1),
    ink3: readVar('--ag-ink-3', FALLBACK.ink3),
    bg0: readVar('--ag-bg-0', FALLBACK.bg0),
  }
}

/** Stylesheet built from concrete colours, safe for canvas rendering. */
export function buildCyStyle(p: CyPalette): any[] {
  const nodeBase: Record<string, unknown> = {
    'background-color': p.entity.other.bg,
    'border-color': p.entity.other.color,
    'border-width': 1.5,
    'border-opacity': 1,
    'label': 'data(label)',
    'color': p.ink1,
    'font-size': 12,
    'text-valign': 'bottom',
    'text-halign': 'center',
    'text-margin-y': 4,
    'width': 40,
    'height': 40,
    'text-wrap': 'wrap',
    'text-max-width': '120px',
    'font-family': 'AG UI, Inter, PingFang SC, Microsoft YaHei, sans-serif',
  }

  const typeStyles = (['def', 'the', 'lem', 'ex', 'pro', 'cor'] as EntityKey[]).map((k) => ({
    selector: `node[entity_key="${k}"]`,
    style: {
      'background-color': p.entity[k].bg,
      'border-color': p.entity[k].color,
      shape: k === 'def' || k === 'ex' ? 'ellipse'
        : k === 'lem' ? 'diamond'
        : k === 'pro' ? 'hexagon' : 'round-rectangle',
      width: k === 'the' ? 46 : 40,
      height: k === 'the' ? 40 : 40,
      'border-style': k === 'cor' ? 'dashed' : 'solid',
    },
  }))

  return [
    { selector: 'node', style: nodeBase },
    ...typeStyles,
    {
      selector: 'edge',
      style: {
        width: 1,
        'line-color': p.line,
        'target-arrow-color': p.arrow,
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        label: 'data(label)',
        'font-size': 11,
        color: p.ink3,
        'text-rotation': 'autorotate',
        'text-background-color': p.bg0,
        'text-background-opacity': 1,
        'text-background-padding': '2px',
      },
    },
    { selector: 'edge[relation_type="GENERALIZES"]', style: { 'line-style': 'dashed' } },
    { selector: 'edge[relation_type="PROVES"]', style: { 'line-style': 'dotted', width: 2 } },
    { selector: 'edge[relation_type="BUILDS_ON"]', style: { 'line-style': 'dashed' } },
    { selector: 'edge[relation_type="EXAMPLE_OF"]', style: { 'line-style': 'dotted' } },
    // AI auto-flow items awaiting review: amber dashed outline so the
    // "AI 部分图" is instantly separable from human-confirmed knowledge.
    {
      selector: 'node[review_status="ai_pending"]',
      style: { 'border-style': 'dashed', 'border-color': p.cinnabar, 'border-width': 2 },
    },
    {
      selector: 'edge[review_status="ai_pending"]',
      style: { 'line-style': 'dashed', 'line-color': p.cinnabar, 'target-arrow-color': p.cinnabar },
    },
    { selector: ':selected', style: { 'border-color': p.cinnabar, 'border-width': 3 } },
    { selector: 'edge:selected', style: { 'line-color': p.cinnabar, 'target-arrow-color': p.cinnabar, width: 2 } },
    { selector: 'node.dimmed', style: { opacity: 0.28 } },
    { selector: 'edge.dimmed', style: { opacity: 0.28 } },
    { selector: 'node.lod-low', style: { shape: 'ellipse', label: '' } },
    // batch-selection highlight (gold ring)
    {
      selector: 'node.ag-selected',
      style: {
        'border-color': '#E6B800',
        'border-width': 3.5,
        'background-color': '#F5E6A8',
      },
    },
  ]
}
