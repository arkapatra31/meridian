import { useGraphStore } from '@/store'
import type { GraphNode } from '@/types'

const TYPE_BADGE: Record<string, string> = {
  module:   'bg-blue-500/15   text-blue-400   border-blue-500/20',
  class:    'bg-purple-500/15 text-purple-400 border-purple-500/20',
  function: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  method:   'bg-teal-500/15   text-teal-400   border-teal-500/20',
  external: 'bg-gray-500/15   text-gray-400   border-gray-500/20',
}

const TYPE_TEXT: Record<string, string> = {
  module:   'text-blue-400',
  class:    'text-purple-400',
  function: 'text-emerald-400',
  method:   'text-teal-400',
  external: 'text-gray-400',
}

const LANG_COLOR: Record<string, string> = {
  python:     'text-blue-400',
  typescript: 'text-sky-400',
  javascript: 'text-yellow-400',
  go:         'text-cyan-400',
  rust:       'text-orange-400',
}

const EDGE_COLOR: Record<string, string> = {
  CALLS:      'text-emerald-500',
  IMPORTS:    'text-blue-500',
  CONTAINS:   'text-purple-500',
  INHERITS:   'text-amber-500',
  DECORATES:  'text-pink-500',
  RELATES_TO: 'text-cyan-500',
  DEPENDS_ON: 'text-orange-500',
}

