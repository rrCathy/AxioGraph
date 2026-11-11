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
