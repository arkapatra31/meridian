import { usePlaygroundStore } from '@/playgroundStore'

/**
 * Floating "open chat" pill — visible only when a playground session exists
 * but the panel is minimized (so the user can return to an in-flight chat
 * after navigating away from the dashboard).
 */
export default function PlaygroundLauncher() {
  const { graphId, isOpen, repoLabel, status, awaiting, show } = usePlaygroundStore()

  if (!graphId || isOpen) return null

  return (
    <button
      onClick={show}
      className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-4 py-2.5 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30 transition-colors"
    >
      <span className="relative flex w-2 h-2">
        <span className={`absolute inset-0 rounded-full ${
          status === 'open' ? 'bg-emerald-300' :
          status === 'error' ? 'bg-red-300' : 'bg-amber-300 animate-pulse'
        }`} />
      </span>
      <span className="text-xs font-semibold">
        {awaiting ? 'Replying…' : 'Resume chat'}
      </span>
      {repoLabel && (
        <span className="text-[11px] opacity-80 font-mono truncate max-w-[140px]">
          {repoLabel}
        </span>
      )}
    </button>
  )
}
