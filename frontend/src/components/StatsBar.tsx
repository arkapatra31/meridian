import { useGraphStore } from '@/store'

const STATUS_STYLES = {
  READY:    'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  BUILDING: 'bg-amber-500/15  text-amber-400  border-amber-500/20',
  ERROR:    'bg-red-500/15    text-red-400    border-red-500/20',
}

export default function StatsBar() {
  const { graphData, reset } = useGraphStore()
  if (!graphData) return null

  const { repo_url, branch, status, node_count, edge_count, community_count } = graphData
  const repoShort = repo_url.replace(/^https?:\/\/github\.com\//, '')

  return (
    <div className="absolute top-0 left-0 right-0 z-20 h-12 flex items-center gap-4 px-4 border-b border-white/5 bg-[#0d1117]/90 backdrop-blur-sm">
      {/* Logo */}
      <span className="text-sm font-bold text-white tracking-tight shrink-0">Meridian</span>

      <div className="w-px h-4 bg-white/10" />

      {/* Repo + branch */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-sm text-gray-300 truncate font-mono">{repoShort}</span>
        <span className="shrink-0 px-1.5 py-0.5 rounded text-xs font-mono bg-white/5 border border-white/10 text-gray-400">
          {branch}
        </span>
      </div>

      {/* Status */}
      <span className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-medium border ${STATUS_STYLES[status]}`}>
        {status}
      </span>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Counts */}
      <div className="flex items-center gap-4 text-xs text-gray-400">
        <Stat label="Nodes" value={node_count} color="text-indigo-400" />
        <Stat label="Edges" value={edge_count} color="text-purple-400" />
        <Stat label="Communities" value={community_count} color="text-cyan-400" />
      </div>

      <div className="w-px h-4 bg-white/10" />

      <button
        onClick={reset}
        className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        title="Load a different graph"
      >
        ← Back
      </button>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-baseline gap-1">
      <span className={`font-semibold tabular-nums ${color}`}>{value.toLocaleString()}</span>
      <span>{label}</span>
    </div>
  )
}
