import { useState, FormEvent } from 'react'
import { useGraphStore } from '@/store'

export default function GraphIdInput() {
  const [value, setValue] = useState('')
  const { loadGraph, loading, error } = useGraphStore()

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    const id = value.trim()
    if (id) loadGraph(id)
  }

  return (
    <div className="relative flex items-center justify-center w-full h-full overflow-hidden bg-[#0d1117]">
      {/* Subtle grid background */}
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: 'linear-gradient(#6366f1 1px, transparent 1px), linear-gradient(90deg, #6366f1 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }}
      />

      {/* Glow blobs */}
      <div className="absolute top-1/4 left-1/3 w-96 h-96 bg-indigo-600/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/3 w-80 h-80 bg-purple-600/10 rounded-full blur-[100px] pointer-events-none" />

      {/* Card */}
      <div className="relative z-10 w-full max-w-md px-4">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] backdrop-blur-sm p-8 shadow-2xl">
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center gap-2 mb-3">
              <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
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
              <span className="text-2xl font-bold tracking-tight text-white">Meridian</span>
            </div>
            <p className="text-sm text-gray-400">Code Knowledge Graph Explorer</p>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-gray-400 tracking-wide uppercase">
                Graph ID
              </label>
              <input
                type="text"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="e.g. 35f0a20b-4f5e-4260-8996-cc67a53b19dd"
                className="glow-input w-full rounded-lg bg-white/5 border border-white/10 px-4 py-3 text-sm text-white placeholder-gray-600 outline-none transition-all focus:border-indigo-500/50 font-mono"
                disabled={loading}
                autoFocus
              />
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !value.trim()}
              className="relative w-full py-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-semibold text-white transition-colors overflow-hidden"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Loading…
                </span>
              ) : (
                'Explore Graph'
              )}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-600 mt-4">
          Enter the graph_id returned from <span className="font-mono text-gray-500">POST /repos/sync</span>
        </p>
      </div>
    </div>
  )
}