export default function NodeSidebar() {
  const { selectedNode, setSelectedNode, graphData } = useGraphStore()
  if (!selectedNode) return null

  const n = selectedNode
  const nodes = graphData?.nodes ?? []
  const edges = graphData?.edges ?? []

  // Build parent hierarchy by following CONTAINS edges upward
  const parents: GraphNode[] = []
  let currentId = n.id
  for (let i = 0; i < 10; i++) {
    const edge = edges.find(e => e.type === 'CONTAINS' && e.target === currentId)
    if (!edge) break
    const parent = nodes.find(nd => nd.id === edge.source)
    if (!parent) break
    parents.unshift(parent)
    currentId = parent.id
  }

  const inEdges  = edges.filter(e => e.target === n.id)
  const outEdges = edges.filter(e => e.source === n.id)

  return (
    <div className="slide-in-right absolute top-14 right-0 bottom-0 w-80 z-30 border-l border-gray-200 dark:border-white/5 bg-white dark:bg-[#0d1117]/95 backdrop-blur-md flex flex-col overflow-hidden">

      {/* Header */}
      <div className="flex items-start gap-3 p-4 border-b border-gray-200 dark:border-white/5">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1.5">
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${TYPE_BADGE[n.type] ?? TYPE_BADGE.external}`}>
              {n.type}
            </span>
            {n.is_god && (
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/20">
                ⚡ god node
              </span>
            )}
            {n.is_orphan && (
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-gray-500/15 text-gray-400 border border-gray-500/20">
                orphan
              </span>
            )}
          </div>
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white font-mono truncate" title={n.name}>
            {n.name}
          </h2>
        </div>
        <button
          onClick={() => setSelectedNode(null)}
          className="shrink-0 p-1 rounded text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">

        {/* Hierarchy breadcrumb */}
        {parents.length > 0 && (
          <Section title="Belongs To">
            <div className="flex items-center gap-1 flex-wrap text-xs font-mono leading-relaxed">
              {parents.map((p) => (
                <span key={p.id} className="flex items-center gap-1">
                  <span className={`${TYPE_TEXT[p.type] ?? 'text-gray-400'}`} title={p.id}>{p.name}</span>
                  <span className="text-gray-400 dark:text-gray-700">›</span>
                </span>
              ))}
              <span className="text-gray-900 dark:text-white font-semibold">{n.name}</span>
            </div>
            <div className="flex items-center gap-1 mt-1 text-[10px] font-mono flex-wrap">
              {parents.map((p, i) => (
                <span key={p.id} className="flex items-center gap-1">
                  <span className={`px-1.5 py-0.5 rounded border ${TYPE_BADGE[p.type] ?? TYPE_BADGE.external}`}>{p.type}</span>
                  {i < parents.length - 1 && <span className="text-gray-400 dark:text-gray-700">·</span>}
                </span>
              ))}
            </div>
          </Section>
        )}

        {/* Location */}
        <Section title="Location">
          <div className="text-xs font-mono text-gray-600 dark:text-gray-400 break-all leading-relaxed">
            {n.file}
            <span className="text-gray-400 dark:text-gray-600 ml-1">:{n.line_start}–{n.line_end}</span>
          </div>
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            <span className={`text-xs font-mono font-medium ${LANG_COLOR[n.language] ?? 'text-gray-400'}`}>
              {n.language}
            </span>
            <span className="text-gray-400 dark:text-gray-600">·</span>
            <span className="text-xs text-gray-500">cluster {n.community}</span>
            <span className="text-gray-400 dark:text-gray-600">·</span>
            <span className="text-xs text-gray-500">{inEdges.length} in / {outEdges.length} out</span>
          </div>
        </Section>

        {/* Docstring */}
        {n.docstring && (
          <Section title="Description">
            <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed font-mono whitespace-pre-wrap">
              {n.docstring}
            </p>
          </Section>
        )}

        {/* Parameters */}
        {n.params && n.params.length > 0 && (
          <Section title="Parameters">
            <div className="flex flex-col gap-1">
              {n.params.map((p, i) => (
                <span key={i} className="text-xs font-mono bg-gray-100 dark:bg-white/5 px-2 py-1 rounded text-gray-700 dark:text-gray-300">
                  {p}
                </span>
              ))}
            </div>
          </Section>
        )}

        {/* Outgoing connections */}
        {outEdges.length > 0 && (
          <Section title={`Calls / Exports (${outEdges.length})`}>
            <div className="flex flex-col gap-1.5">
              {outEdges.slice(0, 10).map((e, i) => (
                <ConnectionRow key={i} nodeId={String(e.target)} kind={e.type} confidence={e.confidence} direction="out" />
              ))}
              {outEdges.length > 10 && (
                <span className="text-[10px] text-gray-400 dark:text-gray-600 pl-4">+{outEdges.length - 10} more</span>
              )}
            </div>
          </Section>
        )}

        {/* Incoming connections */}
        {inEdges.length > 0 && (
          <Section title={`Referenced By (${inEdges.length})`}>
            <div className="flex flex-col gap-1.5">
              {inEdges.slice(0, 10).map((e, i) => (
                <ConnectionRow key={i} nodeId={String(e.source)} kind={e.type} confidence={e.confidence} direction="in" />
              ))}
              {inEdges.length > 10 && (
                <span className="text-[10px] text-gray-400 dark:text-gray-600 pl-4">+{inEdges.length - 10} more</span>
              )}
            </div>
          </Section>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[10px] font-semibold tracking-widest text-gray-400 dark:text-gray-600 uppercase">{title}</span>
      {children}
    </div>
  )
}

function ConnectionRow({
  nodeId, kind, confidence, direction,
}: {
  nodeId: string; kind: string; confidence: string; direction: 'in' | 'out'
}) {
  const shortName = nodeId.split('::').pop() ?? nodeId
  const file      = nodeId.split('::')[0] ?? ''
  const kindColor = EDGE_COLOR[kind] ?? 'text-gray-500'

  return (
    <div className="flex items-start gap-2 text-xs group">
      <span className="shrink-0 text-gray-400 dark:text-gray-700 mt-0.5">{direction === 'out' ? '→' : '←'}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className={`shrink-0 font-medium ${kindColor}`}>{kind}</span>
          {confidence === 'INFERRED' && (
            <span className="shrink-0 text-[10px] text-gray-400 dark:text-gray-600 italic">~inferred</span>
          )}
        </div>
        <span className="text-gray-700 dark:text-gray-300 font-mono truncate block" title={nodeId}>{shortName}</span>
        {file && (
          <span className="text-gray-400 dark:text-gray-600 font-mono text-[10px] truncate block">{file}</span>
        )}
      </div>
    </div>
  )
}
