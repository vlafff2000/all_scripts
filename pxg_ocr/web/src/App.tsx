import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { openFilePicker } from '../../../pxg_core/web-ui/FilePicker'
import { saveUrlAs } from '../../../pxg_core/web-ui/desktopDownload'
import { renderMarkdown } from './markdown'
import { CollapsibleGroup } from '../../../pxg_core/web-ui/CollapsibleGroup'
import { Tables } from '../../../pxg_core/web-ui/table/Tables'
import { tableOf } from '../../../pxg_core/web-ui/table/tableBuild'
import type { Cell } from '../../../pxg_core/web-ui/table/tableTypes'

interface Plan { mode: string; vram_gb: number; threads: number; why: string }
interface Info {
  engine: string; out: string; hardware: { cores: number; gpu: { name: string; total_gb: number; free_gb: number } | null }
  plans: Record<string, Plan>; tiers: Record<string, string>; ocr_modes: Record<string, string>; modes: Record<string, string>
}
interface Result { md: string; json: string; files: string[] }
interface Route { path: string; name: string; route: string; auto: string; reason: string; manual: boolean }
interface Item { session?: string; id: string; src: string; name: string; state: string; error: string; log: string[]; plan: Plan | Record<string, never>; dir: string; elapsed: number; result?: Result }

