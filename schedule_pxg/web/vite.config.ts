import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const modules = (name: string) => decodeURIComponent(new URL('./node_modules/' + name, import.meta.url).pathname)

// Разработка: `python -m schedule_pxg --server` (порт 8768) и `npm run dev`; /api проксируется в сервер.
// Сборка попадает в schedule_pxg/web/dist, её раздаёт сам сервер, Node пользователю не нужен.
export default defineConfig({
  plugins: [react()],
  // общие компоненты из pxg_core/web-ui берут react из node_modules приложения
  resolve: {
    dedupe: ['react', 'react-dom'],
    // графики из pxg_core/web-ui/chart берут echarts из node_modules приложения
    alias: [{ find: /^echarts(\/.*)?$/, replacement: modules('echarts') + '$1' }],
  },
  base: '/',
  server: { port: 5176, fs: { allow: ['../..'] }, proxy: { '/api': 'http://127.0.0.1:8768' } },
  build: { outDir: 'dist', emptyOutDir: true },
})
