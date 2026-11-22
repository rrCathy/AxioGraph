export interface Book {
  id: string
  title: string
  filename: string
  language: string
  status: string
  progress: number
  node_count: number
  edge_count: number
  chunk_total: number
  chunk_done: number
  created_at: string
}

export interface GraphData {
  elements: {
    nodes: GraphNode[]
    edges: GraphEdge[]
  }
}

export interface GraphNode {
  data: {
    id: string
    label: string
    entity_type: string
    name: string
    content: string
    chapter: string
    color: string
    review_status?: string
    tags?: string
  }
}

export interface GraphEdge {
  data: {
    id: string
    source: string
    target: string
    label: string
    relation_type: string
    description: string
    review_status?: string
  }
}

export interface NodeDetail {
  id: string
  book_id: string
  entity_type: string
  name: string
  content: string
  chapter: string
  metadata: string
  created_at: string
}

export interface PageInfo {
  page_no: number
  char_count: number
  quality: number
  status: string
  ocr_confidence: number | null
  edited: number
}

export interface TextBlock {
  x0: number
  y0: number
  x1: number
  y1: number
  text: string
}

export interface LayoutBlock {
  type: 'H' | 'TABLE' | 'P' | 'FORMULA' | 'FIGURE' | 'NOISE'
  text: string
  level?: number
  origin?: string
  bbox?: [number, number, number, number]
  font_size?: number
  /** LaTeX recognized from the formula image (local ONNX engine). */
  latex?: string | null
  latex_source?: string
  /** Heading text this block lives under (reading-order nearest heading). */
  section?: string
  /** Prose block whose text-layer rows use TeX math fonts. */
  has_math?: boolean
}

export interface FormulaItem {
  no: string
  block: number
  bbox: number[] | null
  where: 'formula' | 'prose'
}

export interface FormulaRef {
  ref: string
  block: number
  context: string
}

export interface PageLayout {
  version?: number
  page_no: number
  page_kind: 'text_layer' | 'scanned_ocr' | 'scanned_image' | 'low_quality_text' | 'mixed_ocr'
  text_source?: string
  needs_vision: boolean
  text_quality: number
  figure_boxes: number[][]
  figure_labels: string[]
  formula_numbers: string[]
  formula_items?: FormulaItem[]
  formula_refs?: FormulaRef[]
  formula_recognized?: number
  formula_total?: number
  math_lines?: number
  blocks: LayoutBlock[]
  counts: Record<string, number>
  layout_text?: string
}

/** Rule-based theorem-like environment detected on the page (no LLM). */
export interface Environment {
  kind: 'theorem' | 'definition' | 'lemma' | 'proposition' | 'corollary'
    | 'example' | 'remark' | 'proof' | 'convention' | 'notation'
    | 'problem' | 'warning' | 'exercise'
    | 'axiom' | 'conjecture' | 'claim' | 'fact' | 'assumption' | 'principle'
  label: string
  number: string | null
  title: string | null
  signal: 'font' | 'text'
  bbox: [number, number, number, number]
  text: string
  /** Layout-block indexes the environment overlaps. */
  blocks?: number[]
  /** True when this piece is the continuation of an environment that
   * started on the previous page (cross-page bodies). */
  continuation?: boolean
}

export interface PageDetail {
  book_id: string
  page_no: number
  text: string
  text_raw: string | null
  text_corrected: string | null
  blocks: TextBlock[]
  char_count: number
  quality: number
  status: string
  ocr_confidence: number | null
  page_width?: number
  page_height?: number
  layout?: PageLayout | null
  layout_text?: string
  page_kind?: string
  needs_vision?: boolean
  environments?: Environment[]
}

export interface Relation {
  target: string
  type: string
  note: string
}

export interface Candidate {
  id: string
  book_id: string
  page_start: number
  page_end: number
  entity_type: string
  name: string
  content: string
  quote: string
  relations: Relation[]
  status: string
  merged_into: string | null
  created_at: string
}

export interface ConfirmedNode {
  id: string
  name: string
  entity_type: string
  page_start: number
  page_end: number
}

/* ── Book structure / vision OCR / auto mode ─────────────────────────── */

export interface TocItem {
  level: number
  /** Entry number like "1" / "1.1" when the TOC carries one (local parser). */
  no?: string | null
  title: string
  book_page: number | null
  pdf_page: number | null
}

export interface BookStructure {
  title: string | null
  author: string | null
  publisher: string | null
  offset: number | null
  offset_confidence?: number
  source: string | null
  /** Top-level outline only — the structure editor + chapter nodes. */
  toc: TocItem[]
  /** Every parsed level — the TOC navigation tree. */
  toc_full?: TocItem[]
  confirmed?: boolean
  updated_at?: string
}

export interface AutoFailWindow {
  start: number
  end: number
  error?: string
}

/* ── Promote / relations / selection Q&A ───────────────────────────────── */

export interface RelationInput {
  target_id: string
  relation_type: string
  description: string
}

export interface PromoteResult {
  ok: boolean
  action: 'created' | 'merged'
  node_id: string
  edges_added: number
  undo_token: string
}

export interface RelationTarget {
  id: string
  name: string
  entity_type: string
  page_start: number | null
  page_end: number | null
}

export interface SuggestedRelation {
  target_id: string
  target_name: string
  relation_type: string
  note: string
}

export interface QaRecord {
  id: string
  question: string
  selection: string | null
  answer: string | null
  section_title: string | null
  context_pages: string | null
  created_at: string
}

export interface AskSectionResult {
  id: string
  answer: string
  section: {
    title: string
    source: 'toc' | 'layout' | 'neighbours'
    start: number
    end: number
    chars: number
    pages_used: number[]
  }
}

/* ── AI auto-flow review ─────────────────────────────────────────────── */

export interface AiReviewNode {
  id: string
  entity_type: string
  name: string
  content: string
  source_quote: string | null
  page_start: number | null
  page_end: number | null
  ai_attempts: number
}

export interface AiReviewEdge {
  id: number
  source_id: string
  target_id: string
  relation_type: string
  description: string | null
  ai_attempts: number
  source_name: string
  target_name: string
}

export interface AiReviewQueue {
  nodes: AiReviewNode[]
  edges: AiReviewEdge[]
}

export interface AiReadResult {
  items: number
  edges?: number
  page?: number
  reason?: string
}

/* ── Graph management: tags + recycle bin ────────────────────────────── */

export interface TagPair {
  g: string
  v: string
}

export interface RecycleNode {
  id: string
  entity_type: string
  name: string
  page_start: number | null
  page_end: number | null
  review_status: string
  created_by: string
  deleted_at: string | null
}

export interface RecycleBin {
  nodes: RecycleNode[]
  edges: {
    id: number
    relation_type: string
    description: string | null
    deleted_at: string | null
    source_name: string
    target_name: string
  }[]
}

export interface AutoStatus {
  task_id: string
  book_id: string
  status: 'running' | 'done' | 'cancelled' | 'error'
  range: [number, number]
  window_size: number
  window_total: number
  window_done: number
  current_window: [number, number] | null
  failed_windows: AutoFailWindow[]
  next_window: number | null
  error?: string
}
