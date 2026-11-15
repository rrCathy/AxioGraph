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
  label: string
  number: string | null
  title: string | null
  signal: 'font' | 'text'
  bbox: [number, number, number, number]
  text: string
  /** Layout-block indexes the environment overlaps. */
  blocks?: number[]
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
