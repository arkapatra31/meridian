import { create } from 'zustand'
import type { GraphApiResponse, GraphNode, GraphSummary } from './types'

interface GraphStore {
  graphId: string | null
  graphData: GraphApiResponse | null
  selectedNode: GraphNode | null
  searchQuery: string
  loading: boolean
  error: string | null

  graphs: GraphSummary[]
  graphsLoading: boolean
  graphsError: string | null

  syncLoading: boolean
  syncError: string | null

  loadGraph: (id: string, token: string) => Promise<void>
  listGraphs: (token: string) => Promise<void>
  syncRepo: (url: string, pat: string, branch: string | undefined, token: string) => Promise<string | null>
  deleteGraph: (id: string, token: string) => Promise<void>
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

  graphs: [],
  graphsLoading: false,
  graphsError: null,

  syncLoading: false,
  syncError: null,

  loadGraph: async (id: string, token: string) => {
    set({ loading: true, error: null, selectedNode: null, searchQuery: '' })
    try {
      const res = await fetch(`/graph?graph_id=${encodeURIComponent(id)}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
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

  listGraphs: async (token: string) => {
    set({ graphsLoading: true, graphsError: null })
    try {
      const res = await fetch('/repos', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      const data: GraphSummary[] = await res.json()
      set({ graphs: data, graphsLoading: false })
    } catch (err) {
      set({ graphsError: (err as Error).message, graphsLoading: false })
    }
  },

  syncRepo: async (url: string, pat: string, branch: string | undefined, token: string) => {
    set({ syncLoading: true, syncError: null })
    try {
      const res = await fetch('/repos/sync', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          'X-GitHub-PAT': pat,
        },
        body: JSON.stringify({ url, branch: branch || null }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      const data = await res.json()
      set({ syncLoading: false })
      return data.graph_id as string | null
    } catch (err) {
      set({ syncError: (err as Error).message, syncLoading: false })
      return null
    }
  },

  deleteGraph: async (id: string, token: string) => {
    try {
      const res = await fetch(`/repos/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      set(s => ({ graphs: s.graphs.filter(g => g.graph_id !== id) }))
    } catch (err) {
      set({ graphsError: (err as Error).message })
    }
  },

  setSelectedNode: (node) => set({ selectedNode: node }),

  setSearchQuery: (q) => set({ searchQuery: q }),

  reset: () =>
    set({
      graphId: null,
      graphData: null,
      selectedNode: null,
      searchQuery: '',
      error: null,
    }),
}))
