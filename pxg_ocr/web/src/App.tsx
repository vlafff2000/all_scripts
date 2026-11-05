import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { openFilePicker } from '../../../pxg_core/web-ui/FilePicker'
import { saveUrlAs } from '../../../pxg_core/web-ui/desktopDownload'
import { renderMarkdown } from './markdown'

interface Plan { mode: string; vram_gb: number; threads: number; why: string }
interface Info {
  engine: string; out: string; hardware: { cores: number; gpu: { name: string; total_gb: number; free_gb: number } | null }
  plans: Record<string, Plan>; tiers: Record<string, string>; ocr_modes: Record<string, string>; modes: Record<string, string>
}
interface Result { md: string; json: string; files: string[] }
interface Item { id: string; src: string; name: string; state: string; error: string; log: string[]; plan: Plan | Record<string, never>; dir: string; elapsed: number; result?: Result }

const STATES: Record<string, string> = { queued: 'в очереди', running: 'идёт', done: 'готово', error: 'ошибка', cancelled: 'отменено' }
const FILTER = 'pdf png jpg jpeg tif tiff jp2 webp bmp docx pptx xlsx'
const api = async <T,>(url: string, body?: unknown): Promise<T> => {
  const r = await fetch(url, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  return (await r.json()) as T
}
const fmt = (s: number) => (s < 60 ? `${Math.round(s)} с` : `${Math.floor(s / 60)} мин ${Math.round(s % 60)} с`)
const fileUrl = (dir: string, name: string, download = false) => `/api/ocr/file?dir=${encodeURIComponent(dir)}&name=${encodeURIComponent(name)}${download ? '&download=1' : ''}`

export default function App() {
  const [info, setInfo] = useState<Info | null>(null)
  const [paths, setPaths] = useState<string[]>([])
  const [tier, setTier] = useState('standard')
  const [mode, setMode] = useState('auto')
  const [ocrMode, setOcrMode] = useState('ocr')
  const [pages, setPages] = useState('all')
  const [items, setItems] = useState<Item[]>([])
  const [sel, setSel] = useState('')
  const [tab, setTab] = useState<'view' | 'md' | 'json'>('view')
  const [text, setText] = useState({ md: '', json: '' })
  const [page, setPage] = useState(0)
  const [err, setErr] = useState('')
  const [askDel, setAskDel] = useState(false)
  const [pageErr, setPageErr] = useState('')
  const running = useRef<Set<string>>(new Set())

  const refresh = useCallback(async () => {
    const h = await api<{ items: Item[] }>('/api/ocr/history')
    setItems((cur) => {
      const live = cur.filter((c) => running.current.has(c.id))
      const ids = new Set(live.map((l) => l.dir))
      return [...live, ...h.items.filter((x) => !ids.has(x.dir))]
    })
  }, [])

  useEffect(() => {
    void api<Info>('/api/ocr/info').then(setInfo)
    void refresh()
    const t = window.setInterval(() => void fetch('/api/ocr/ping').catch(() => undefined), 5000)
    return () => window.clearInterval(t)
  }, [refresh])

  useEffect(() => {
    const t = window.setInterval(async () => {
      for (const id of Array.from(running.current)) {
        const j = await api<Item>(`/api/ocr/job?id=${id}`)
        if (['done', 'error', 'cancelled'].includes(j.state)) { running.current.delete(id); void refresh() }
        setItems((cur) => cur.some((c) => c.id === id) ? cur.map((c) => (c.id === id ? j : c)) : cur)
      }
    }, 1500)
    return () => window.clearInterval(t)
  }, [refresh])

  const cur = useMemo(() => items.find((i) => (i.id || i.dir) === sel), [items, sel])

  useEffect(() => {
    setText({ md: '', json: '' }); setPage(0); setAskDel(false); setPageErr('')
    const r = cur?.result
    if (!cur || cur.state !== 'done' || !r) return
    if (r.md) void fetch(fileUrl(cur.dir, r.md)).then((x) => x.text()).then((md) => setText((t) => ({ ...t, md })))
    if (r.json) void fetch(fileUrl(cur.dir, r.json)).then((x) => x.text()).then((js) => setText((t) => ({ ...t, json: js })))
  }, [cur?.id, cur?.dir, cur?.state]) // eslint-disable-line react-hooks/exhaustive-deps

  const pick = async () => {
    const p = await openFilePicker({ mode: 'files', filter: FILTER, title: 'Выберите сканы и документы' })
    if (p) setPaths(p.split('\n').filter(Boolean))
  }
  const start = async () => {
    setErr('')
    const r = await api<{ jobs?: string[]; error?: string }>('/api/ocr/start', { paths, tier, mode, ocr_mode: ocrMode, pages })
    if (r.error || !r.jobs) { setErr(r.error || 'Не удалось начать'); return }
    for (const id of r.jobs) {
      running.current.add(id)
      const j = await api<Item>(`/api/ocr/job?id=${id}`)
      setItems((c) => [j, ...c])
      setSel(id)
    }
    setPaths([])
  }
  const stop = (id: string) => void api('/api/ocr/job/cancel', { id })
  const del = async () => {
    if (!cur) return
    await api('/api/ocr/delete', { dir: cur.dir }); setSel(''); void refresh()
  }

  const plan = info?.plans[mode]
  const result = cur?.result
  const html = useMemo(() => (cur && text.md ? renderMarkdown(text.md, (rel) => fileUrl(cur.dir, rel.replace(/^\.\//, ''))) : ''), [cur, text.md])
  const isPdf = !!cur && /\.pdf$/i.test(cur.src)

  return (
    <div className="ocr">
      <aside className="ocr-side">
        <h1>Распознавание</h1>
        {info && !info.engine && <p className="ocr-err">Движок распознавания не найден. Положите папку ocr рядом с программой.</p>}
        <button type="button" onClick={pick}>Выбрать файлы…</button>
        {paths.length > 0 && <div className="ocr-files">{paths.map((p) => <div key={p}><span>{p.split(/[\\/]/).pop()}</span></div>)}</div>}
        <label>Качество
          <select value={tier} onChange={(e) => setTier(e.target.value)}>{info && Object.entries(info.tiers).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </label>
        <label>Что считать
          <select value={ocrMode} onChange={(e) => setOcrMode(e.target.value)}>{info && Object.entries(info.ocr_modes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </label>
        <label>Вычисления
          <select value={mode} onChange={(e) => setMode(e.target.value)}>{info && Object.entries(info.modes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </label>
        {plan && <div className={'ocr-plan' + (plan.mode === 'gpu' && plan.why.includes('мало') ? ' warn' : '')}>
          Будет: {plan.mode === 'gpu' ? `видеокарта, лимит ${plan.vram_gb} ГБ` : 'процессор'}, потоков {plan.threads}; {plan.why}.
        </div>}
        <label>Страницы
          <input type="text" value={pages} onChange={(e) => setPages(e.target.value)} placeholder="all, 1-5 или 1-5,8" />
        </label>
        {err && <p className="ocr-err">{err}</p>}
        <button type="button" className="primary" disabled={!paths.length || !info?.engine} onClick={start}>Распознать{paths.length > 1 ? ` (${paths.length})` : ''}</button>
        <h2>Результаты</h2>
        <div className="ocr-hist">
          {items.length === 0 && <span className="muted">Пока ничего нет.</span>}
          {items.map((i) => { const k = i.id || i.dir; return (
            <button type="button" key={k} aria-current={sel === k} onClick={() => setSel(k)}>
              <span>{i.name}</span><small>{STATES[i.state] || i.state}{i.elapsed ? `, ${fmt(i.elapsed)}` : ''}</small>
            </button>) })}
        </div>
      </aside>
      <main className="ocr-main">
        {!cur && <p className="muted">Выберите файлы слева и нажмите «Распознать». Результат появится здесь: страница исходника рядом с распознанным текстом.</p>}
        {cur && <>
          <div className="ocr-bar">
            <h2>{cur.name}</h2><span className="muted">{STATES[cur.state] || cur.state}, {fmt(cur.elapsed)}</span>
            <span className="sp" />
            {(cur.state === 'running' || cur.state === 'queued') && <button type="button" onClick={() => stop(cur.id)}>Остановить</button>}
            {cur.state === 'done' && result && <>
              {result.md && <button type="button" onClick={() => void saveUrlAs(fileUrl(cur.dir, result.md, true), cur.name.replace(/\.[^.]+$/, '') + '.md')}>Скачать markdown</button>}
              {result.json && <button type="button" onClick={() => void saveUrlAs(fileUrl(cur.dir, result.json, true), cur.name.replace(/\.[^.]+$/, '') + '.json')}>Скачать JSON</button>}
              {askDel ? <button type="button" onClick={del}>Точно удалить результат?</button> : <button type="button" onClick={() => setAskDel(true)}>Удалить</button>}
            </>}
          </div>
          {cur.error && <p className="ocr-err">{cur.error}</p>}
          {cur.state !== 'done' && <div className="ocr-log">{cur.log.join('\n') || 'Ожидание…'}</div>}
          {cur.state === 'done' && <>
            <div className="ocr-tabs" role="tablist">
              {([['view', 'Просмотр'], ['md', 'Markdown'], ['json', 'JSON']] as const).map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>)}
            </div>
            <div className="ocr-split" style={tab === 'view' && isPdf || tab !== 'view' ? undefined : { gridTemplateColumns: '1fr' }}>
              <div className="ocr-page">
                <div className="ocr-bar">
                  <button type="button" disabled={page <= 0} onClick={() => { setPageErr(''); setPage(page - 1) }}>←</button>
                  <span>Страница {page + 1}</span>
                  <button type="button" onClick={() => { setPageErr(''); setPage(page + 1) }}>→</button>
                </div>
                {pageErr ? <p className="ocr-err">{pageErr}</p> : <img src={`/api/ocr/page?path=${encodeURIComponent(cur.src)}&n=${page}`} alt="Исходная страница" onError={() => {
                  void fetch(`/api/ocr/page?path=${encodeURIComponent(cur.src)}&n=${page}`).then((r) => r.json()).then((j: { error?: string }) => setPageErr(j.error || 'Страница не показана')).catch(() => setPageErr('Страница не показана'))
                }} />}
              </div>
              <div className="ocr-view">
                {tab === 'view' && <div dangerouslySetInnerHTML={{ __html: html }} />}
                {tab === 'md' && <pre>{text.md}</pre>}
                {tab === 'json' && <pre>{text.json ? JSON.stringify(safeJson(text.json), null, 1) : ''}</pre>}
              </div>
            </div>
          </>}
        </>}
      </main>
    </div>
  )
}

function safeJson(s: string): unknown { try { return JSON.parse(s) } catch { return s } }
