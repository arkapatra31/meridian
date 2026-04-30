import { useRef, useState, useEffect, useMemo, useCallback } from 'react'
import ForceGraph3D from 'react-force-graph-3d'
import * as THREE from 'three'
import { useGraphStore } from '@/store'
import type { GraphNode } from '@/types'

const PALETTE = [
  '#ef4444','#f97316','#eab308','#22c55e',
  '#06b6d4','#3b82f6','#a855f7','#ec4899',
  '#14b8a6','#f59e0b','#84cc16','#8b5cf6',
]

const EDGE_COLOR: Record<string, string> = {
  IMPORTS:    '#60A5FA',
  CALLS:      '#F59E42',
  CONTAINS:   '#555577',
  INHERITS:   '#34D399',
  DECORATES:  '#ec4899',
  RELATES_TO: '#06b6d4',
  DEPENDS_ON: '#f97316',
}

const NODE_TYPE_STYLE: Record<string, { badge: string; dot: string }> = {
  module:   { badge: 'bg-blue-500/15 text-blue-400 border-blue-500/30',     dot: 'bg-blue-400' },
  class:    { badge: 'bg-purple-500/15 text-purple-400 border-purple-500/30', dot: 'bg-purple-400' },
  function: { badge: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', dot: 'bg-emerald-400' },
  method:   { badge: 'bg-teal-500/15 text-teal-400 border-teal-500/30',     dot: 'bg-teal-400' },
  external: { badge: 'bg-gray-500/15 text-gray-400 border-gray-500/30',     dot: 'bg-gray-400' },
}

const EDGE_TYPE_STYLE: Record<string, string> = {
  CALLS:      'bg-amber-500/15 text-amber-400 border-amber-500/30',
  IMPORTS:    'bg-blue-500/15 text-blue-400 border-blue-500/30',
  CONTAINS:   'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  INHERITS:   'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  DECORATES:  'bg-pink-500/15 text-pink-400 border-pink-500/30',
  RELATES_TO: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  DEPENDS_ON: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
}

const ALL_NODE_TYPES = ['module', 'class', 'function', 'method', 'external'] as const
const ALL_EDGE_TYPES = ['CALLS', 'IMPORTS', 'CONTAINS', 'INHERITS', 'DECORATES', 'RELATES_TO', 'DEPENDS_ON'] as const

function nodeColor(community: number) {
  return community < 0 ? '#6b7280' : PALETTE[community % PALETTE.length]
}

function makeLabelSprite(name: string, color: string) {
  const label = name.length > 22 ? name.slice(0, 20) + '…' : name
  const canvas = document.createElement('canvas')
  canvas.width = 320
  canvas.height = 52
  const ctx = canvas.getContext('2d')!
  ctx.font = 'bold 22px "JetBrains Mono", "Fira Code", monospace'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = color
  ctx.globalAlpha = 0.9
  ctx.fillText(label, 160, 26)
  const texture = new THREE.CanvasTexture(canvas)
  texture.needsUpdate = true
  const mat = new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false })
  const sprite = new THREE.Sprite(mat)
  sprite.scale.set(28, 5.5, 1)
  sprite.position.set(0, 9, 0)
  return sprite
}

function toggleSet<T>(set: Set<T>, val: T): Set<T> {
  const next = new Set(set)
  if (next.has(val)) next.delete(val); else next.add(val)
  return next
}