const STATES: Record<string, string> = { queued: 'в очереди', running: 'идёт', done: 'готово', error: 'ошибка', cancelled: 'отменено' }
const FILTER = 'pdf png jpg jpeg tif tiff jp2 webp bmp doc docx rtf odt pptx xlsx'
const api = async <T,>(url: string, body?: unknown): Promise<T> => {
  const r = await fetch(url, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  return (await r.json()) as T
}
// Метка сессии: ГГГГММДД_ЧЧММСС — запуск «Распознать»; ГГГГММДД — записи до учёта сессий (одна на день)
const sessionTitle = (k: string) => {
  const m = /^(\d{4})(\d{2})(\d{2})(?:_(\d{2})(\d{2}))?/.exec(k)
  if (!m) return 'Раньше'
  const d = `${m[3]}.${m[2]}.${m[1]}`
  return m[4] ? `Сессия ${d} ${m[4]}:${m[5]}` : `${d} (до учёта сессий)`
}
const fmt = (s: number) => (s < 60 ? `${Math.round(s)} с` : `${Math.floor(s / 60)} мин ${Math.round(s % 60)} с`)
const fileUrl = (dir: string, name: string, download = false) => `/api/ocr/file?dir=${encodeURIComponent(dir)}&name=${encodeURIComponent(name)}${download ? '&download=1' : ''}`

export default function App() {
  const [info, setInfo] = useState<Info | null>(null)
  const [paths, setPaths] = useState<string[]>([])
  const [routes, setRoutes] = useState<Route[]>([])
  const [over, setOver] = useState<Record<string, string>>({})
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
  const [db, setDb] = useState<{ kind: string; sheets: { name: string; columns: string[]; rows: Cell[][] }[] } | null>(null)
  const [dbErr, setDbErr] = useState('')
  const [svod, setSvod] = useState('')
  const [gpuInfo, setGpuInfo] = useState('')
  const [allDb, setAllDb] = useState<{ file: string; dir: string; info: string; sheets: { name: string; columns: string[]; rows: Cell[][] }[] } | null>(null)
  const [opened, setOpened] = useState<Record<string, boolean>>({})  // ручной выбор: развёрнута / свёрнута сессия
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

  const sessions = useMemo(() => {
    const m = new Map<string, Item[]>()
    for (const i of items) { const k = i.session || 'earlier'; m.set(k, [...(m.get(k) || []), i]) }
    return Array.from(m, ([key, its]) => ({ key, items: its })).sort((a, b) => (a.key < b.key ? 1 : -1))
  }, [items])

  const cur = useMemo(() => items.find((i) => (i.id || i.dir) === sel), [items, sel])

  useEffect(() => {
    setText({ md: '', json: '' }); setPage(0); setAskDel(false); setPageErr(''); setDb(null); setDbErr('')
    const r = cur?.result
    if (!cur || cur.state !== 'done' || !r) return
    if (r.md) void fetch(fileUrl(cur.dir, r.md)).then((x) => x.text()).then((md) => setText((t) => ({ ...t, md })))
    if (r.json) void fetch(fileUrl(cur.dir, r.json)).then((x) => x.text()).then((js) => setText((t) => ({ ...t, json: js })))
  }, [cur?.id, cur?.dir, cur?.state]) // eslint-disable-line react-hooks/exhaustive-deps

  const pick = async () => {
    const p = await openFilePicker({ mode: 'files', filter: FILTER, title: 'Выберите сканы и документы' })
    if (p) { setPaths(p.split('\n').filter(Boolean)); setOver({}) }
  }
  useEffect(() => {
    if (!paths.length) { setRoutes([]); return }
    void api<{ items: Route[] }>('/api/ocr/route', { paths, overrides: over }).then((r) => setRoutes(r.items))
  }, [paths, over])
  const ocrPaths = routes.filter((r) => r.route === 'ocr').map((r) => r.path)
  const start = async () => {
    setErr('')
    const r = await api<{ jobs?: string[]; error?: string }>('/api/ocr/start', { paths: ocrPaths, tier, mode, ocr_mode: ocrMode, pages })
    if (r.error || !r.jobs) { setErr(r.error || 'Не удалось начать'); return }
    for (const id of r.jobs) {
      running.current.add(id)
      const j = await api<Item>(`/api/ocr/job?id=${id}`)
      setItems((c) => [j, ...c])
      setSel(id)
    }
    setPaths([]); setOver({})
  }
  const stop = (id: string) => void api('/api/ocr/job/cancel', { id })
  const makeDb = async () => {
    if (!cur) return
    setDbErr('')
    const r = await api<{ kind?: string; sheets?: { name: string; columns: string[]; rows: Cell[][] }[]; error?: string }>('/api/ocr/db', { dir: cur.dir })
    if (r.error || !r.sheets) { setDbErr(r.error || 'Не удалось собрать БД'); return }
    setDb({ kind: r.kind || '', sheets: r.sheets })
  }
  const exportFile = async (kind: 'docx' | 'tables') => {
    if (!cur) return
    setDbErr('')
    const r = await api<{ file?: string; error?: string }>(`/api/ocr/${kind}`, { dir: cur.dir })
    if (r.error || !r.file) { setDbErr(r.error || 'Не удалось выгрузить'); return }
    await saveUrlAs(fileUrl(cur.dir, r.file, true), kind === 'docx' ? r.file : cur.name.replace(/\.[^.]+$/, '') + '_таблицы.xlsx')
  }
  const collect = async (folder: boolean) => {
    setErr(''); setSvod('')
    let folders: string[] = []
    if (folder) {
      const p = await openFilePicker({ mode: 'folder', title: 'Папка с файлами OCR (*.ocr.md)' })
      if (!p) return
      folders = p.split('\n').filter(Boolean)
    }
    const r = await api<{ dir?: string; file?: string; files?: number; sheets?: { name: string; tables: number; rows: number }[]; error?: string }>('/api/ocr/collect', folder ? { folders } : { scope: 'all' })
    if (r.error || !r.file || !r.dir) { setErr(r.error || 'Сводка не собрана'); return }
    setSvod(`Файлов: ${r.files}. Листов: ${r.sheets?.length}: ` + (r.sheets || []).map((x) => `${x.name} (${x.rows})`).join(', '))
    await saveUrlAs(fileUrl(r.dir, r.file, true), r.file)
  }
  const buildAll = async (folder: boolean) => {
    setErr(''); setAllDb(null)
    let folders: string[] = []
    if (folder) {
      const p = await openFilePicker({ mode: 'folder', title: 'Папка с распознанными файлами (*.ocr.md)' })
      if (!p) return
      folders = p.split('\n').filter(Boolean)
    }
    const r = await api<{ dir?: string; file?: string; files?: number; recognised?: number; sheets?: { name: string; columns: string[]; rows: Cell[][] }[]; error?: string }>('/api/ocr/db-all', folder ? { folders, scope: 'folders' } : { scope: 'all' })
    if (r.error || !r.file || !r.sheets || !r.dir) { setErr(r.error || 'БД не собрана'); return }
    setAllDb({ file: r.file, dir: r.dir, info: `Файлов: ${r.files}, вид документа определён у ${r.recognised}. Остальные перечислены на листе «Файлы» с причиной.`, sheets: r.sheets })
  }
  const checkGpu = async () => {
    setGpuInfo('Проверяю…')
    const r = await api<{ lines: string[] }>('/api/ocr/gpu')
    setGpuInfo(r.lines.join('\n'))
  }
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
        {routes.length > 0 && <div className="ocr-files">{routes.map((r) => (
          <div key={r.path} title={r.reason}>
            <span>{r.name}</span>
            <select value={r.route} onChange={(e) => setOver((o) => ({ ...o, [r.path]: e.target.value }))} aria-label={`Путь для ${r.name}`}>
              <option value="script">Скриптом{r.auto === 'script' ? ' (авто)' : ''}</option>
              <option value="ocr">OCR{r.auto === 'ocr' ? ' (авто)' : ''}</option>
            </select>
          </div>))}
          <small className="muted">Word и PDF с текстом читают сборщики БД напрямую, OCR для них не нужен. Путь можно сменить вручную.</small>
        </div>}
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
        <button type="button" onClick={() => void checkGpu()}>Проверить видеокарту</button>
        {gpuInfo && <pre className="ocr-log" style={{ maxHeight: 260, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{gpuInfo}</pre>}
        <label>Страницы
          <input type="text" value={pages} onChange={(e) => setPages(e.target.value)} placeholder="all, 1-5 или 1-5,8" />
        </label>
        {err && <p className="ocr-err">{err}</p>}
        <button type="button" className="primary" disabled={!ocrPaths.length || !info?.engine} onClick={start}>Распознать{ocrPaths.length > 1 ? ` (${ocrPaths.length})` : ''}</button>
        <h2>Сводка таблиц</h2>
        <button type="button" disabled={!items.some((i) => i.state === 'done')} onClick={() => void collect(false)}>Из всех результатов (xlsx)</button>
        <button type="button" onClick={() => void collect(true)}>Из папки с OCR…</button>
        {svod && <small className="muted">{svod}. Один тип таблицы — один лист, в каждой строке скважина и дата.</small>}
        <h2>БД из распознанного</h2>
        <button type="button" disabled={!items.some((i) => i.state === 'done')} onClick={() => void buildAll(false)}>Собрать БД из всех результатов</button>
        <button type="button" onClick={() => void buildAll(true)}>Собрать БД из папки…</button>
        <small className="muted">Акты КРС, заключения ГИС, отчёты ГДИ и месячные отчёты ПХГ из многих файлов в один xlsx. Кнопка «БД из этого файла» над результатом собирает только открытый файл.</small>
        <h2>Результаты</h2>
        <div className="ocr-hist">
          {items.length === 0 && <span className="muted">Пока ничего нет.</span>}
          {sessions.map((g, gi) => {
            const hasCur = g.items.some((i) => (i.id || i.dir) === sel) || g.items.some((i) => i.state === 'running' || i.state === 'queued')
            const open = opened[g.key] ?? (gi === 0 || hasCur)
            const done = g.items.filter((i) => i.state === 'done').length
            return (
              <CollapsibleGroup key={g.key} title={sessionTitle(g.key)} count={g.items.length} hint={`готово ${done}`} open={open}
                onToggle={(o) => setOpened((c) => ({ ...c, [g.key]: o }))}>
                {g.items.map((i) => { const k = i.id || i.dir; return (
                  <button type="button" key={k} aria-current={sel === k} onClick={() => setSel(k)}>
                    <span>{i.name}</span><small>{STATES[i.state] || i.state}{i.elapsed ? `, ${fmt(i.elapsed)}` : ''}</small>
                  </button>) })}
              </CollapsibleGroup>)
          })}
        </div>
      </aside>
      <main className="ocr-main">
        {allDb && <div className="ocr-db">
          <div className="ocr-bar"><h2>БД из многих файлов</h2><span className="muted">{allDb.info}</span><span className="sp" />
            <button type="button" onClick={() => void saveUrlAs(fileUrl(allDb.dir, allDb.file, true), allDb.file)}>Скачать xlsx</button>
            <button type="button" onClick={() => setAllDb(null)}>Закрыть</button></div>
          <Tables scope="ocr-db-all" tables={allDb.sheets.map((sh, i) => tableOf('dball' + i, sh.name, sh.columns, sh.rows, 'Собрано из всех выбранных файлов. Столбец «Проверка» говорит, чему можно доверять; решает инженер.'))} />
        </div>}
        {!cur && <p className="muted">Выберите файлы слева и нажмите «Распознать». Результат появится здесь: страница исходника рядом с распознанным текстом.</p>}
        {cur && <>
          <div className="ocr-bar">
            <h2>{cur.name}</h2><span className="muted">{STATES[cur.state] || cur.state}, {fmt(cur.elapsed)}</span>
            <span className="sp" />
            {(cur.state === 'running' || cur.state === 'queued') && <button type="button" onClick={() => stop(cur.id)}>Остановить</button>}
            {cur.state === 'done' && result && <>
              {result.md && <button type="button" onClick={() => void saveUrlAs(fileUrl(cur.dir, result.md, true), cur.name.replace(/\.[^.]+$/, '') + '.md')}>Скачать markdown</button>}
              {result.json && <button type="button" onClick={() => void saveUrlAs(fileUrl(cur.dir, result.json, true), cur.name.replace(/\.[^.]+$/, '') + '.json')}>Скачать JSON</button>}
              <button type="button" onClick={() => void exportFile('docx')}>Скачать Word</button>
              <button type="button" onClick={() => void exportFile('tables')}>Таблицы в xlsx</button>
              <button type="button" onClick={makeDb}>БД из этого файла</button>
              {db && <button type="button" onClick={() => void saveUrlAs(fileUrl(cur.dir, 'db.xlsx', true), cur.name.replace(/\.[^.]+$/, '') + '_БД.xlsx')}>Скачать БД (xlsx)</button>}
              {askDel ? <button type="button" onClick={del}>Точно удалить результат?</button> : <button type="button" onClick={() => setAskDel(true)}>Удалить</button>}
            </>}
          </div>
          {cur.error && <p className="ocr-err">{cur.error}</p>}
          {dbErr && <p className="ocr-err">{dbErr}</p>}
          {db && <div className="ocr-db"><Tables scope="ocr-db" tables={db.sheets.map((sh, i) => tableOf('db' + i, sh.name, sh.columns, sh.rows, 'Собрано программой из распознанного текста. Столбец «Проверка» говорит, чему можно доверять; решает инженер.'))} /></div>}
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
