import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget = process.env.PLANNING_POKER_API_URL ?? 'http://127.0.0.1:8001'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': apiTarget,
      '/ws': {
        target: apiTarget.replace(/^http/, 'ws'),
        ws: true,
      },
    },
  },
})
