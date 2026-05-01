import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

interface AuthUser {
  user_id: string
  email: string
  display_name: string
}

interface AuthStore {
  token: string | null
  user: AuthUser | null
  loading: boolean
  error: string | null

  login: (email: string, password: string) => Promise<void>
  register: (email: string, display_name: string, password: string, github_username?: string) => Promise<void>
  logout: () => void
  clearError: () => void
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set) => ({
      token: null,
      user:  null,
      loading: false,
      error: null,

      login: async (email, password) => {
        set({ loading: true, error: null })
        try {
          const res = await fetch('/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
          })
          const body = await res.json()
          if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`)
          const user: AuthUser = { user_id: body.user_id, email: body.email, display_name: body.display_name }
          set({ token: body.access_token, user, loading: false })
        } catch (err) {
          set({ error: (err as Error).message, loading: false })
        }
      },

      register: async (email, display_name, password, github_username) => {
        set({ loading: true, error: null })
        try {
          const res = await fetch('/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, display_name, password, github_username: github_username ?? null }),
          })
          const body = await res.json()
          if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`)
          const loginRes = await fetch('/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
          })
          const loginBody = await loginRes.json()
          if (!loginRes.ok) throw new Error(loginBody.detail ?? `HTTP ${loginRes.status}`)
          const user: AuthUser = { user_id: loginBody.user_id, email: loginBody.email, display_name: loginBody.display_name }
          set({ token: loginBody.access_token, user, loading: false })
        } catch (err) {
          set({ error: (err as Error).message, loading: false })
        }
      },

      logout: () => set({ token: null, user: null, error: null }),

      clearError: () => set({ error: null }),
    }),
    {
      name: 'meridian-auth',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({ token: state.token, user: state.user }),
    },
  ),
)
