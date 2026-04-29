export interface GraphNode {
  id: string
  type: 'module' | 'class' | 'function' | 'method' | 'external'
  name: string
  file: string
  line_start: number
  line_end: number
  language: string
  params?: string[]
  docstring?: string
  community: number
  is_god: boolean
  is_orphan: boolean
}

export interface GraphEdge {
  source: string
  target: string
  type: 'IMPORTS' | 'CALLS' | 'CONTAINS' | 'INHERITS' | 'DECORATES' | 'RELATES_TO' | 'DEPENDS_ON'
  confidence: 'EXTRACTED' | 'INFERRED'
  weight: number
  metadata: Record<string, unknown>
}

export interface GraphSummary {
  graph_id: string
  repo_url: string
  branch: string
  status: 'BUILDING' | 'READY' | 'ERROR'
  node_count: number
  edge_count: number
  community_count: number
  created_at: string
  updated_at: string
  last_synced_at: string | null
}

export interface GraphApiResponse {
  graph_id: string
  repo_url: string
  branch: string
  status: 'BUILDING' | 'READY' | 'ERROR'
  last_commit_sha: string | null
  node_count: number
  edge_count: number
  community_count: number
  error_message: string | null
  nodes: GraphNode[]
  edges: GraphEdge[]
  created_at: string
  updated_at: string
  last_synced_at: string | null
}

/* Shape ForceGraph3D expects */
export interface FGNode extends GraphNode {
  // three.js will add x, y, z at runtime
  x?: number
  y?: number
  z?: number
}

export interface FGLink {
  source: string | FGNode
  target: string | FGNode
  type: GraphEdge['type']
  confidence: GraphEdge['confidence']
  weight: number
}
