import { useRef, useState, useEffect, useMemo } from 'react'
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

export default function GraphCanvas() {
  const { graphData, selectedNode, setSelectedNode } = useGraphStore()
  const containerRef = useRef<HTMLDivElement>(null)
  const [dims, setDims] = useState({ w: window.innerWidth, h: window.innerHeight - 48 })

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

  const fgData = useMemo(() => ({
    nodes: nodes.map(n => ({ ...n })),
    links: edges.map(e => ({
      source: e.source,
      target: e.target,
      type: e.type,
      confidence: e.confidence,
      weight: e.weight,
    })),
  }), [nodes, edges])

  const nodeThreeObj = useMemo(() => (node: object) => {
    const n = node as GraphNode
    return makeLabelSprite(n.name, nodeColor(n.community))
  }, [])

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative' }}>
      <ForceGraph3D
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
        onNodeClick={(node) => {
          const n = node as GraphNode
          setSelectedNode(selectedNode?.id === n.id ? null : n)
        }}
      />

      {/* Selected node detail strip */}
      {selectedNode && (
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0,
          background: 'rgba(13,17,23,0.88)',
          backdropFilter: 'blur(10px)',
          borderTop: '1px solid rgba(255,255,255,0.06)',
          padding: '10px 16px',
          display: 'flex', alignItems: 'center', gap: 12,
          fontSize: 11, fontFamily: '"JetBrains Mono","Fira Code",monospace',
          color: '#ccc', zIndex: 10,
        }}>
          <span style={{
            width: 10, height: 10, borderRadius: 2,
            background: nodeColor(selectedNode.community),
            display: 'inline-block', flexShrink: 0,
          }} />
          <strong style={{ color: '#e0e0e0', fontWeight: 600 }}>{selectedNode.name}</strong>
          <span style={{ color: '#555' }}>{selectedNode.type}</span>
          {selectedNode.is_god && (
            <span style={{
              background: '#F59E4222', color: '#F59E42',
              padding: '1px 7px', borderRadius: 4, fontSize: 10,
            }}>god node</span>
          )}
          {selectedNode.is_orphan && (
            <span style={{
              background: '#ef444422', color: '#ef4444',
              padding: '1px 7px', borderRadius: 4, fontSize: 10,
            }}>orphan</span>
          )}
          <span style={{
            background: nodeColor(selectedNode.community) + '1a',
            color: nodeColor(selectedNode.community),
            padding: '1px 7px', borderRadius: 4, fontSize: 10,
          }}>C{selectedNode.community}</span>
          <span style={{ color: '#444' }}>{selectedNode.file}:{selectedNode.line_start}</span>
          <div style={{ flex: 1 }} />
          <span style={{ color: '#555' }}>
            <span style={{ color: '#F59E42' }}>
              {edges.filter(e => e.source === selectedNode.id).length}
            </span> out
          </span>
          <span style={{ color: '#555' }}>
            <span style={{ color: '#60A5FA' }}>
              {edges.filter(e => e.target === selectedNode.id).length}
            </span> in
          </span>
          {selectedNode.docstring && (
            <span style={{ color: '#666', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {selectedNode.docstring}
            </span>
          )}
          <button
            onClick={() => setSelectedNode(null)}
            style={{ color: '#555', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, padding: '0 4px' }}
            className="hover:text-gray-300 transition-colors"
          >✕</button>
        </div>
      )}
    </div>
  )
}
