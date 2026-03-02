import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Relative asset paths so the bundle works under any HA Ingress base path
  base: './',
  server: {
    proxy: {
      '/api': 'http://localhost:8099',
    },
  },
})
