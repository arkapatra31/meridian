import { create } from 'zustand'
import type { GraphApiResponse, GraphNode } from './types'

interface GraphStore {
  graphId: string | null
  graphData: GraphApiResponse | null
  selectedNode: GraphNode | null
  searchQuery: string
  loading: boolean
  error: string | null

  loadGraph: (id: string) => Promise<void>
  setSelectedNode: (node: GraphNode | null) => void
  setSearchQuery: (q: string) => void
  reset: () => void
}

export const useGraphStore = create<GraphStore>((set) => ({
  graphId: null,
  graphData: null,
  selectedNode: null,
  searchQuery: '',
  loading: false,
  error: null,

  loadGraph: async (id: string) => {
    set({ loading: true, error: null, selectedNode: null, searchQuery: '' })
    try {
      const res = await fetch(`/graph?graph_id=${encodeURIComponent(id)}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      const data: GraphApiResponse = await res.json()
      set({ graphData: data, graphId: id, loading: false })
    } catch (err) {
      set({ error: (err as Error).message, loading: false })
    }
  },

  setSelectedNode: (node) => set({ selectedNode: node }),

  setSearchQuery: (q) => set({ searchQuery: q }),

  reset: () =>
    set({ graphId: null, graphData: null, selectedNode: null, searchQuery: '', error: null }),
}))
