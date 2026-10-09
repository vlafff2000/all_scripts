import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Разработка: `python -m schedule_pxg --server` (порт 8768) и `npm run dev`; /api проксируется в сервер.
// Сборка попадает в schedule_pxg/web/dist, её раздаёт сам сервер, Node пользователю не нужен.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: { port: 5176, fs: { allow: ['../..'] }, proxy: { '/api': 'http://127.0.0.1:8768' } },
  build: { outDir: 'dist', emptyOutDir: true },
})
