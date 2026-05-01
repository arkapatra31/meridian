import { useEffect, useMemo, useRef, useState, FormEvent, KeyboardEvent } from 'react'
import { usePlaygroundStore, type ChatMessage, type MessageMeta } from '@/playgroundStore'

/**
 * Floating chat panel for the C6 QnA Playground.
 *
 * Mounted at App level so the WebSocket survives navigation between the
 * dashboard and the graph view. The store owns the socket; this component
 * is just a view onto it.
 */
export default function PlaygroundChat() {
  const {
    isOpen, graphId, repoLabel, status, awaiting, error, messages,
    hide, close, newChat, send,
  } = usePlaygroundStore()

  const [draft, setDraft] = useState('')
  const [confirmingClose, setConfirmingClose] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, awaiting])

  // Auto-grow the composer textarea up to ~6 lines.
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [draft])

  if (!isOpen || !graphId) return null

  const submit = () => {
    if (awaiting || status !== 'open') return
    const trimmed = draft.trim()
    if (!trimmed) return
    send(trimmed)
    setDraft('')
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter submits; Ctrl/Cmd+Enter inserts a newline (and Shift+Enter too,
    // for users who reach for the conventional shortcut).
    if (e.key !== 'Enter') return
    if (e.ctrlKey || e.metaKey || e.shiftKey) return
    e.preventDefault()
    submit()
  }

  const requestClose = () => {
    if (messages.length === 0) {
      close()
      return
    }
    setConfirmingClose(true)
  }

  const confirmClose = () => {
    setConfirmingClose(false)
    close()
  }

  const statusLabel = (() => {
    if (error) return error
    if (status === 'connecting') return 'connecting…'
    if (status === 'closed')     return 'disconnected'
    if (status === 'error')      return 'error'
    return ''
  })()

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      {/* Backdrop — click to minimize (preserves the WS session). */}
      <button
        type="button"
        aria-label="Minimize chat"
        onClick={hide}
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
      />

      {/* Panel */}
      <div className="relative w-full max-w-[760px] h-[min(720px,calc(100vh-4rem))] flex flex-col rounded-2xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0d1117] shadow-2xl shadow-black/50">
        {/* Header */}
        <div className="flex items-center justify-between px-4 h-12 border-b border-gray-200 dark:border-white/5 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`w-1.5 h-1.5 rounded-full ${
              status === 'open'       ? 'bg-emerald-400'                  :
              status === 'connecting' ? 'bg-amber-400 animate-pulse'      :
              status === 'error'      ? 'bg-red-400'                      :
                                        'bg-gray-400'
            }`} />
            <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
              Playground
            </span>
            {repoLabel && (
              <>
                <span className="text-gray-400 dark:text-gray-700 text-xs">/</span>
                <span className="text-xs text-gray-500 truncate font-mono" title={repoLabel}>
                  {repoLabel}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={hide}
              title="Minimize"
              className="text-gray-500 hover:text-gray-900 dark:hover:text-white transition-colors p-1"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 12H5" />
              </svg>
            </button>
            <button
              onClick={requestClose}
              title="End chat"
              className="text-gray-500 hover:text-red-400 transition-colors p-1"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Sub-toolbar: status + new chat */}
        <div className="flex items-center justify-end px-4 h-9 border-b border-gray-200 dark:border-white/5 shrink-0 text-xs gap-3">
          <span className={`text-[11px] ${error ? 'text-red-400' : 'text-gray-500 dark:text-gray-600'}`}>
            {statusLabel}
          </span>
          <button
            onClick={newChat}
            disabled={status !== 'open' && status !== 'closed' && status !== 'error'}
            className="text-[11px] text-gray-500 hover:text-indigo-400 transition-colors disabled:opacity-40"
            title="Start a new chat (overwrites current history)"
          >
            New chat
          </button>
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-center">
              <div className="w-10 h-10 rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
                <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.86 9.86 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400">Ask about the graph</p>
              <p className="text-xs text-gray-400 dark:text-gray-600 max-w-[320px] leading-relaxed">
                Each answer is grounded in a subgraph slice extracted from your question.
              </p>
            </div>
          )}

          {messages.map((m) => (
            <MessageBubble key={m.id} role={m.role} text={m.text} pending={m.pending} meta={m.meta} />
          ))}

          {awaiting && messages[messages.length - 1]?.role === 'user' && (
            <div className="flex items-center gap-2 text-xs text-gray-500 px-1">
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" style={{ animationDelay: '0.15s' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" style={{ animationDelay: '0.3s' }} />
            </div>
          )}
        </div>

        {/* Composer */}
        <form onSubmit={handleSubmit} className="border-t border-gray-200 dark:border-white/5 p-3 shrink-0 flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={status === 'open' ? 'Ask about this codebase…  (Enter to send · Ctrl+Enter for newline)' : 'Connecting…'}
            disabled={status !== 'open' || awaiting}
            rows={1}
            className="flex-1 resize-none rounded-lg bg-gray-50 dark:bg-white/5 border border-gray-300 dark:border-white/10 px-3 py-2 text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 outline-none focus:border-indigo-500/50 transition-colors disabled:opacity-50 leading-relaxed"
          />
          <button
            type="submit"
            disabled={status !== 'open' || awaiting || !draft.trim()}
            className="px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors self-stretch flex items-center"
            title="Send"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </button>
        </form>
      </div>

      {confirmingClose && (
        <CloseSummary
          messages={messages}
          repoLabel={repoLabel}
          onCancel={() => setConfirmingClose(false)}
          onConfirm={confirmClose}
        />
      )}
    </div>
  )
}


function MessageBubble({ role, text, pending, meta }: {
  role: 'user' | 'assistant'
  text: string
  pending?: boolean
  meta?: MessageMeta
}) {
  const isUser = role === 'user'
  return (
    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} gap-1`}>
      <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
        isUser
          ? 'bg-indigo-600 text-white rounded-br-sm'
          : 'bg-gray-100 dark:bg-white/[0.05] text-gray-900 dark:text-gray-100 border border-gray-200 dark:border-white/5 rounded-bl-sm'
      }`}>
        {text}
        {pending && <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-current opacity-60 animate-pulse align-middle" />}
      </div>
      {!isUser && !pending && meta && (
        <div className="flex items-center gap-2.5 px-1 text-[11px] text-gray-400 dark:text-gray-600">
          <span title="Duration">{(meta.duration_ms / 1000).toFixed(1)}s</span>
          {meta.cost_usd != null && (
            <span title="Cost" className="text-indigo-400/70">${meta.cost_usd.toFixed(4)}</span>
          )}
          {meta.input_tokens != null && meta.output_tokens != null && (
            <span title="Token usage" className="font-mono">
              {meta.input_tokens}↑ {meta.output_tokens}↓
            </span>
          )}
        </div>
      )}
    </div>
  )
}


function CloseSummary({ messages, repoLabel, onCancel, onConfirm }: {
  messages: ChatMessage[]
  repoLabel: string | null
  onCancel: () => void
  onConfirm: () => void
}) {
  const totals = useMemo(() => sumTotals(messages), [messages])

  const exportTranscript = () => {
    const md = formatTranscript(messages, repoLabel, totals)
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    const slug = (repoLabel || 'meridian-chat').replace(/[^a-zA-Z0-9._-]+/g, '_')
    a.href = url
    a.download = `${slug}_${stamp}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const userTurns      = messages.filter((m) => m.role === 'user').length
  const assistantTurns = messages.filter((m) => m.role === 'assistant').length

  return (
    <div className="absolute inset-0 flex items-center justify-center p-6">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative w-full max-w-md rounded-2xl border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0d1117] shadow-2xl">
        <div className="px-5 pt-5 pb-3 border-b border-gray-200 dark:border-white/5">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">End this chat?</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Closing ends the session and discards history. Export a transcript first if you want to keep it.
          </p>
        </div>

        <div className="px-5 py-4 grid grid-cols-2 gap-3 text-xs">
          <SummaryStat label="Messages" value={`${userTurns} / ${assistantTurns}`} hint="you / assistant" />
          <SummaryStat
            label="Total cost"
            value={totals.cost > 0 ? `$${totals.cost.toFixed(4)}` : '—'}
            valueClass="text-indigo-400"
          />
          <SummaryStat
            label="Tokens"
            value={
              totals.inTokens || totals.outTokens
                ? `${totals.inTokens.toLocaleString()}↑ ${totals.outTokens.toLocaleString()}↓`
                : '—'
            }
            mono
          />
          <SummaryStat
            label="Total time"
            value={totals.durationMs > 0 ? `${(totals.durationMs / 1000).toFixed(1)}s` : '—'}
          />
        </div>

        <div className="px-5 pb-5 pt-2 flex items-center justify-between gap-2">
          <button
            onClick={exportTranscript}
            disabled={messages.length === 0}
            className="text-xs px-3 py-2 rounded-lg border border-gray-300 dark:border-white/10 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 transition-colors disabled:opacity-40"
          >
            Export transcript
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={onCancel}
              className="text-xs px-3 py-2 rounded-lg text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              className="text-xs px-3 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white transition-colors"
            >
              End chat
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}


