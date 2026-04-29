import { useAuthStore } from '@/authStore'
import { useGraphStore } from '@/store'

const STATUS_STYLES = {
  READY:    'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  BUILDING: 'bg-amber-500/15  text-amber-400  border-amber-500/20',
  ERROR:    'bg-red-500/15    text-red-400    border-red-500/20',
}

export default function StatsBar() {
  const { graphData, reset } = useGraphStore()
  const { user, logout } = useAuthStore()
  if (!graphData) return null

  const { repo_url, branch, status, node_count, edge_count, community_count } = graphData
  const repoShort = repo_url.replace(/^https?:\/\/github\.com\//, '')
  const repoName  = repoShort.split('/').pop() ?? repoShort

  return (
    <div className="absolute top-0 left-0 right-0 z-20 h-14 flex items-center gap-3 px-4 border-b border-white/5 bg-[#0d1117]/90 backdrop-blur-sm">

      {/* ← Back to Dashboard */}
      <button
        onClick={reset}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-gray-400 hover:text-white hover:bg-white/5 border border-transparent hover:border-white/10 transition-all shrink-0"
        title="Back to dashboard"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Dashboard
      </button>

      <div className="w-px h-5 bg-white/10" />

      {/* Breadcrumb: repo / branch */}
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="text-sm text-gray-400 truncate font-mono">{repoShort}</span>
        <span className="shrink-0 px-1.5 py-0.5 rounded text-xs font-mono bg-white/5 border border-white/10 text-gray-500">
          {branch}
        </span>
      </div>

      {/* Status badge */}
      <span className={`shrink-0 px-2.5 py-0.5 rounded-full text-xs font-medium border ${STATUS_STYLES[status]}`}>
        {status}
      </span>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Stats */}
      <div className="hidden sm:flex items-center gap-5 text-sm text-gray-400">
        <Stat label="Nodes"     value={node_count}      color="text-indigo-400" />
        <Stat label="Edges"     value={edge_count}      color="text-purple-400" />
        <Stat label="Clusters"  value={community_count} color="text-cyan-400" />
        <Stat label="God Nodes" value={graphData.nodes.filter(n => n.is_god).length} color="text-amber-400" />
      </div>

      <div className="w-px h-5 bg-white/10" />

      {/* User + sign out */}
      {user && (
        <span className="hidden md:block text-sm text-gray-500 truncate max-w-[140px]" title={user.email}>
          {user.display_name}
        </span>
      )}
      <button
        onClick={logout}
        className="text-sm text-gray-600 hover:text-red-400 transition-colors shrink-0"
        title="Sign out"
      >
        Sign out
      </button>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={`text-base font-bold tabular-nums ${color}`}>{value.toLocaleString()}</span>
      <span className="text-sm">{label}</span>
    </div>
  )
}
