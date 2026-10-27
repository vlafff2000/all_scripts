import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Разработка: `python -m pxg_finder --server` (порт 8769) и `npm run dev`; /api проксируется в сервер.
// Сборка попадает в pxg_finder/web/dist, её раздаёт сам сервер, Node пользователю не нужен.
export default defineConfig({
  plugins: [react()],
  resolve: { dedupe: ['react', 'react-dom'] },
  base: '/',
  server: { port: 5176, fs: { allow: ['../..'] }, proxy: { '/api': 'http://127.0.0.1:8769' } },
  build: { outDir: 'dist', emptyOutDir: true },
})
