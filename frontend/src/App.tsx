import { useGraphStore } from './store'
import GraphIdInput from './components/GraphIdInput'
import StatsBar from './components/StatsBar'
import GraphCanvas from './components/GraphCanvas'

export default function App() {
  const { graphData, loading } = useGraphStore()

  if (!graphData && !loading) return <GraphIdInput />

  return (
    <div className="relative w-full h-full bg-[#0d1117] overflow-hidden">
      <StatsBar />
      <div className="absolute inset-0 top-12">
        {loading ? <LoadingOverlay /> : <GraphCanvas />}
      </div>
    </div>
  )
}

function LoadingOverlay() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4">
      <div className="relative">
        <div className="w-16 h-16 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin" />
        <div className="absolute inset-0 w-16 h-16 rounded-full border-2 border-transparent border-b-purple-500/40 animate-spin"
          style={{ animationDuration: '1.5s', animationDirection: 'reverse' }} />
      </div>
      <p className="text-sm text-gray-400 tracking-wide">Building graph…</p>
    </div>
  )
}
