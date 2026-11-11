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
