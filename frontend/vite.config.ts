import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The browser uses relative URLs. BACKEND_URL changes only the server-side proxy.
const target = process.env.CODING_AGENT_BACKEND_URL || 'http://127.0.0.1:8000'
const proxy = { '/api': { target, changeOrigin: true }, '/health': { target, changeOrigin: true } }

export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 5173, strictPort: true, proxy },
})
