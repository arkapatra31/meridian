import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/auth':       { target: 'http://localhost:8000', changeOrigin: true },
      '/graph':      { target: 'http://localhost:8000', changeOrigin: true },
      '/repos':      { target: 'http://localhost:8000', changeOrigin: true },
      '/playground': { target: 'ws://localhost:8000',   changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: '../api/static',
    emptyOutDir: true,
  },
})
