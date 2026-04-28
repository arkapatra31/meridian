import { useGraphStore } from '@/store'

const TYPE_COLORS: Record<string, string> = {
  module:   'bg-blue-500/15   text-blue-400   border-blue-500/20',
  class:    'bg-purple-500/15 text-purple-400 border-purple-500/20',
  function: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  method:   'bg-teal-500/15   text-teal-400   border-teal-500/20',
  external: 'bg-gray-500/15   text-gray-400   border-gray-500/20',
}

const LANG_COLORS: Record<string, string> = {
  python:     'text-blue-400',
  typescript: 'text-sky-400',
  javascript: 'text-yellow-400',
  go:         'text-cyan-400',
  rust:       'text-orange-400',
}

export default function NodeSidebar() {
  const { selectedNode, setSelectedNode, graphData } = useGraphStore()

  if (!selectedNode) return null

  const n = selectedNode
  const typeStyle = TYPE_COLORS[n.type] ?? TYPE_COLORS.external
  const langColor = LANG_COLORS[n.language] ?? 'text-gray-400'

  const inEdges  = graphData?.edges.filter((e) => e.target === n.id) ?? []
  const outEdges = graphData?.edges.filter((e) => e.source === n.id) ?? []

  return (
    <div className="slide-in-right absolute top-12 right-0 bottom-0 w-80 z-30 border-l border-white/5 bg-[#0d1117]/95 backdrop-blur-md flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-start gap-3 p-4 border-b border-white/5">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${typeStyle}`}>
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
          <h2 className="text-sm font-semibold text-white font-mono truncate" title={n.name}>
            {n.name}
          </h2>
        </div>
        <button
          onClick={() => setSelectedNode(null)}
          className="shrink-0 p-1 rounded text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">

        {/* File info */}
        <Section title="Location">
          <div className="text-xs font-mono text-gray-400 break-all leading-relaxed">
            {n.file}
            <span className="text-gray-600 ml-1">:{n.line_start}–{n.line_end}</span>
          </div>
          <div className="flex items-center gap-2 mt-2">
            <span className={`text-xs font-mono font-medium ${langColor}`}>{n.language}</span>
            <span className="text-gray-600">·</span>
            <span className="text-xs text-gray-500">community {n.community}</span>
          </div>
        </Section>

        {/* Docstring */}
        {n.docstring && (
          <Section title="Docstring">
            <p className="text-xs text-gray-400 leading-relaxed font-mono whitespace-pre-wrap">
              {n.docstring}
            </p>
          </Section>
        )}

        {/* Params */}
        {n.params && n.params.length > 0 && (
          <Section title="Parameters">
            <div className="flex flex-col gap-1">
              {n.params.map((p, i) => (
                <span key={i} className="text-xs font-mono bg-white/5 px-2 py-1 rounded text-gray-300">
                  {p}
                </span>
              ))}
            </div>
          </Section>
        )}

        {/* Connections */}
        <Section title={`Connections (${inEdges.length} in · ${outEdges.length} out)`}>
          <div className="flex flex-col gap-2">
            {outEdges.slice(0, 8).map((e, i) => (
              <EdgeRow key={i} label={String(e.target)} kind={e.type} confidence={e.confidence} direction="out" />
            ))}
            {inEdges.slice(0, 8).map((e, i) => (
              <EdgeRow key={i} label={String(e.source)} kind={e.type} confidence={e.confidence} direction="in" />
            ))}
            {(inEdges.length + outEdges.length) > 16 && (
              <span className="text-xs text-gray-600 text-center">
                +{inEdges.length + outEdges.length - 16} more
              </span>
            )}
          </div>
        </Section>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[10px] font-semibold tracking-widest text-gray-600 uppercase">{title}</span>
      {children}
    </div>
  )
}

const EDGE_KIND_COLORS: Record<string, string> = {
  CALLS:     'text-emerald-500',
  IMPORTS:   'text-blue-500',
  CONTAINS:  'text-purple-500',
  INHERITS:  'text-amber-500',
  DECORATES: 'text-pink-500',
  RELATES_TO:'text-cyan-500',
  DEPENDS_ON:'text-orange-500',
}

function EdgeRow({
  label, kind, confidence, direction,
}: {
  label: string; kind: string; confidence: string; direction: 'in' | 'out'
}) {
  const kindColor = EDGE_KIND_COLORS[kind] ?? 'text-gray-500'
  const nodeId = label.split('::').pop() ?? label

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`shrink-0 text-gray-600`}>{direction === 'out' ? '→' : '←'}</span>
      <span className={`shrink-0 font-medium ${kindColor}`}>{kind}</span>
      <span className="text-gray-400 truncate font-mono" title={label}>{nodeId}</span>
      {confidence === 'INFERRED' && (
        <span className="shrink-0 text-[10px] text-gray-600 italic">~</span>
      )}
    </div>
  )
}
