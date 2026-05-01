import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

interface ThemeStore {
  isDark: boolean
  toggle: () => void
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set) => ({
      isDark: true,
      toggle: () => set(s => ({ isDark: !s.isDark })),
    }),
    {
      name: 'meridian-theme',
      storage: createJSONStorage(() => localStorage),
    }
  )
)
