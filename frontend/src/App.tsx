import { useState, useEffect } from 'react'
import { useAuthStore } from './authStore'
import { useGraphStore } from './store'
import { useThemeStore } from './themeStore'
import LoginPage from './components/LoginPage'
import RegisterPage from './components/RegisterPage'
import RepoDashboard from './components/RepoDashboard'
import StatsBar from './components/StatsBar'
import GraphCanvas from './components/GraphCanvas'
import NodeSidebar from './components/NodeSidebar'

export default function App() {
  const { token } = useAuthStore()
  const { graphData, loading, reset: resetGraph } = useGraphStore()
  const [page, setPage] = useState<'login' | 'register'>('login')
  const { isDark } = useThemeStore()

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
  }, [isDark])

  useEffect(() => {
    if (!token) resetGraph()
  }, [token, resetGraph])

  if (!token) {
    return page === 'login'
      ? <LoginPage onGoRegister={() => setPage('register')} />
      : <RegisterPage onGoLogin={() => setPage('login')} />
  }

  if (!graphData && !loading) return <RepoDashboard />

  return (
    <div className="relative w-full h-full bg-gray-50 dark:bg-[#0d1117] overflow-hidden">
      <StatsBar />
      <div className="absolute inset-0 top-14">
        {loading ? <LoadingOverlay onCancel={resetGraph} /> : <GraphCanvas />}
      </div>
      <NodeSidebar />
    </div>
  )
}

function LoadingOverlay({ onCancel }: { onCancel: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4">
      <div className="relative">
        <div className="w-16 h-16 rounded-full border-2 border-indigo-500/20 border-t-indigo-500 animate-spin" />
        <div
          className="absolute inset-0 w-16 h-16 rounded-full border-2 border-transparent border-b-purple-500/40 animate-spin"
          style={{ animationDuration: '1.5s', animationDirection: 'reverse' }}
        />
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 tracking-wide">Loading graph…</p>
      <button
        onClick={onCancel}
        className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-600 hover:text-gray-700 dark:hover:text-gray-400 transition-colors mt-1"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Cancel, back to Dashboard
      </button>
    </div>
  )
}
