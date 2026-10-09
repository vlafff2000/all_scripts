import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Разработка: `python -m gsp_maps --server` (порт 8767) и `npm run dev`; /api проксируется в сервер.
// Сборка попадает в gsp_maps/web/dist, её раздаёт сам сервер, Node пользователю не нужен.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: { port: 5175, fs: { allow: ['../..'] }, proxy: { '/api': 'http://127.0.0.1:8767' } },
  build: { outDir: 'dist', emptyOutDir: true },
})