export default function GraphCanvas() {
  const { graphData, selectedNode, setSelectedNode, searchQuery, setSearchQuery } = useGraphStore()
  const containerRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<any>(null)
  const [dims, setDims] = useState({ w: window.innerWidth, h: window.innerHeight - 56 })
  const [filtersOpen, setFiltersOpen] = useState(false)

  // Filter state
  const [godOnly,    setGodOnly]    = useState(false)
  const [orphansOnly, setOrphansOnly] = useState(false)
  const [nodeTypes, setNodeTypes]   = useState<Set<string>>(() => new Set(ALL_NODE_TYPES))
  const [edgeTypes, setEdgeTypes]   = useState<Set<string>>(() => new Set(ALL_EDGE_TYPES))
  const [activeClusters, setActiveClusters] = useState<Set<number>>(new Set())

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect
      setDims({ w: width, h: height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const nodes = useMemo(() => graphData?.nodes ?? [], [graphData])
  const edges = useMemo(() => graphData?.edges ?? [], [graphData])

  const allClusters = useMemo(() => {
    const s = new Set<number>()
    nodes.forEach(n => { if (n.community >= 0) s.add(n.community) })
    return [...s].sort((a, b) => a - b)
  }, [nodes])

  const filteredNodes = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return nodes.filter(n => {
      if (!nodeTypes.has(n.type)) return false
      if (godOnly && !n.is_god) return false
      if (orphansOnly && !n.is_orphan) return false
      if (activeClusters.size > 0 && !activeClusters.has(n.community)) return false
      if (q && !n.name.toLowerCase().includes(q) && !n.file.toLowerCase().includes(q)) return false
      return true
    })
  }, [nodes, nodeTypes, godOnly, orphansOnly, activeClusters, searchQuery])

  const filteredNodeIds = useMemo(() => new Set(filteredNodes.map(n => n.id)), [filteredNodes])

  const filteredEdges = useMemo(() =>
    edges.filter(e =>
      edgeTypes.has(e.type) &&
      filteredNodeIds.has(e.source) &&
      filteredNodeIds.has(e.target)
    ),
  [edges, edgeTypes, filteredNodeIds])

  const fgData = useMemo(() => ({
    nodes: filteredNodes.map(n => ({ ...n })),
    links: filteredEdges.map(e => ({
      source: e.source, target: e.target,
      type: e.type, confidence: e.confidence, weight: e.weight,
    })),
  }), [filteredNodes, filteredEdges])

  // Collect glow halo materials so animateGlow can update them every frame.
  const glowMatsRef = useRef<THREE.MeshBasicMaterial[]>([])
  useEffect(() => { glowMatsRef.current = [] }, [fgData])

  const nodeThreeObj = useMemo(() => (node: object) => {
    const n = node as GraphNode
    const color = nodeColor(n.community)

    // Additive halo sphere slightly bigger than the default node sphere.
    const glowMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(color),
      transparent: true,
      opacity: 0.6,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.FrontSide,
    })
    glowMatsRef.current.push(glowMat)
    const halo = new THREE.Mesh(new THREE.SphereGeometry(7, 14, 14), glowMat)

    const group = new THREE.Group()
    group.add(halo)
    group.add(makeLabelSprite(n.name, color))
    return group
  }, [])

  // Pulse: opacity oscillates 0→max→0 with a 0.5 s full period.
  const animateGlow = useCallback(() => {
    const pulse = 0.5 + 0.5 * Math.sin(Date.now() * Math.PI / 250)
    for (const mat of glowMatsRef.current) mat.opacity = pulse * 0.7
  }, [])

  useEffect(() => {
    let rafId: number
    const loop = () => { animateGlow(); rafId = requestAnimationFrame(loop) }
    rafId = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(rafId)
  }, [animateGlow])

  const unlockZoom = () => {
    const fg = fgRef.current
    if (!fg) return
    const controls = fg.controls()
    if (controls) {
      controls.minDistance = 0.01
      controls.maxDistance = Infinity
    }
  }

  const isFiltered =
    godOnly || orphansOnly ||
    nodeTypes.size < ALL_NODE_TYPES.length ||
    edgeTypes.size < ALL_EDGE_TYPES.length ||
    activeClusters.size > 0

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative' }}>
      <ForceGraph3D
        ref={fgRef}
        graphData={fgData}
        width={dims.w}
        height={dims.h}
        backgroundColor="#0d1117"
        nodeColor={(node) => nodeColor((node as GraphNode).community)}
        nodeLabel={(node) => (node as GraphNode).name}
        nodeOpacity={0.9}
        nodeThreeObjectExtend
        nodeThreeObject={nodeThreeObj}
        linkColor={(link) => EDGE_COLOR[(link as { type: string }).type] ?? '#444'}
        linkWidth={(link) => (link as { confidence: string }).confidence === 'EXTRACTED' ? 0.8 : 0.4}
        linkOpacity={0.35}
        linkDirectionalArrowLength={3}
        linkDirectionalArrowRelPos={1}
        onEngineStop={unlockZoom}
        onNodeClick={(node) => {
          const n = node as GraphNode
          setSelectedNode(selectedNode?.id === n.id ? null : n)

          // Fly camera to face the clicked node and re-center the orbit on it.
          // This makes subsequent scroll-zoom go straight into that node.
          const fg = fgRef.current
          if (!fg) return
          const nx = (n as any).x ?? 0
          const ny = (n as any).y ?? 0
          const nz = (n as any).z ?? 0
          const mag = Math.hypot(nx, ny, nz) || 1
          const flyDistance = 80
          const scale = (mag + flyDistance) / mag
          fg.cameraPosition(
            { x: nx * scale, y: ny * scale, z: nz * scale },
            { x: nx, y: ny, z: nz },
            1200,
          )
        }}
      />

      {/* Search + filter toolbar */}
      <div className="absolute top-3 left-3 z-20 flex flex-col gap-2">
        <div className="flex items-center gap-2">
          {/* Search input */}
          <div className="relative">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none"
              fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search nodes…"
              className="w-56 pl-9 pr-8 py-2 text-sm rounded-lg bg-[#161b22]/90 backdrop-blur-sm border border-white/10 text-gray-300 placeholder-gray-600 outline-none focus:border-indigo-500/40 transition-colors"
            />
            {searchQuery && (
              <button onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            )}
          </div>

          {/* Filter toggle */}
          <button
            onClick={() => setFiltersOpen(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border backdrop-blur-sm transition-colors
              ${filtersOpen
                ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300'
                : isFiltered
                  ? 'bg-amber-500/15 border-amber-500/30 text-amber-400'
                  : 'bg-[#161b22]/90 border-white/10 text-gray-400 hover:text-gray-200 hover:border-white/20'
              }`}
          >
            <FilterIcon />
            Filters
            {isFiltered && (
              <span className="ml-0.5 px-1.5 py-0 rounded-full bg-amber-500/30 text-amber-300 text-xs leading-5">
                ON
              </span>
            )}
          </button>
        </div>

        {/* Filter panel */}
        {filtersOpen && (
          <div className="w-64 rounded-xl border border-white/8 bg-[#0d1117]/95 backdrop-blur-md shadow-2xl p-3 flex flex-col gap-3">

            {/* Quick toggles */}
            <FilterSection label="Quick Filters">
              <div className="flex flex-wrap gap-1.5">
                <QuickToggle
                  active={godOnly}
                  onClick={() => { setGodOnly(v => !v); setOrphansOnly(false) }}
                  label="⚡ God Nodes"
                  activeClass="bg-amber-500/20 text-amber-400 border-amber-500/40"
                />
                <QuickToggle
                  active={orphansOnly}
                  onClick={() => { setOrphansOnly(v => !v); setGodOnly(false) }}
                  label="Orphans"
                  activeClass="bg-red-500/20 text-red-400 border-red-500/40"
                />
              </div>
            </FilterSection>

            {/* Node types */}
            <FilterSection label="Node Types">
              <div className="flex flex-wrap gap-1">
                {ALL_NODE_TYPES.map(t => (
                  <button
                    key={t}
                    onClick={() => setNodeTypes(s => toggleSet(s, t))}
                    className={`px-2 py-0.5 rounded-full text-xs font-medium border transition-all
                      ${nodeTypes.has(t)
                        ? NODE_TYPE_STYLE[t]?.badge ?? 'bg-gray-500/15 text-gray-400 border-gray-500/30'
                        : 'bg-transparent text-gray-600 border-gray-700/50 line-through'
                      }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </FilterSection>

            {/* Edge types */}
            <FilterSection label="Edge Types">
              <div className="flex flex-wrap gap-1">
                {ALL_EDGE_TYPES.map(t => (
                  <button
                    key={t}
                    onClick={() => setEdgeTypes(s => toggleSet(s, t))}
                    className={`px-2 py-0.5 rounded-full text-xs font-medium border transition-all
                      ${edgeTypes.has(t)
                        ? EDGE_TYPE_STYLE[t] ?? 'bg-gray-500/15 text-gray-400 border-gray-500/30'
                        : 'bg-transparent text-gray-600 border-gray-700/50 line-through'
                      }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </FilterSection>

            {/* Clusters */}
            {allClusters.length > 0 && (
              <FilterSection label={`Clusters${activeClusters.size > 0 ? ` (${activeClusters.size} selected)` : ''}`}>
                <div className="flex flex-wrap gap-1">
                  {allClusters.map(c => {
                    const color = nodeColor(c)
                    const active = activeClusters.size === 0 || activeClusters.has(c)
                    return (
                      <button
                        key={c}
                        onClick={() => setActiveClusters(s => toggleSet(s, c))}
                        style={active ? { borderColor: color + '66', color, background: color + '1a' } : {}}
                        className={`px-2 py-0.5 rounded-full text-xs font-mono font-medium border transition-all
                          ${active
                            ? ''
                            : 'bg-transparent text-gray-600 border-gray-700/50 opacity-40'
                          }`}
                      >
                        C{c}
                      </button>
                    )
                  })}
                </div>
              </FilterSection>
            )}

            {/* Reset */}
            {isFiltered && (
              <button
                onClick={() => {
                  setGodOnly(false)
                  setOrphansOnly(false)
                  setNodeTypes(new Set(ALL_NODE_TYPES))
                  setEdgeTypes(new Set(ALL_EDGE_TYPES))
                  setActiveClusters(new Set())
                }}
                className="text-xs text-gray-500 hover:text-gray-300 transition-colors text-left"
              >
                ↺ Reset all filters
              </button>
            )}

            {/* Live count */}
            <div className="text-xs text-gray-600 border-t border-white/5 pt-2">
              Showing {filteredNodes.length.toLocaleString()} nodes · {filteredEdges.length.toLocaleString()} edges
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function FilterSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-semibold tracking-widest text-gray-600 uppercase">{label}</span>
      {children}
    </div>
  )
}

function QuickToggle({ active, onClick, label, activeClass }: {
  active: boolean; onClick: () => void; label: string; activeClass: string
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-0.5 rounded-full text-xs font-medium border transition-all
        ${active ? activeClass : 'bg-transparent text-gray-500 border-gray-700/50 hover:text-gray-300'}`}
    >
      {label}
    </button>
  )
}

function FilterIcon() {
  return (
    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M3 4h18M7 12h10M11 20h2" />
    </svg>
  )
}
