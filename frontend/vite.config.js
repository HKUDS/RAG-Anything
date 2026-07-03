import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server timeout plugin: Node HTTP server defaults to 300s requestTimeout.
// Large uploads (video 200MB+ at 10Mbps ≈ 160s) easily fit, but any network
// slowdown can push past 300s.  Align with nginx proxy_read_timeout = 600s.
function uploadTimeoutPlugin() {
  return {
    name: 'upload-timeout-plugin',
    configureServer(server) {
      if (server.httpServer) {
        server.httpServer.requestTimeout = 600_000 // 600s (Node 17+)
        server.httpServer.headersTimeout = 600_000
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), uploadTimeoutPlugin()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        // http-proxy inactivity timeout (default 0 = disabled); set explicitly
        timeout: 600_000,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react-dom/') || id.includes('node_modules/react/') || id.includes('node_modules/scheduler/')) {
            return 'react-vendor'
          }
          if (id.includes('node_modules/react-router') || id.includes('node_modules/@remix-run')) {
            return 'router-vendor'
          }
          if (id.includes('node_modules/framer-motion')) {
            return 'motion-vendor'
          }
          if (id.includes('node_modules/lucide-react')) {
            return 'icons-vendor'
          }
          if (id.includes('node_modules/recharts')) {
            return 'charts-vendor'
          }
          if (id.includes('node_modules/lodash')) {
            return 'lodash-vendor'
          }
        }
      }
    }
  }
})