function SummaryStat({ label, value, hint, mono, valueClass }: {
  label: string
  value: string
  hint?: string
  mono?: boolean
  valueClass?: string
}) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-white/5 bg-gray-50 dark:bg-white/[0.02] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-600">{label}</div>
      <div className={`mt-0.5 text-sm ${mono ? 'font-mono' : 'font-semibold'} text-gray-900 dark:text-white ${valueClass || ''}`}>
        {value}
      </div>
      {hint && <div className="text-[10px] text-gray-400 dark:text-gray-600 mt-0.5">{hint}</div>}
    </div>
  )
}


interface Totals {
  cost: number
  inTokens: number
  outTokens: number
  durationMs: number
}

function sumTotals(messages: ChatMessage[]): Totals {
  return messages.reduce<Totals>(
    (acc, m) => {
      const meta = m.meta
      if (!meta) return acc
      return {
        cost:       acc.cost       + (meta.cost_usd      ?? 0),
        inTokens:   acc.inTokens   + (meta.input_tokens  ?? 0),
        outTokens:  acc.outTokens  + (meta.output_tokens ?? 0),
        durationMs: acc.durationMs + (meta.duration_ms   ?? 0),
      }
    },
    { cost: 0, inTokens: 0, outTokens: 0, durationMs: 0 },
  )
}

