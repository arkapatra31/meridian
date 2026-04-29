import { useState, useEffect, useRef, FormEvent } from 'react'
import { useAuthStore } from '@/authStore'
import { useGraphStore } from '@/store'
import type { GraphSummary } from '@/types'

const STATUS_STYLES = {
  READY:    'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20',
  BUILDING: 'bg-amber-500/15  text-amber-400  border border-amber-500/20',
  ERROR:    'bg-red-500/15    text-red-400    border border-red-500/20',
}

const TIME_STAGES = [
  { label: 'Cloning repository',              cumulative: 4,  icon: 'git'     },
  { label: 'Parsing code (tree-sitter)',       cumulative: 10, icon: 'code'    },
  { label: 'Resolving cross-file references',  cumulative: 19, icon: 'search'  },
  { label: 'Agent resolving ambiguous edges',  cumulative: 99, icon: 'agent'   },
]
const EVENT_STAGES = [
  { label: 'Building knowledge graph',  icon: 'graph'   },
  { label: 'Clustering communities',    icon: 'cluster' },
]

function stripGit(url: string): string {
  return url.replace(/^https?:\/\/github\.com\//, '').replace(/\.git$/, '')
}

export default function RepoDashboard() {
  const { token, user, logout } = useAuthStore()
  const { graphs, graphsLoading, graphsError, syncLoading, syncError, listGraphs, syncRepo, loadGraph, deleteGraph } = useGraphStore()

  const [repoUrl, setRepoUrl]         = useState('')
  const [pat, setPat]                 = useState('')
  const [branch, setBranch]           = useState('')
  const [buildingId, setBuildingId]   = useState<string | null>(null)
  const [buildDone, setBuildDone]     = useState(false)
  const [justReadyId, setJustReadyId] = useState<string | null>(null)
  const [deletingId, setDeletingId]   = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (token) listGraphs(token)
  }, [token])

  useEffect(() => {
    if (!buildingId || !token) return
    pollRef.current = setInterval(() => listGraphs(token), 3000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [buildingId, token])

  useEffect(() => {
    if (!buildingId || buildDone) return
    const g = graphs.find(g => g.graph_id === buildingId)
    if (g && g.status !== 'BUILDING') {
      if (pollRef.current) clearInterval(pollRef.current)
      if (g.status === 'READY') {
        setJustReadyId(buildingId)
        setBuildDone(true)
      } else {
        setBuildingId(null)
      }
    }
  }, [graphs, buildingId, buildDone])

  useEffect(() => {
    if (!justReadyId) return
    const t = setTimeout(() => setJustReadyId(null), 7000)
    return () => clearTimeout(t)
  }, [justReadyId])

  const handleSync = async (e: FormEvent) => {
    e.preventDefault()
    if (!token || !repoUrl.trim() || !pat.trim()) return
    setJustReadyId(null)
    const graphId = await syncRepo(repoUrl.trim(), pat.trim(), branch.trim() || undefined, token)
    if (graphId) {
      setBuildingId(graphId)
      setRepoUrl('')
      setPat('')
      setBranch('')
      listGraphs(token)
    }
  }

  const handleOpenGraph = (id: string) => {
    if (token) loadGraph(id, token)
  }

  const handleDelete = async (id: string) => {
    if (!token) return
    setDeletingId(id)
    await deleteGraph(id, token)
    setDeletingId(null)
  }

  const isBuilding = syncLoading || !!buildingId

  return (
    <div className="relative min-h-full bg-[#0d1117] overflow-auto">
      {/* Background grid */}
      <div
        className="fixed inset-0 opacity-[0.025] pointer-events-none"
        style={{
          backgroundImage: 'linear-gradient(#6366f1 1px, transparent 1px), linear-gradient(90deg, #6366f1 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }}
      />
      <div className="fixed top-1/4 left-1/4 w-[500px] h-[500px] bg-indigo-600/8 rounded-full blur-[160px] pointer-events-none" />
      <div className="fixed bottom-1/4 right-1/4 w-[400px] h-[400px] bg-purple-600/8 rounded-full blur-[140px] pointer-events-none" />

      {/* Top nav */}
      <div className="relative z-10 flex items-center justify-between px-6 h-14 border-b border-white/5 bg-[#0d1117]/80 backdrop-blur-sm sticky top-0">
        <div className="flex items-center gap-2.5">
          <MeridianLogo />
          <span className="text-base font-bold text-white tracking-tight">Meridian</span>
          <span className="text-gray-700 text-sm mx-0.5">/</span>
          <span className="text-sm text-gray-500">Dashboard</span>
        </div>
        <div className="flex items-center gap-4">
          {user && (
            <span className="text-sm text-gray-500 truncate max-w-[180px]" title={user.email}>
              {user.display_name}
            </span>
          )}
          <button onClick={logout} className="text-sm text-gray-600 hover:text-red-400 transition-colors">
            Sign out
          </button>
        </div>
      </div>

      <div className="relative z-10 max-w-4xl mx-auto px-6 py-10 flex flex-col gap-10">

        {/* ── Sync form ── */}
        <section>
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-4">
            Sync a repository
          </h2>
          <div className="rounded-2xl border border-white/5 bg-white/[0.03] backdrop-blur-sm p-6 flex flex-col gap-4">
            {justReadyId && (
              <div className="flex items-center gap-2.5 text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2.5">
                <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Graph built successfully — ready to explore below.
              </div>
            )}
            <form onSubmit={handleSync} className="flex flex-col gap-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="flex flex-col gap-1.5 sm:col-span-2">
                  <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Repository URL <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="url"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                    placeholder="https://github.com/owner/repo"
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-4 py-2.5 text-sm text-white placeholder-gray-600 outline-none focus:border-indigo-500/50 transition-colors font-mono disabled:opacity-50"
                    required
                    disabled={isBuilding}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    GitHub PAT <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="password"
                    value={pat}
                    onChange={(e) => setPat(e.target.value)}
                    placeholder="ghp_xxxxxxxxxxxx"
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-4 py-2.5 text-sm text-white placeholder-gray-600 outline-none focus:border-indigo-500/50 transition-colors font-mono disabled:opacity-50"
                    required
                    disabled={isBuilding}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Branch <span className="text-gray-600">(optional)</span>
                  </label>
                  <input
                    type="text"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    placeholder="main"
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-4 py-2.5 text-sm text-white placeholder-gray-600 outline-none focus:border-indigo-500/50 transition-colors font-mono disabled:opacity-50"
                    disabled={isBuilding}
                  />
                </div>
              </div>
              {syncError && (
                <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                  {syncError}
                </p>
              )}
              <button
                type="submit"
                disabled={isBuilding || !repoUrl.trim() || !pat.trim()}
                className="self-start px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-semibold text-white transition-colors"
              >
                {isBuilding ? (
                  <span className="flex items-center gap-2">
                    <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    {buildingId ? 'Building…' : 'Syncing…'}
                  </span>
                ) : 'Sync Repository'}
              </button>
            </form>
          </div>
        </section>

        {/* ── Knowledge graphs ── */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
              Your knowledge graphs
            </h2>
            <button
              onClick={() => token && listGraphs(token)}
              disabled={graphsLoading}
              className="flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-400 transition-colors disabled:opacity-40"
            >
              <svg className={`w-3 h-3 ${graphsLoading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {graphsLoading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>

          {graphsError && (
            <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-4">
              {graphsError}
            </p>
          )}

          {graphsLoading && graphs.length === 0 ? (
            <div className="flex items-center justify-center h-32 text-sm text-gray-600">
              <span className="w-4 h-4 border-2 border-white/20 border-t-indigo-500 rounded-full animate-spin mr-2" />
              Loading graphs…
            </div>
          ) : graphs.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-white/8 flex flex-col items-center justify-center h-36 gap-2">
              <p className="text-sm text-gray-600">No graphs yet</p>
              <p className="text-xs text-gray-700">Sync a repository above to get started.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {graphs.map((g) => (
                <GraphCard
                  key={g.graph_id}
                  graph={g}
                  onOpen={handleOpenGraph}
                  onDelete={handleDelete}
                  isNew={g.graph_id === justReadyId}
                  isDeleting={deletingId === g.graph_id}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      {/* ── Building modal ── */}
      {isBuilding && (
        <BuildingModal
          graphId={buildingId ?? ''}
          done={buildDone}
          onClose={() => { setBuildingId(null); setBuildDone(false) }}
        />
      )}
    </div>
  )
}


function BuildingModal({ graphId, done, onClose }: { graphId: string; done: boolean; onClose: () => void }) {
  const [elapsed, setElapsed] = useState(0)
  const [postDone, setPostDone] = useState<null | 'building' | 'clustering' | 'complete'>(null)
  const stageStartRef = useRef<Record<number, number>>({})
  const prevActiveRef = useRef<number>(-1)

  useEffect(() => {
    const t = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!done) return
    setPostDone('building')
    const t1 = setTimeout(() => setPostDone('clustering'), 1000)
    const t2 = setTimeout(() => setPostDone('complete'), 2000)
    return () => { clearTimeout(t1); clearTimeout(t2) }
  }, [done])

  const activeIdx = (() => {
    if (postDone === 'complete') return 6
    if (postDone === 'clustering') return 5
    if (postDone === 'building') return 4
    const i = TIME_STAGES.findIndex(s => elapsed < s.cumulative)
    return i === -1 ? 3 : i
  })()

  if (prevActiveRef.current !== activeIdx) {
    stageStartRef.current[activeIdx] = elapsed
    prevActiveRef.current = activeIdx
  }

  const stageElapsed = elapsed - (stageStartRef.current[activeIdx] ?? 0)
  const sm = Math.floor(stageElapsed / 60)
  const ss = stageElapsed % 60
  const stageStr = sm > 0 ? `${sm}m ${ss}s` : `${ss}s`

  const allStages = [...TIME_STAGES, ...EVENT_STAGES]
  const isComplete = postDone === 'complete'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
      {/* Fully opaque backdrop */}
      <div className="absolute inset-0 bg-[#060912] opacity-[0.97]" />

      {/* Modal */}
      <div className="relative w-full max-w-2xl rounded-3xl border border-white/[0.07] bg-[#080d18]
        shadow-[0_0_0_1px_rgba(99,102,241,0.05),0_32px_80px_rgba(0,0,0,0.75)]">

        {/* Top accent line */}
        <div className="absolute top-0 inset-x-0 h-px bg-gradient-to-r from-transparent via-indigo-500/30 to-transparent rounded-t-3xl" />

        <div className="p-8 flex flex-col gap-6">

          {/* Status header */}
          <div className="flex items-center gap-2">
            {isComplete
              ? <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              : <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />}
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
              {isComplete ? 'Graph ready' : 'Building knowledge graph'}
            </span>
          </div>

          {/* Body: animation left + content right */}
          <div className="flex gap-8 items-center">

            {/* Left: radar animation */}
            <div className="shrink-0">
              <RadarScanAnimation activeIdx={activeIdx} done={isComplete} />
            </div>

            {/* Right: stages or completion */}
            <div className="flex-1 min-w-0">
              {isComplete ? (
                <div className="flex flex-col gap-5">
                  <div className="flex items-center gap-4">
                    <div className="w-11 h-11 rounded-full bg-emerald-500/15 border border-emerald-500/25 flex items-center justify-center shrink-0">
                      <svg className="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                      </svg>
                    </div>
                    <div>
                      <p className="text-base text-emerald-400 font-semibold">Built successfully</p>
                      {graphId && <p className="text-xs text-gray-600 font-mono mt-0.5">{graphId.slice(0, 8)}…</p>}
                    </div>
                  </div>
                  <p className="text-sm text-gray-500 leading-relaxed">
                    Your knowledge graph is ready to explore. Click nodes to inspect definitions, edges show call and import relationships.
                  </p>
                  <button
                    onClick={onClose}
                    className="self-start px-7 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold text-white transition-colors"
                  >
                    View Dashboard
                  </button>
                </div>
              ) : (
                <div className="flex flex-col gap-1">
                  {allStages.map((stage, i) => {
                    const isDone   = i < activeIdx
                    const isActive = i === activeIdx
                    return (
                      <div key={stage.label}
                        className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-500 ${
                          isActive ? 'bg-indigo-500/[0.08] border border-indigo-500/15' : ''
                        }`}
                      >
                        <StageIcon type={stage.icon} state={isDone ? 'done' : isActive ? 'active' : 'pending'} />
                        <span className={`text-sm flex-1 transition-colors duration-300 ${
                          isDone ? 'text-gray-600' : isActive ? 'text-white font-medium' : 'text-gray-700'
                        }`}>
                          {stage.label}
                        </span>
                        {isActive && (
                          <span className="text-xs text-indigo-400 font-mono tabular-nums">{stageStr}</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function RadarScanAnimation({ activeIdx, done }: { activeIdx: number; done: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stateRef  = useRef({ activeIdx, done })

  useEffect(() => { stateRef.current = { activeIdx, done } }, [activeIdx, done])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const S = 220
    canvas.width  = S
    canvas.height = S
    const cx = S / 2, cy = S / 2

    const NODES = [
      { r: 0,  a: 0,                    color: '#6366f1', size: 5   },
      { r: 44, a: 0,                    color: '#a78bfa', size: 3.5 },
      { r: 44, a: (Math.PI * 2) / 3,    color: '#7c3aed', size: 3.5 },
      { r: 44, a: (Math.PI * 4) / 3,    color: '#a78bfa', size: 3.5 },
      { r: 78, a: Math.PI / 6,          color: '#34d399', size: 3   },
      { r: 78, a: Math.PI * (5 / 6),    color: '#38bdf8', size: 3   },
      { r: 78, a: Math.PI * (3 / 2),    color: '#f472b6', size: 3   },
    ]
    const EDGES: [number, number][] = [[0,1],[0,2],[0,3],[1,4],[2,5],[3,6],[4,5],[5,6]]

    const nodeXY = (n: typeof NODES[0]) => ({
      x: cx + Math.cos(n.a) * n.r,
      y: cy + Math.sin(n.a) * n.r,
    })

    const alpha  = NODES.map(() => 0)
    const eAlpha = EDGES.map(() => 0)
    let sweep  = 0
    let animId: number

    const tick = () => {
      ctx.clearRect(0, 0, S, S)
      const { activeIdx, done } = stateRef.current
      sweep += 0.025

      // Fade nodes in/out
      for (let i = 0; i < NODES.length; i++) {
        alpha[i] += ((done || i <= activeIdx ? 1 : 0) - alpha[i]) * 0.07
      }
      // Fade edges in when done
      for (let i = 0; i < EDGES.length; i++) {
        eAlpha[i] += ((done ? 1 : 0) - eAlpha[i]) * 0.05
      }

      // Dashed orbit rings
      for (const r of [44, 78]) {
        ctx.beginPath()
        ctx.arc(cx, cy, r, 0, Math.PI * 2)
        ctx.strokeStyle = 'rgba(99,102,241,0.1)'
        ctx.lineWidth = 1
        ctx.setLineDash([2, 7])
        ctx.stroke()
        ctx.setLineDash([])
      }

      // Outer boundary
      ctx.beginPath()
      ctx.arc(cx, cy, 92, 0, Math.PI * 2)
      ctx.strokeStyle = 'rgba(99,102,241,0.06)'
      ctx.lineWidth = 1
      ctx.stroke()

      // Radar sweep (only while building)
      if (!done) {
        ctx.save()
        ctx.beginPath()
        ctx.moveTo(cx, cy)
        ctx.arc(cx, cy, 92, sweep - Math.PI / 3, sweep)
        ctx.closePath()
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, 92)
        g.addColorStop(0, 'rgba(99,102,241,0)')
        g.addColorStop(1, 'rgba(99,102,241,0.11)')
        ctx.fillStyle = g
        ctx.fill()

        ctx.beginPath()
        ctx.moveTo(cx, cy)
        ctx.lineTo(cx + Math.cos(sweep) * 92, cy + Math.sin(sweep) * 92)
        ctx.strokeStyle = 'rgba(99,102,241,0.55)'
        ctx.lineWidth = 1.5
        ctx.stroke()
        ctx.restore()
      }

      // Edges (only when done, clean sharp lines)
      for (let i = 0; i < EDGES.length; i++) {
        if (eAlpha[i] < 0.01) continue
        const [a, b] = EDGES[i]
        const pa = nodeXY(NODES[a]), pb = nodeXY(NODES[b])
        ctx.beginPath()
        ctx.moveTo(pa.x, pa.y)
        ctx.lineTo(pb.x, pb.y)
        ctx.strokeStyle = `rgba(99,102,241,${eAlpha[i] * 0.22})`
        ctx.lineWidth = 1
        ctx.stroke()
      }

      // Nodes with crosshair ticks
      for (let i = 0; i < NODES.length; i++) {
        if (alpha[i] < 0.01) continue
        const n  = NODES[i]
        const { x, y } = nodeXY(n)
        const a  = alpha[i]
        const ha = Math.round(a * 255).toString(16).padStart(2, '0')
        const hd = Math.round(a * 100).toString(16).padStart(2, '0')
        const tk = n.size + 5

        ctx.strokeStyle = n.color + hd
        ctx.lineWidth = 0.8
        ctx.beginPath()
        ctx.moveTo(x - tk, y);         ctx.lineTo(x - n.size - 1, y)
        ctx.moveTo(x + n.size + 1, y); ctx.lineTo(x + tk, y)
        ctx.moveTo(x, y - tk);         ctx.lineTo(x, y - n.size - 1)
        ctx.moveTo(x, y + n.size + 1); ctx.lineTo(x, y + tk)
        ctx.stroke()

        ctx.beginPath()
        ctx.arc(x, y, n.size, 0, Math.PI * 2)
        ctx.fillStyle = n.color + ha
        ctx.fill()
      }

      // Green center dot when complete
      if (done && alpha[0] > 0.5) {
        ctx.beginPath()
        ctx.arc(cx, cy, 5, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(52,211,153,${alpha[0] * 0.85})`
        ctx.fill()
      }

      animId = requestAnimationFrame(tick)
    }

    tick()
    return () => cancelAnimationFrame(animId)
  }, [])

  return <canvas ref={canvasRef} style={{ width: 220, height: 220 }} className="rounded-2xl" />
}

function StageIcon({ type, state }: { type: string; state: 'done' | 'active' | 'pending' }) {
  if (state === 'pending') {
    return (
      <div className="w-5 h-5 shrink-0 flex items-center justify-center">
        <div className="w-1.5 h-1.5 rounded-full bg-gray-700" />
      </div>
    )
  }
  if (state === 'done') {
    return (
      <div className="w-5 h-5 shrink-0 rounded-full bg-emerald-500/20 flex items-center justify-center">
        <svg className="w-3 h-3 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
        </svg>
      </div>
    )
  }
  // Active — type-specific animated icon
  const cls = 'w-4 h-4 text-indigo-400'
  const icon = (() => {
    switch (type) {
      case 'git':
        return (
          <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <circle cx="18" cy="6" r="3" strokeWidth={2} />
            <circle cx="6" cy="18" r="3" strokeWidth={2} />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 15V9a6 6 0 006 6h3" />
          </svg>
        )
      case 'code':
        return (
          <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l-3 3 3 3M16 9l3 3-3 3M12 5l-2 14" />
          </svg>
        )
      case 'search':
        return (
          <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <circle cx="11" cy="11" r="7" strokeWidth={2} />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35" />
          </svg>
        )
      case 'agent':
        return (
          <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
        )
      case 'graph':
        return (
          <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <circle cx="5"  cy="12" r="2" strokeWidth={2} />
            <circle cx="19" cy="5"  r="2" strokeWidth={2} />
            <circle cx="19" cy="19" r="2" strokeWidth={2} />
            <path strokeLinecap="round" strokeWidth={2} d="M7 12h5M14 7l3-1M14 17l3 1" />
          </svg>
        )
      case 'cluster':
        return (
          <svg className={cls} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M4 7l8-4 8 4M4 7l8 4 8-4M4 7v10l8 4 8-4V7M12 11v10" />
          </svg>
        )
      default:
        return <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
    }
  })()

  return (
    <div className="w-5 h-5 shrink-0 flex items-center justify-center animate-pulse" style={{ animationDuration: '1.4s' }}>
      {icon}
    </div>
  )
}


function GraphCard({ graph, onOpen, onDelete, isNew, isDeleting }: {
  graph: GraphSummary
  onOpen: (id: string) => void
  onDelete: (id: string) => void
  isNew?: boolean
  isDeleting?: boolean
}) {
  const repoStripped = stripGit(graph.repo_url)
  const repoName     = repoStripped.split('/').pop() ?? repoStripped
  const repoOwner    = repoStripped.includes('/') ? repoStripped.split('/').slice(0, -1).join('/') : ''
  const updatedAgo   = formatRelativeDate(graph.updated_at)
  const isBuilding   = graph.status === 'BUILDING'
  const [confirmDelete, setConfirmDelete] = useState(false)

  return (
    <div className={`rounded-2xl border p-5 flex flex-col gap-3 transition-all duration-500 ${
      isNew
        ? 'border-emerald-500/30 bg-emerald-500/[0.04] shadow-[0_0_40px_rgba(52,211,153,0.08)]'
        : 'border-white/5 bg-white/[0.03]'
    } ${isDeleting ? 'opacity-50 pointer-events-none' : ''}`}>

      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {repoOwner && (
            <p className="text-xs text-gray-600 truncate font-mono mb-0.5">{repoOwner}/</p>
          )}
          <p className="text-sm font-semibold text-white truncate">{repoName}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium flex items-center gap-1.5 ${STATUS_STYLES[graph.status]}`}>
            {isBuilding && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />}
            {graph.status}
          </span>
          {/* Delete */}
          {confirmDelete ? (
            <div className="flex items-center gap-1">
              <button
                onClick={() => onDelete(graph.graph_id)}
                className="text-[11px] text-red-400 hover:text-red-300 font-medium transition-colors"
              >
                Confirm
              </button>
              <span className="text-gray-700 text-[11px]">/</span>
              <button
                onClick={() => setConfirmDelete(false)}
                className="text-[11px] text-gray-600 hover:text-gray-400 transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              className="text-gray-500 hover:text-red-400 transition-colors"
              title="Delete graph"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Branch */}
      <p className="text-xs font-mono text-gray-600">
        <span className="text-gray-700">branch:</span> {graph.branch}
      </p>

      {/* Stats */}
      <div className="flex items-center gap-4 text-xs text-gray-500">
        <Stat label="nodes"    value={graph.node_count}      color="text-indigo-400" />
        <Stat label="edges"    value={graph.edge_count}      color="text-purple-400" />
        <Stat label="clusters" value={graph.community_count} color="text-cyan-400" />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-2 border-t border-white/5">
        <p className="text-xs text-gray-700">Updated {updatedAgo}</p>
        {graph.status === 'READY' ? (
          <button
            onClick={() => onOpen(graph.graph_id)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition-colors"
          >
            View Graph
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        ) : isBuilding ? (
          <span className="flex items-center gap-1.5 text-xs text-amber-400">
            <span className="w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
            In progress…
          </span>
        ) : (
          <span className="text-xs text-red-400">Build failed</span>
        )}
      </div>
    </div>
  )
}


function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <span>
      <span className={`font-semibold tabular-nums ${color}`}>{value.toLocaleString()}</span>{' '}
      <span>{label}</span>
    </span>
  )
}


function MeridianLogo() {
  return (
    <svg width="22" height="22" viewBox="0 0 28 28" fill="none">
      <circle cx="14" cy="14" r="3" fill="#6366f1" />
      <circle cx="14" cy="4"  r="2" fill="#a78bfa" />
      <circle cx="14" cy="24" r="2" fill="#a78bfa" />
      <circle cx="4"  cy="14" r="2" fill="#a78bfa" />
      <circle cx="24" cy="14" r="2" fill="#a78bfa" />
      <circle cx="6"  cy="6"  r="1.5" fill="#6366f1" opacity="0.5" />
      <circle cx="22" cy="6"  r="1.5" fill="#6366f1" opacity="0.5" />
      <circle cx="6"  cy="22" r="1.5" fill="#6366f1" opacity="0.5" />
      <circle cx="22" cy="22" r="1.5" fill="#6366f1" opacity="0.5" />
      <line x1="14" y1="11" x2="14" y2="6"  stroke="#6366f1" strokeWidth="1" opacity="0.6" />
      <line x1="14" y1="17" x2="14" y2="22" stroke="#6366f1" strokeWidth="1" opacity="0.6" />
      <line x1="11" y1="14" x2="6"  y2="14" stroke="#6366f1" strokeWidth="1" opacity="0.6" />
      <line x1="17" y1="14" x2="22" y2="14" stroke="#6366f1" strokeWidth="1" opacity="0.6" />
    </svg>
  )
}


function formatRelativeDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins  = Math.floor(diff / 60_000)
  const hours = Math.floor(diff / 3_600_000)
  const days  = Math.floor(diff / 86_400_000)
  if (mins < 1)   return 'just now'
  if (mins < 60)  return `${mins}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 30)  return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}
