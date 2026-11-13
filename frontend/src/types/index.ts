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
}

export interface PageLayout {
  page_no: number
  page_kind: 'text_layer' | 'scanned_ocr' | 'scanned_image' | 'low_quality_text' | 'mixed_ocr'
  text_source?: string
  needs_vision: boolean
  text_quality: number
  figure_boxes: number[][]
  figure_labels: string[]
  formula_numbers: string[]
  blocks: LayoutBlock[]
  counts: Record<string, number>
  layout_text?: string
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
  toc: TocItem[]
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
