import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Разработка: `python -m pxg_base --server` (порт 8766) и `npm run dev`; /api проксируется в сервер.
// Сборка попадает в pxg_base/web/dist, её раздаёт сам сервер, Node пользователю не нужен.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: { port: 5174, proxy: { '/api': 'http://127.0.0.1:8766' } },
  build: { outDir: 'dist', emptyOutDir: true },
})
