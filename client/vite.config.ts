import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Same-origin proxy to the local `eve dev` server (default port 2000),
      // so useEveAgent() can talk to /eve/v1/* without a `host` override or
      // touching agent/channels/eve.ts CORS/auth config.
      "/eve": {
        target: process.env.EVE_DEV_URL ?? "http://localhost:2000",
        changeOrigin: true,
      },
    },
  },
})