function formatTranscript(
  messages: ChatMessage[],
  repoLabel: string | null,
  totals: Totals,
): string {
  const header = [
    `# Meridian Playground transcript`,
    repoLabel ? `**Repo:** \`${repoLabel}\`` : null,
    `**Exported:** ${new Date().toISOString()}`,
    ``,
    `- **Messages:** ${messages.length}`,
    `- **Total cost:** ${totals.cost > 0 ? `$${totals.cost.toFixed(4)}` : '—'}`,
    `- **Tokens:** ${totals.inTokens.toLocaleString()} in / ${totals.outTokens.toLocaleString()} out`,
    `- **Total time:** ${(totals.durationMs / 1000).toFixed(1)}s`,
    ``,
    `---`,
    ``,
  ].filter(Boolean).join('\n')

  const body = messages
    .map((m) => {
      const speaker = m.role === 'user' ? '**You**' : '**Assistant**'
      const meta = m.role === 'assistant' && m.meta
        ? `  \n_${(m.meta.duration_ms / 1000).toFixed(1)}s · $${(m.meta.cost_usd ?? 0).toFixed(4)} · ${m.meta.input_tokens ?? 0}↑ ${m.meta.output_tokens ?? 0}↓_`
        : ''
      return `### ${speaker}${meta}\n\n${m.text.trim()}\n`
    })
    .join('\n')

  return header + body
}
