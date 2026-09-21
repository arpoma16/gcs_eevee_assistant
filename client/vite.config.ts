import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Same-origin proxy hacia el server de eve, para que useEveAgent() hable
      // con /eve/** sin `host` ni tocar el CORS de agent/channels/eve.ts.
      //
      // El prefijo `/eve` cubre los dos modos de dev, porque las dos formas de
      // ruta empiezan igual:
      //   `eve dev --agent <name>`  -> /eve/v1/*            (:2000 por defecto)
      //   `vercel dev --local`      -> /eve/<name>/v1/*      (el puerto que informe)
      // Lo que cambia es el destino y, en el segundo caso, el `agent` que
      // useEveAgent necesita para armar el prefijo. Ver los scripts del
      // package.json de este paquete.
      "/eve": {
        target: process.env.EVE_DEV_URL ?? "http://localhost:2000",
        changeOrigin: true,
      },
    },
  },
})
