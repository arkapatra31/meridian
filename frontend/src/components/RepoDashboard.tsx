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
    if (!token || !repoUrl.trim() || !pat.trim() || !branch.trim()) return
    setJustReadyId(null)
    const graphId = await syncRepo(repoUrl.trim(), pat.trim(), branch.trim(), token)
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
                    Branch <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    placeholder="main"
                    className="w-full rounded-lg bg-white/5 border border-white/10 px-4 py-2.5 text-sm text-white placeholder-gray-600 outline-none focus:border-indigo-500/50 transition-colors font-mono disabled:opacity-50"
                    required
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
                disabled={isBuilding || !repoUrl.trim() || !pat.trim() || !branch.trim()}
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

            {/* Left: submarine animation */}
            <div className="shrink-0">
              <SubmarineAnimation activeIdx={activeIdx} done={isComplete} />
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

function SubmarineAnimation({ activeIdx: _activeIdx, done }: { activeIdx: number; done: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stateRef  = useRef({ done })

  useEffect(() => { stateRef.current = { done } }, [done])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const W = 220, H = 220
    canvas.width  = W
    canvas.height = H

    let subX = -55
    const subY = 152
    const centerX = W / 2
    let speed = 0.0
    let dir = 1          // 1 = left→right, -1 = right→left
    let propAngle = 0
    let frame = 0
    let doneTextAlpha = 0
    let donePulseSent = false
    let doneDirSet = false   // locked once when done=true first fires

    type Ping = { x: number; y: number; r: number; a: number }
    const pings: Ping[] = []
    let pingTimer = 50

    type Bubble = { x: number; y: number; r: number; vy: number; vx: number; a: number }
    const bubbles: Bubble[] = []

    let animId: number

    function rRect(x: number, y: number, w: number, h: number, r: number) {
      ctx.beginPath()
      ctx.moveTo(x + r, y)
      ctx.lineTo(x + w - r, y)
      ctx.quadraticCurveTo(x + w, y, x + w, y + r)
      ctx.lineTo(x + w, y + h - r)
      ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
      ctx.lineTo(x + r, y + h)
      ctx.quadraticCurveTo(x, y + h, x, y + h - r)
      ctx.lineTo(x, y + r)
      ctx.quadraticCurveTo(x, y, x + r, y)
      ctx.closePath()
    }

    const tick = () => {
      const { done } = stateRef.current
      ctx.clearRect(0, 0, W, H)
      frame++

      // Background
      const bg = ctx.createLinearGradient(0, 0, 0, H)
      bg.addColorStop(0, '#06090e')
      bg.addColorStop(0.3, '#080e1c')
      bg.addColorStop(1, '#050810')
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, W, H)

      // Depth grid
      ctx.setLineDash([3, 9])
      ctx.lineWidth = 1
      for (let gy = 108; gy < H; gy += 28) {
        ctx.beginPath()
        ctx.strokeStyle = `rgba(99,102,241,${0.03 + (gy - 108) * 0.0004})`
        ctx.moveTo(0, gy)
        ctx.lineTo(W, gy)
        ctx.stroke()
      }
      ctx.setLineDash([])

      // Water surface
      const wY = 90
      ctx.beginPath()
      for (let wx = 0; wx <= W; wx++) {
        const wy = wY + Math.sin(wx * 0.045 + frame * 0.022) * 3.5
                      + Math.sin(wx * 0.018 + frame * 0.014) * 2
        if (wx === 0) ctx.moveTo(wx, wy); else ctx.lineTo(wx, wy)
      }
      ctx.strokeStyle = 'rgba(56,189,248,0.22)'
      ctx.lineWidth = 1.5
      ctx.stroke()

      // Above-water fill
      ctx.beginPath()
      for (let wx = 0; wx <= W; wx++) {
        const wy = wY + Math.sin(wx * 0.045 + frame * 0.022) * 3.5
                      + Math.sin(wx * 0.018 + frame * 0.014) * 2
        if (wx === 0) ctx.moveTo(wx, wy); else ctx.lineTo(wx, wy)
      }
      ctx.lineTo(W, 0); ctx.lineTo(0, 0); ctx.closePath()
      const wGrad = ctx.createLinearGradient(0, 0, 0, wY)
      wGrad.addColorStop(0, 'rgba(56,189,248,0.06)')
      wGrad.addColorStop(1, 'rgba(56,189,248,0.01)')
      ctx.fillStyle = wGrad
      ctx.fill()

      // Submarine movement
      if (!done) {
        speed = Math.min(speed + 0.018, 0.95)
        propAngle += 0.13

        // Flip direction at edges
        subX += speed * dir
        if (dir === 1 && subX > W + 55) {
          dir = -1; subX = W + 55; donePulseSent = false
        } else if (dir === -1 && subX < -55) {
          dir = 1; subX = -55; donePulseSent = false
        }
      } else {
        // Lock in the direction toward center once
        if (!doneDirSet) {
          dir = subX <= centerX ? 1 : -1
          doneDirSet = true
        }

        const dist = Math.abs(centerX - subX)
        if (dist > 1) {
          // Ease in: fast far away, slow near center
          speed = 0.08 + Math.min(dist / 80, 1) * 0.55
          subX += speed * dir
          // Clamp so we don't overshoot center
          if (dir === 1 && subX > centerX) subX = centerX
          if (dir === -1 && subX < centerX) subX = centerX
        } else {
          subX = centerX
          speed = 0
        }

        propAngle += Math.max(speed, 0) * 0.14
        doneTextAlpha = Math.min(doneTextAlpha + 0.018, 1)

        if (!donePulseSent && dist < 8) {
          const bowX = centerX + dir * 44
          pings.push({ x: bowX, y: subY, r: 0,  a: 1.1 })
          pings.push({ x: bowX, y: subY, r: 18, a: 0.8 })
          donePulseSent = true
        }
      }

      // Sonar ping emit from bow
      pingTimer++
      if (pingTimer >= 72 && !done) {
        pings.push({ x: subX + dir * 44, y: subY, r: 0, a: 0.75 })
        pingTimer = 0
      }

      // Draw pings
      for (let i = pings.length - 1; i >= 0; i--) {
        const p = pings[i]
        p.r += done ? 2.2 : 1.6
        p.a -= 0.01
        if (p.a <= 0) { pings.splice(i, 1); continue }
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.strokeStyle = done
          ? `rgba(52,211,153,${Math.max(0, p.a)})`
          : `rgba(99,102,241,${Math.max(0, p.a)})`
        ctx.lineWidth = 1.2
        ctx.stroke()
      }

      // Bubbles from propeller (always behind the sub)
      if (frame % 9 === 0 && speed > 0.15) {
        bubbles.push({
          x: subX - dir * 41 + (Math.random() - 0.5) * 8,
          y: subY - 10,
          r: 0.8 + Math.random() * 2,
          vy: -(0.28 + Math.random() * 0.38),
          vx: (Math.random() - 0.5) * 0.18,
          a: 0.5 + Math.random() * 0.3,
        })
      }
      for (let i = bubbles.length - 1; i >= 0; i--) {
        const b = bubbles[i]
        b.y += b.vy
        b.x += b.vx + Math.sin(frame * 0.07 + i) * 0.22
        b.a -= 0.007
        if (b.a <= 0 || b.y < wY - 8) { bubbles.splice(i, 1); continue }
        ctx.beginPath()
        ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(147,197,253,${b.a})`
        ctx.lineWidth = 0.8
        ctx.stroke()
      }

      // ── Draw submarine ──
      ctx.save()
      ctx.translate(subX, subY)
      if (dir === -1) ctx.scale(-1, 1)   // mirror so bow always faces direction of travel

      // Propeller wake
      for (let wi = 0; wi < 3; wi++) {
        const wa = (speed / 0.95) * (0.13 - wi * 0.04)
        if (wa < 0.01) continue
        ctx.beginPath()
        ctx.ellipse(-45 - wi * 8, 0, 3 + wi, 4 + wi * 1.5, 0, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(56,189,248,${wa})`
        ctx.lineWidth = 1
        ctx.stroke()
      }

      const bw = 88, bh = 22

      // Main hull
      ctx.beginPath()
      ctx.ellipse(0, 0, bw / 2, bh / 2, 0, 0, Math.PI * 2)
      ctx.fillStyle = '#2a4568'
      ctx.fill()
      ctx.strokeStyle = '#456898'
      ctx.lineWidth = 1.2
      ctx.stroke()

      // Hull highlight
      ctx.beginPath()
      ctx.ellipse(5, -bh / 4, bw / 2 - 10, bh / 5, 0, Math.PI, Math.PI * 2)
      ctx.fillStyle = 'rgba(80,120,160,0.22)'
      ctx.fill()

      // Conning tower
      const tX = 12, tW = 22, tH = 15
      rRect(tX - tW / 2, -bh / 2 - tH, tW, tH, 3)
      ctx.fillStyle = '#223858'
      ctx.fill()
      ctx.strokeStyle = '#456898'
      ctx.lineWidth = 1
      ctx.stroke()

      // Tower window
      ctx.beginPath()
      ctx.arc(tX, -bh / 2 - tH / 2, 3, 0, Math.PI * 2)
      ctx.fillStyle = done ? 'rgba(52,211,153,0.5)' : 'rgba(56,189,248,0.35)'
      ctx.fill()
      ctx.strokeStyle = done ? 'rgba(52,211,153,0.8)' : 'rgba(56,189,248,0.6)'
      ctx.lineWidth = 0.8
      ctx.stroke()

      // Periscope
      ctx.beginPath()
      ctx.moveTo(tX + 6, -bh / 2 - tH)
      ctx.lineTo(tX + 6, -bh / 2 - tH - 13)
      ctx.lineTo(tX + 13, -bh / 2 - tH - 13)
      ctx.strokeStyle = '#456898'
      ctx.lineWidth = 1.5
      ctx.stroke()
      ctx.beginPath()
      ctx.arc(tX + 13, -bh / 2 - tH - 13, 2.5, 0, Math.PI * 2)
      ctx.fillStyle = done ? '#34d399' : '#38bdf8'
      ctx.fill()

      // Diving planes
      ctx.beginPath()
      ctx.moveTo(-8, -bh / 2)
      ctx.lineTo(-8, -bh / 2 - 7)
      ctx.lineTo(6, -bh / 2 - 2)
      ctx.lineTo(6, -bh / 2)
      ctx.closePath()
      ctx.fillStyle = '#223858'
      ctx.fill()
      ctx.strokeStyle = '#456898'
      ctx.lineWidth = 0.8
      ctx.stroke()

      // Propeller blades
      ctx.save()
      ctx.translate(-bw / 2 + 2, 0)
      ctx.rotate(propAngle)
      for (let bi = 0; bi < 3; bi++) {
        ctx.save()
        ctx.rotate((Math.PI * 2 * bi) / 3)
        ctx.beginPath()
        ctx.ellipse(0, -7.5, 2.5, 7.5, 0.25, 0, Math.PI * 2)
        ctx.fillStyle = '#456898'
        ctx.fill()
        ctx.restore()
      }
      ctx.beginPath()
      ctx.arc(0, 0, 2.5, 0, Math.PI * 2)
      ctx.fillStyle = '#5b82a6'
      ctx.fill()
      ctx.restore()

      // Bow light
      ctx.beginPath()
      ctx.arc(bw / 2 - 4, 0, 3.5, 0, Math.PI * 2)
      ctx.fillStyle = done ? '#34d399' : '#6366f1'
      ctx.fill()
      if (done || frame % 60 < 30) {
        ctx.beginPath()
        ctx.arc(bw / 2 - 4, 0, 7, 0, Math.PI * 2)
        ctx.fillStyle = done ? 'rgba(52,211,153,0.14)' : 'rgba(99,102,241,0.12)'
        ctx.fill()
      }

      ctx.restore()

      // Done label
      if (doneTextAlpha > 0) {
        ctx.save()
        ctx.globalAlpha = doneTextAlpha
        ctx.fillStyle = '#34d399'
        ctx.font = '600 9px ui-monospace, monospace'
        ctx.textAlign = 'center'
        ctx.fillText('TARGET ACQUIRED', W / 2, H - 14)
        ctx.restore()
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
