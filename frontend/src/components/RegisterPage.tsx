import { useState, FormEvent } from 'react'
import { useAuthStore } from '@/authStore'

export default function RegisterPage({ onGoLogin }: { onGoLogin: () => void }) {
  const [email, setEmail]         = useState('')
  const [displayName, setName]    = useState('')
  const [password, setPassword]   = useState('')
  const [github, setGithub]       = useState('')
  const { register, loading, error, clearError } = useAuthStore()

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    register(email, displayName, password, github || undefined)
  }

  return (
    <div className="relative flex items-center justify-center w-full h-full overflow-hidden bg-[#0d1117]">
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: 'linear-gradient(#6366f1 1px, transparent 1px), linear-gradient(90deg, #6366f1 1px, transparent 1px)',
          backgroundSize: '60px 60px',
        }}
      />
      <div className="absolute top-1/4 right-1/3 w-96 h-96 bg-purple-600/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/4 left-1/3 w-80 h-80 bg-indigo-600/10 rounded-full blur-[100px] pointer-events-none" />

      <div className="relative z-10 w-full max-w-md px-4">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] backdrop-blur-sm p-8 shadow-2xl">

          {/* Logo */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center gap-2 mb-3">
              <MeridianLogo />
              <span className="text-2xl font-bold tracking-tight text-white">Meridian</span>
            </div>
            <p className="text-sm text-gray-400">Create your account</p>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <Field label="Display name">
              <input
                type="text"
                value={displayName}
                onChange={e => { clearError(); setName(e.target.value) }}
                placeholder="Ada Lovelace"
                className="glow-input w-full rounded-lg bg-white/5 border border-white/10 px-4 py-3 text-sm text-white placeholder-gray-600 outline-none transition-all focus:border-indigo-500/50"
                disabled={loading}
                autoFocus
              />
            </Field>

            <Field label="Email">
              <input
                type="email"
                value={email}
                onChange={e => { clearError(); setEmail(e.target.value) }}
                placeholder="you@example.com"
                className="glow-input w-full rounded-lg bg-white/5 border border-white/10 px-4 py-3 text-sm text-white placeholder-gray-600 outline-none transition-all focus:border-indigo-500/50"
                disabled={loading}
              />
            </Field>

            <Field label="Password">
              <input
                type="password"
                value={password}
                onChange={e => { clearError(); setPassword(e.target.value) }}
                placeholder="Min. 8 characters"
                className="glow-input w-full rounded-lg bg-white/5 border border-white/10 px-4 py-3 text-sm text-white placeholder-gray-600 outline-none transition-all focus:border-indigo-500/50"
                disabled={loading}
              />
            </Field>

            <Field label="GitHub username (optional)">
              <input
                type="text"
                value={github}
                onChange={e => setGithub(e.target.value)}
                placeholder="octocat"
                className="glow-input w-full rounded-lg bg-white/5 border border-white/10 px-4 py-3 text-sm text-white placeholder-gray-600 outline-none transition-all focus:border-indigo-500/50"
                disabled={loading}
              />
            </Field>

            {error && (
              <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !email || !displayName || password.length < 8}
              className="w-full py-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-semibold text-white transition-colors"
            >
              {loading ? <Spinner /> : 'Create Account'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-600 mt-4">
          Already have an account?{' '}
          <button onClick={onGoLogin} className="text-indigo-400 hover:text-indigo-300 transition-colors">
            Sign in
          </button>
        </p>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-gray-400 tracking-wide uppercase">{label}</label>
      {children}
    </div>
  )
}

function Spinner() {
  return (
    <span className="flex items-center justify-center gap-2">
      <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
      Creating account…
    </span>
  )
}

function MeridianLogo() {
  return (
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
  )
}
