import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Разработка: `python -m pxg_ocr --server` (порт 8770) и `npm run dev`; /api проксируется в сервер.
// Сборка попадает в pxg_ocr/web/dist, её раздаёт сам сервер, Node пользователю не нужен.
export default defineConfig({
  plugins: [react()],
  resolve: { dedupe: ['react', 'react-dom'] },
  base: '/',
  server: { port: 5177, fs: { allow: ['../..'] }, proxy: { '/api': 'http://127.0.0.1:8770' } },
  build: { outDir: 'dist', emptyOutDir: true },
})
