import { create } from 'zustand'

export type ChatRole = 'user' | 'assistant'

export interface MessageMeta {
  duration_ms: number
  cost_usd?: number
  input_tokens?: number
  output_tokens?: number
}

export interface ChatMessage {
  id: string
  role: ChatRole
  text: string
  /** Streaming flag — true while assistant deltas are arriving. */
  pending?: boolean
  meta?: MessageMeta
}

type WsStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

interface PlaygroundState {
  /** Whether the chat panel is visible. The WS may still be open while hidden. */
  isOpen: boolean
  /** The graph the WS is bound to. Switching graphs forces a reconnect. */
  graphId: string | null
  repoLabel: string | null
  status: WsStatus
  /** True between sending a question and receiving the closing `done` frame. */
  awaiting: boolean
  error: string | null
  messages: ChatMessage[]

  open: (args: { graphId: string; repoLabel: string; token: string }) => void
  close: () => void
  hide: () => void
  show: () => void
  send: (text: string) => void
  newChat: () => void
}

let socket: WebSocket | null = null
let lastConnectArgs: { graphId: string; token: string } | null = null

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

function buildWsUrl(graphId: string, token: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const params = new URLSearchParams({ token })
  return `${proto}//${window.location.host}/playground/${encodeURIComponent(graphId)}?${params}`
}

export const usePlaygroundStore = create<PlaygroundState>((set, get) => {
  function teardown() {
    if (socket) {
      try { socket.close() } catch { /* noop */ }
    }
    socket = null
  }

  function connect(graphId: string, token: string) {
    teardown()
    set({
      status: 'connecting',
      error: null,
      awaiting: false,
    })
    lastConnectArgs = { graphId, token }

    const ws = new WebSocket(buildWsUrl(graphId, token))
    socket = ws

    ws.onmessage = (ev) => {
      let msg: any
      try { msg = JSON.parse(ev.data) } catch { return }

      if (msg.type === 'ready') {
        set({ status: 'open' })
        return
      }
      if (msg.type === 'delta') {
        const { messages } = get()
        const last = messages[messages.length - 1]
        if (last && last.role === 'assistant' && last.pending) {
          set({
            messages: [
              ...messages.slice(0, -1),
              { ...last, text: last.text + (msg.text ?? '') },
            ],
          })
        } else {
          set({
            messages: [
              ...messages,
              { id: uid(), role: 'assistant', text: msg.text ?? '', pending: true },
            ],
          })
        }
        return
      }
      if (msg.type === 'done') {
        const { messages } = get()
        const last = messages[messages.length - 1]
        const meta: MessageMeta | undefined =
          msg.duration_ms != null
            ? {
                duration_ms:   msg.duration_ms,
                cost_usd:      msg.cost_usd,
                input_tokens:  msg.input_tokens,
                output_tokens: msg.output_tokens,
              }
            : undefined
        if (last && last.role === 'assistant' && last.pending) {
          set({
            messages: [...messages.slice(0, -1), { ...last, pending: false, meta }],
            awaiting: false,
          })
        } else {
          set({ awaiting: false })
        }
        return
      }
      if (msg.type === 'error') {
        set({ error: msg.message ?? 'unknown error', awaiting: false })
        return
      }
    }

    ws.onerror = () => {
      set({ status: 'error', error: 'WebSocket error', awaiting: false })
    }

    ws.onclose = (ev) => {
      set({
        status: 'closed',
        awaiting: false,
        error: ev.code >= 4000 ? (ev.reason || `closed (${ev.code})`) : get().error,
      })
      if (socket === ws) socket = null
    }
  }

  return {
    isOpen: false,
    graphId: null,
    repoLabel: null,
    status: 'idle',
    awaiting: false,
    error: null,
    messages: [],

    open: ({ graphId, repoLabel, token }) => {
      const cur = get()
      if (
        cur.graphId === graphId &&
        socket &&
        socket.readyState <= WebSocket.OPEN
      ) {
        set({ isOpen: true, repoLabel })
        return
      }
      set({
        isOpen: true,
        graphId,
        repoLabel,
        messages: [],
        error: null,
      })
      connect(graphId, token)
    },

    hide: () => set({ isOpen: false }),
    show: () => set({ isOpen: true }),

    close: () => {
      teardown()
      lastConnectArgs = null
      set({
        isOpen: false,
        graphId: null,
        repoLabel: null,
        status: 'idle',
        messages: [],
        awaiting: false,
        error: null,
      })
    },

    newChat: () => {
      if (!lastConnectArgs) return
      const { graphId, token } = lastConnectArgs
      set({ messages: [], error: null })
      connect(graphId, token)
    },

    send: (text) => {
      const trimmed = text.trim()
      if (!trimmed) return
      const ws = socket
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        set({ error: 'Not connected — try reconnecting.' })
        return
      }
      const userMsg: ChatMessage = { id: uid(), role: 'user', text: trimmed }
      set((s) => ({ messages: [...s.messages, userMsg], awaiting: true, error: null }))
      ws.send(JSON.stringify({ query: trimmed }))
    },
  }
})
