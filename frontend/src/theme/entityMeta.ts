export type EntityKey = 'def' | 'the' | 'lem' | 'ex' | 'pro' | 'cor' | 'other'

export interface EntityMeta {
  key: EntityKey
  abbr: string
  label: string
  colorVar: string
  bgVar: string
  colorClass: string
  bgClass: string
  shape: 'ellipse' | 'round-rectangle' | 'diamond' | 'hexagon'
}

export const ENTITY_META: Record<EntityKey, EntityMeta> = {
  def: { key: 'def', abbr: 'DEF', label: '定义', colorVar: '--ag-entity-def', bgVar: '--ag-entity-def-bg', colorClass: 'text-ag-entityDef', bgClass: 'bg-ag-entityDefBg', shape: 'ellipse' },
  the: { key: 'the', abbr: 'THE', label: '定理', colorVar: '--ag-entity-the', bgVar: '--ag-entity-the-bg', colorClass: 'text-ag-entityThe', bgClass: 'bg-ag-entityTheBg', shape: 'round-rectangle' },
  lem: { key: 'lem', abbr: 'LEM', label: '引理', colorVar: '--ag-entity-lem', bgVar: '--ag-entity-lem-bg', colorClass: 'text-ag-entityLem', bgClass: 'bg-ag-entityLemBg', shape: 'diamond' },
  ex: { key: 'ex', abbr: 'EX', label: '例证', colorVar: '--ag-entity-ex', bgVar: '--ag-entity-ex-bg', colorClass: 'text-ag-entityEx', bgClass: 'bg-ag-entityExBg', shape: 'ellipse' },
  pro: { key: 'pro', abbr: 'PRO', label: '命题', colorVar: '--ag-entity-pro', bgVar: '--ag-entity-pro-bg', colorClass: 'text-ag-entityPro', bgClass: 'bg-ag-entityProBg', shape: 'hexagon' },
  cor: { key: 'cor', abbr: 'COR', label: '推论', colorVar: '--ag-entity-cor', bgVar: '--ag-entity-cor-bg', colorClass: 'text-ag-entityCor', bgClass: 'bg-ag-entityCorBg', shape: 'round-rectangle' },
  other: { key: 'other', abbr: 'OTH', label: '其他', colorVar: '--ag-ink-3', bgVar: '--ag-bg-3', colorClass: 'text-ag-ink3', bgClass: 'bg-ag-bg3', shape: 'ellipse' },
}

/** Backend actually returns 9+ entity types; fold the extras into the 6 semantic families. */
const TYPE_MAP: Record<string, EntityKey> = {
  DEFINITION: 'def', THEOREM: 'the', LEMMA: 'lem', EXAMPLE: 'ex',
  PROPOSITION: 'pro', COROLLARY: 'cor',
  AXIOM: 'def', PROOF: 'lem', CONCEPT: 'other',
  CHAPTER: 'other', FORMULA: 'other',
}

export function entityKeyOf(type: string): EntityKey {
  return TYPE_MAP[(type || '').toUpperCase()] ?? 'other'
}

export function entityMetaOf(type: string): EntityMeta {
  return ENTITY_META[entityKeyOf(type)]
}

export interface StatusMeta {
  label: string
  icon: string
  colorVar: string
  colorClass: string
}

export const STATUS_META: Record<string, StatusMeta> = {
  pending:   { label: '待处理', icon: '○',  colorVar: '--ag-status-pending',   colorClass: 'text-ag-statusPending' },
  extracted: { label: '已提取', icon: '▸',  colorVar: '--ag-status-extracted', colorClass: 'text-ag-statusExtracted' },
  ocr:       { label: '待复核', icon: '⚑',  colorVar: '--ag-status-ocr',       colorClass: 'text-ag-statusOcr' },
  reviewed:  { label: '已校对', icon: '✓',  colorVar: '--ag-status-reviewed',  colorClass: 'text-ag-statusReviewed' },
  confirmed: { label: '已确认', icon: '✓✓', colorVar: '--ag-status-confirmed', colorClass: 'text-ag-statusConfirmed' },
  bad_page:  { label: '坏页',   icon: '⊘',  colorVar: '--ag-status-bad',       colorClass: 'text-ag-statusBad' },
  rejected:  { label: '已驳回', icon: '✕',  colorVar: '--ag-status-bad',       colorClass: 'text-ag-statusBad' },
  merged:    { label: '已合并', icon: '⤳',  colorVar: '--ag-status-merged',    colorClass: 'text-ag-statusMerged' },
  ready:     { label: '待逐页分析', icon: '○', colorVar: '--ag-status-extracted', colorClass: 'text-ag-statusExtracted' },
  importing: { label: '导入中', icon: '▸', colorVar: '--ag-status-extracted', colorClass: 'text-ag-statusExtracted' },
  done:      { label: '完成', icon: '✓✓', colorVar: '--ag-status-confirmed', colorClass: 'text-ag-statusConfirmed' },
}

export function statusMetaOf(status: string): StatusMeta {
  return STATUS_META[status] ?? STATUS_META.pending
}
