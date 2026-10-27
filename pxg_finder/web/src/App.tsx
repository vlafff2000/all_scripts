import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { baseName, copyText, dirName, getJson, op, post, watchJob } from './api'
import type { Favs, IndexRoot, Place } from './api'
import Pane from './Pane'
import Sidebar from './Sidebar'
import Preview from './Preview'
import SearchBar from './SearchBar'
import Palette from './Palette'
import type { Cmd } from './Palette'
import { Confirm, Conflict, DupsDialog, Help, IndexDialog, MetaDialog, Prompt, TrashDialog } from './Dialogs'
import { newTab } from './types'
import type { AppState, MetaMap, PaneApi, Row, SearchSpec, Tab } from './types'

type Dlg =
  | { k: 'prompt'; title: string; label: string; value: string; ok: string; done: (v: string) => void }
  | { k: 'confirm'; title: string; text: string; ok: string; danger?: boolean; list?: string[]; done: () => void }
  | { k: 'conflict'; names: string[]; done: (c: 'skip' | 'overwrite' | 'rename') => void }
  | { k: 'meta'; path: string }
  | { k: 'trash' } | { k: 'index' } | { k: 'help' } | { k: 'dups'; folder: string }
interface MenuItem { label: string; run?: () => void; danger?: boolean; sep?: boolean; disabled?: boolean }
interface Toast { id: number; text: string; kind: 'info' | 'bad' | 'job'; cancel?: () => void }

const DEFAULT: AppState = { panes: [{ tabs: [], active: 0 }, { tabs: [], active: 0 }], dual: false, activePane: 0, preview: true, hidden: false, sideW: 250, previewW: 360, theme: 'system', recent: [] }
const ACT = <T,>(a: T[], i: number): T | undefined => a[Math.max(0, Math.min(a.length - 1, i))]
const lower = (p: string) => p.replace(/\//g, '\\').toLowerCase().replace(/\\+$/, '')

export default function App() {
  const [st, setSt] = useState<AppState | null>(null)
  const [places, setPlaces] = useState<Place[]>([])
  const [favs, setFavs] = useState<Favs>({ favorites: [], frequent: [] })
  const [meta, setMeta] = useState<MetaMap>({})
  const [colors, setColors] = useState<string[]>([])
  const [roots, setRoots] = useState<IndexRoot[]>([])
  const [sel, setSel] = useState<Row[][]>([[], []])
  const [nonce, setNonce] = useState(0)
  const [dlg, setDlg] = useState<Dlg | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null)
  const [palette, setPalette] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const paneApi = [useRef<PaneApi | null>(null), useRef<PaneApi | null>(null)]
  const searchInput = useRef<HTMLInputElement>(null)
  const lastDest = useRef('')
  const toastId = useRef(0)
  const saveTimer = useRef(0)
  const stRef = useRef<AppState | null>(null)
  stRef.current = st

  // ---------- старт ----------
  useEffect(() => {
    void (async () => {
      const [state, last, info, m] = await Promise.all([
        getJson<{ state: Partial<AppState> }>('/api/finder/state').catch(() => ({ state: {} as Partial<AppState> })),
        getJson<{ dir: string }>('/api/fs/last').catch(() => ({ dir: '' })),
        getJson<{ home: string; start: string; colors: string[] }>('/api/finder/info').catch(() => ({ home: '', start: '', colors: [] })),
        getJson<{ meta: MetaMap }>('/api/finder/meta').catch(() => ({ meta: {} })),
      ])
      const start = last.dir || info.home || '/'
      const s: AppState = { ...DEFAULT, ...state.state }
      s.panes = [0, 1].map(i => {
        const ps = state.state.panes?.[i]
        const tabs = (ps?.tabs ?? []).map((t: Tab) => ({ ...newTab(t.path), sort: t.sort || 'name', desc: !!t.desc }))
        return tabs.length ? { tabs, active: Math.min(ps?.active ?? 0, tabs.length - 1) } : { tabs: [newTab(start)], active: 0 }
      })
      if (info.start) { // запуск с папкой: открываем её в новой вкладке левой панели
        const t = newTab(info.start)
        s.panes[0] = { tabs: [...s.panes[0].tabs, t], active: s.panes[0].tabs.length }
        s.activePane = 0
      }
      setColors(info.colors); setMeta(m.meta); setSt(s)
    })()
    void reloadFavs(); void reloadPlaces(); void reloadRoots()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const reloadFavs = useCallback(() => getJson<Favs>('/api/fs/favorites').then(setFavs).catch(() => undefined), [])
  const reloadPlaces = useCallback(() => getJson<{ places: Place[] }>('/api/fs/places').then(r => setPlaces(r.places)).catch(() => undefined), [])
  const reloadRoots = useCallback(() => getJson<{ roots: IndexRoot[] }>('/api/finder/index').then(r => setRoots(r.roots)).catch(() => undefined), [])
  const reloadMeta = useCallback(() => getJson<{ meta: MetaMap }>('/api/finder/meta').then(r => setMeta(r.meta)).catch(() => undefined), [])

  // сигнал серверу, что страница открыта (в режиме браузера закрытие вкладки завершает сервер)
  useEffect(() => {
    const t = window.setInterval(() => void fetch('/api/finder/ping').catch(() => undefined), 5000)
    void fetch('/api/finder/ping').catch(() => undefined)
    return () => window.clearInterval(t)
  }, [])

  // ---------- сохранение вида ----------
  useEffect(() => {
    if (!st) return
    document.documentElement.dataset.theme = st.theme === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : st.theme
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      void post('/api/finder/state', { ...st, panes: st.panes.map(p => ({ active: p.active, tabs: p.tabs.map(t => ({ path: t.path, sort: t.sort, desc: t.desc })) })) })
    }, 700)
  }, [st])

  const note = useCallback((text: string, kind: Toast['kind'] = 'info') => {
    const id = ++toastId.current
    setToasts(t => [...t, { id, text, kind }])
    window.setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), kind === 'bad' ? 7000 : 3500)
  }, [])

  // ---------- вкладки и переходы ----------
  const update = (f: (s: AppState) => AppState) => setSt(s => (s ? f(s) : s))
  const patchTab = (pi: number, ti: number, p: Partial<Tab>) => update(s => ({ ...s, panes: s.panes.map((pn, i) => i !== pi ? pn : { ...pn, tabs: pn.tabs.map((t, j) => j === ti ? { ...t, ...p } : t) }) }))
  const activeTab = (pi: number) => (st ? ACT(st.panes[pi].tabs, st.panes[pi].active) : undefined)
  const navigate = (pi: number, ti: number, path: string) => update(s => ({
    ...s, panes: s.panes.map((pn, i) => i !== pi ? pn : { ...pn, tabs: pn.tabs.map((t, j) => j !== ti ? t : (lower(t.path) === lower(path) && !t.search ? t : { ...t, path, search: undefined, back: [...t.back, t.path].slice(-50), fwd: [] })) }),
  }))
  const goBack = (pi: number, ti: number) => update(s => ({
    ...s, panes: s.panes.map((pn, i) => i !== pi ? pn : { ...pn, tabs: pn.tabs.map((t, j) => {
      if (j !== ti) return t
      if (t.search) return { ...t, search: undefined }
      const prev = t.back[t.back.length - 1]
      return prev ? { ...t, path: prev, back: t.back.slice(0, -1), fwd: [...t.fwd, t.path] } : t
    }) }),
  }))
  const goFwd = (pi: number, ti: number) => update(s => ({
    ...s, panes: s.panes.map((pn, i) => i !== pi ? pn : { ...pn, tabs: pn.tabs.map((t, j) => {
      const next = j === ti ? t.fwd[t.fwd.length - 1] : ''
      return next ? { ...t, path: next, fwd: t.fwd.slice(0, -1), back: [...t.back, t.path], search: undefined } : t
    }) }),
  }))
  const go = (path: string) => { if (st) navigate(st.activePane, st.panes[st.activePane].active, path) }
  const addTab = (pi: number, path?: string) => update(s => ({ ...s, panes: s.panes.map((pn, i) => i !== pi ? pn : { tabs: [...pn.tabs, newTab(path || ACT(pn.tabs, pn.active)?.path || '/')], active: pn.tabs.length }) }))
  const closeTab = (pi: number, ti: number) => update(s => ({
    ...s, panes: s.panes.map((pn, i) => i !== pi || pn.tabs.length < 2 ? pn : { tabs: pn.tabs.filter((_, j) => j !== ti), active: Math.max(0, ti <= pn.active ? pn.active - (ti < pn.active || ti === pn.tabs.length - 1 ? 1 : 0) : pn.active) }),
  }))
  const selectTab = (pi: number, ti: number) => update(s => ({ ...s, activePane: pi, panes: s.panes.map((pn, i) => i === pi ? { ...pn, active: ti } : pn) }))

  const ap = st?.activePane ?? 0
  const folderOf = (pi: number) => paneApi[pi].current?.focusedFolder() || activeTab(pi)?.path || ''
  const selection = () => paneApi[ap].current?.selection() ?? []
  const refreshAll = () => setNonce(n => n + 1)

  const indexed = useCallback((folder: string) => {
    const f = lower(folder)
    return roots.some(r => r.count > 0 && (f === lower(r.root) || f.startsWith(lower(r.root) + '\\')))
  }, [roots])

  const runSearch = (spec: SearchSpec) => { if (st) patchTab(st.activePane, st.panes[st.activePane].active, { search: spec, runId: Date.now() }) }
  const clearSearch = () => { if (st) patchTab(st.activePane, st.panes[st.activePane].active, { search: undefined }) }

  // ---------- файловые операции ----------
  const addJobToast = (label: string, jobId: string, after: () => void) => {
    const id = ++toastId.current
    const cancel = () => void post('/api/finder/job/cancel', { id: jobId })
    setToasts(t => [...t, { id, text: label + '…', kind: 'job', cancel }])
    void watchJob(jobId, s => {
      const done = s.info.done || 0, total = s.info.total || 0
      setToasts(t => t.map(x => x.id === id ? { ...x, text: `${label}: ${done}/${total}${s.info.bytes ? ', ' + (s.info.bytes / 1048576).toFixed(0) + ' МБ' : ''}…` } : x))
    }).then(s => {
      const errs = s.items.filter((i: any) => i.error)
      setToasts(t => t.filter(x => x.id !== id))
      if (s.error) note(`${label}: ${s.error}`, 'bad')
      else if (errs.length) note(`${label}: ошибок ${errs.length} — ${errs[0].error}`, 'bad')
      else note(`${label}: готово${s.cancelled ? ' (остановлено)' : ''}`)
      after()
    })
  }
  const transfer = async (kind: 'copy' | 'move', paths: string[], dest: string, conflict = 'ask', confirm = false) => {
    if (!paths.length || !dest) return
    lastDest.current = dest
    const r = await op({ op: kind, paths, dest, conflict, confirm })
    if (r.error) { note(r.error, 'bad'); return }
    if (r.conflicts && !r.needConfirm) {
      setDlg({ k: 'conflict', names: r.conflicts, done: c => {
        setDlg(null)
        if (c === 'overwrite') setDlg({ k: 'confirm', title: 'Заменить файлы', text: `Файлы в «${dest}» будут перезаписаны без возможности вернуть.`, list: r.conflicts, ok: 'Заменить', danger: true, done: () => { setDlg(null); void transfer(kind, paths, dest, 'overwrite', true) } })
        else void transfer(kind, paths, dest, c)
      } })
      return
    }
    if (r.needConfirm) { setDlg({ k: 'confirm', title: 'Заменить файлы', text: 'Будут перезаписаны файлы в папке назначения.', list: r.conflicts, ok: 'Заменить', danger: true, done: () => { setDlg(null); void transfer(kind, paths, dest, 'overwrite', true) } }); return }
    if (r.job) addJobToast(kind === 'copy' ? 'Копирование' : 'Перенос', r.job, refreshAll)
  }
  const toOther = (kind: 'copy' | 'move') => {
    const rows = selection()
    if (!rows.length) { note('Сначала выберите файлы.'); return }
    const paths = rows.map(r => r.path)
    const other = st && st.dual ? folderOf(1 - ap) : ''
    if (other && lower(other) !== lower(folderOf(ap))) { void transfer(kind, paths, other); return }
    setDlg({ k: 'prompt', title: kind === 'copy' ? 'Копировать в…' : 'Переместить в…', label: 'Папка назначения (или включите две панели: Ctrl+D)', value: lastDest.current || folderOf(ap), ok: kind === 'copy' ? 'Копировать' : 'Переместить', done: v => { setDlg(null); void transfer(kind, paths, v) } })
  }
  const trashSel = () => {
    const rows = selection()
    if (!rows.length) return
    setDlg({ k: 'confirm', title: 'Удалить в корзину', text: `Переместить в корзину программы: ${rows.length}. Их можно вернуть из корзины.`, list: rows.map(r => r.name), ok: 'В корзину', danger: true, done: async () => {
      setDlg(null)
      const r = await op({ op: 'trash', paths: rows.map(x => x.path), confirm: true })
      if (r.error) note(r.error, 'bad'); else if (r.errors?.length) note(r.errors[0].error, 'bad'); else note(`В корзине: ${r.trashed.length}`)
      refreshAll()
    } })
  }
  const renameSel = () => {
    const rows = selection()
    if (rows.length !== 1) { note('Для переименования выберите один элемент.'); return }
    const r = rows[0]
    setDlg({ k: 'prompt', title: 'Переименовать', label: 'Новое имя', value: r.name, ok: 'Переименовать', done: async v => {
      setDlg(null)
      const res = await op({ op: 'rename', path: r.path, name: v })
      if (res.error) note(res.error, 'bad'); else refreshAll()
    } })
  }
  const makeNew = (folder: boolean) => {
    const dir = folderOf(ap)
    setDlg({ k: 'prompt', title: folder ? 'Новая папка' : 'Новый файл', label: 'Имя', value: folder ? 'Новая папка' : 'Новый файл.txt', ok: 'Создать', done: async v => {
      setDlg(null)
      const res = await op({ op: folder ? 'mkdir' : 'newfile', path: dir, name: v })
      if (res.error) note(res.error, 'bad'); else refreshAll()
    } })
  }
  const copyPath = async (rows = selection()) => {
    const text = rows.length ? rows.map(r => r.path).join('\n') : folderOf(ap)
    note((await copyText(text)) ? (rows.length > 1 ? `Скопированы пути: ${rows.length}` : 'Путь скопирован') : 'Не удалось скопировать', 'info')
  }
  const dirSize = async (path: string) => {
    const r = await op({ op: 'dirsize', path })
    if (r.error) { note(r.error, 'bad'); return }
    const id = ++toastId.current
    setToasts(t => [...t, { id, text: 'Считаю размер…', kind: 'job', cancel: () => void post('/api/finder/job/cancel', { id: r.job }) }])
    const s = await watchJob(r.job, x => setToasts(t => t.map(y => y.id === id ? { ...y, text: `Размер ${baseName(path)}: ${(x.info.bytes / 1048576).toFixed(1)} МБ, файлов ${x.info.files}…` } : y)))
    setToasts(t => t.filter(y => y.id !== id))
    note(`${baseName(path)}: ${(s.info.bytes / 1073741824 >= 1 ? (s.info.bytes / 1073741824).toFixed(2) + ' ГБ' : (s.info.bytes / 1048576).toFixed(1) + ' МБ')}, файлов ${s.info.files}${s.cancelled ? ' (остановлено)' : ''}`)
  }
  const openFile = (r: Row) => { void op({ op: 'open', path: r.path }).then(x => { if (x.error) note(x.error, 'bad') }) }
  const reveal = (r: Row) => { void op({ op: 'reveal', path: r.path }).then(x => { if (x.error) note(x.error, 'bad') }) }
  const editMeta = (path: string) => setDlg({ k: 'meta', path })
  const toggleFav = (path: string) => post('/api/fs/favorites', { action: favs.favorites.some(f => lower(f.path) === lower(path)) ? 'remove' : 'add', path }).then(reloadFavs)
  const addFavManual = () => setDlg({ k: 'prompt', title: 'Добавить в избранное', label: 'Путь к папке (локальной или сетевой)', value: '', ok: 'Добавить', done: v => { setDlg(null); void post('/api/fs/favorites', { action: 'add', path: v }).then(reloadFavs) } })
  const showInFolder = (path: string) => { if (st) { patchTab(st.activePane, st.panes[st.activePane].active, { search: undefined, path: dirName(path), back: [...(activeTab(st.activePane)?.back ?? []), activeTab(st.activePane)?.path ?? ''] }); setDlg(null) } }

  // ---------- меню ----------
  const showMenu = (e: React.MouseEvent, rows: Row[], folder: string) => {
    const one = rows.length === 1 ? rows[0] : null
    const other = st?.dual ? folderOf(1 - ap) : ''
    const items: MenuItem[] = []
    if (rows.length) {
      items.push({ label: one?.dir ? 'Открыть папку' : 'Открыть', run: () => (one ? (one.dir ? go(one.path) : openFile(one)) : undefined), disabled: !one })
      if (one?.dir) items.push({ label: 'Открыть в новой вкладке', run: () => addTab(ap, one.path) })
      items.push({ label: 'Открыть в системе / показать в проводнике ОС', run: () => one && reveal(one), disabled: !one })
      items.push({ label: 'Показать в папке', run: () => one && showInFolder(one.path), disabled: !one || !activeTab(ap)?.search })
      items.push({ sep: true, label: '' })
      items.push({ label: 'Копировать путь   Ctrl+Shift+C', run: () => void copyPath(rows) })
      items.push({ label: other ? 'Копировать в другую панель   F5' : 'Копировать в…   F5', run: () => toOther('copy') })
      items.push({ label: other ? 'Переместить в другую панель   F6' : 'Переместить в…   F6', run: () => toOther('move') })
      items.push({ label: 'Переименовать   F2', run: renameSel, disabled: !one })
      items.push({ sep: true, label: '' })
      items.push({ label: 'Цвет и теги…', run: () => one && editMeta(one.path), disabled: !one })
      if (one?.dir) {
        items.push({ label: 'В избранное', run: () => void toggleFav(one.path) })
        items.push({ label: 'Размер папки', run: () => void dirSize(one.path) })
        items.push({ label: 'Дубликаты внутри…', run: () => setDlg({ k: 'dups', folder: one.path }) })
      }
      items.push({ sep: true, label: '' })
      items.push({ label: 'Удалить в корзину   Delete', run: trashSel, danger: true })
    } else {
      items.push({ label: 'Новая папка   F7', run: () => makeNew(true) })
      items.push({ label: 'Новый файл', run: () => makeNew(false) })
      items.push({ label: 'Копировать путь папки', run: () => void copyText(folder).then(() => note('Путь скопирован')) })
      items.push({ label: 'Дубликаты в этой папке…', run: () => setDlg({ k: 'dups', folder }) })
      items.push({ label: 'Обновить', run: () => paneApi[ap].current?.refresh() })
    }
    setMenu({ x: Math.min(e.clientX, window.innerWidth - 300), y: Math.min(e.clientY, window.innerHeight - items.length * 28 - 20), items })
  }
  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener('mousedown', close); window.addEventListener('blur', close); window.addEventListener('keydown', close, true)
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('blur', close); window.removeEventListener('keydown', close, true) }
  }, [menu])

  // ---------- палитра команд ----------
  const cmds: Cmd[] = [
    { id: 'tab', title: 'Новая вкладка', hint: 'Ctrl+T', run: () => addTab(ap) },
    { id: 'closetab', title: 'Закрыть вкладку', hint: 'Ctrl+W', run: () => st && closeTab(ap, st.panes[ap].active) },
    { id: 'dual', title: st?.dual ? 'Одна панель' : 'Две панели', hint: 'Ctrl+D', run: () => update(s => ({ ...s, dual: !s.dual, activePane: 0 })) },
    { id: 'preview', title: st?.preview ? 'Скрыть предпросмотр' : 'Показать предпросмотр', hint: 'F3', run: () => update(s => ({ ...s, preview: !s.preview })) },
    { id: 'hidden', title: st?.hidden ? 'Не показывать скрытые файлы' : 'Показывать скрытые файлы', hint: 'Ctrl+H', run: () => update(s => ({ ...s, hidden: !s.hidden })) },
    { id: 'find', title: 'Поиск', hint: 'Ctrl+F', run: () => searchInput.current?.focus() },
    { id: 'copy', title: 'Копировать выбранное в другую панель', hint: 'F5', run: () => toOther('copy') },
    { id: 'move', title: 'Переместить выбранное в другую панель', hint: 'F6', run: () => toOther('move') },
    { id: 'rename', title: 'Переименовать', hint: 'F2', run: renameSel },
    { id: 'mkdir', title: 'Новая папка', hint: 'F7', run: () => makeNew(true) },
    { id: 'trash', title: 'Удалить в корзину', hint: 'Delete', run: trashSel },
    { id: 'copypath', title: 'Копировать путь', hint: 'Ctrl+Shift+C', run: () => void copyPath() },
    { id: 'fav', title: 'Добавить текущую папку в избранное / убрать', hint: 'Ctrl+B', run: () => void toggleFav(folderOf(ap)) },
    { id: 'meta', title: 'Цвет и теги выбранного', run: () => { const r = selection(); if (r.length === 1) editMeta(r[0].path); else note('Выберите один элемент.') } },
    { id: 'size', title: 'Размер текущей папки', run: () => void dirSize(folderOf(ap)) },
    { id: 'dups', title: 'Найти дубликаты в текущей папке', run: () => setDlg({ k: 'dups', folder: folderOf(ap) }) },
    { id: 'index', title: 'Индекс для быстрого поиска', run: () => setDlg({ k: 'index' }) },
    { id: 'trashview', title: 'Корзина программы', run: () => setDlg({ k: 'trash' }) },
    { id: 'refresh', title: 'Обновить', hint: 'Ctrl+R', run: () => paneApi[ap].current?.refresh() },
    { id: 'theme', title: 'Тема: светлая / тёмная / системная', run: () => update(s => ({ ...s, theme: s.theme === 'system' ? 'light' : s.theme === 'light' ? 'dark' : 'system' })) },
    { id: 'help', title: 'Горячие клавиши и язык поиска', hint: 'F1', run: () => setDlg({ k: 'help' }) },
    { id: 'newfile', title: 'Новый файл', run: () => makeNew(false) },
    { id: 'selall', title: 'Выделить всё', hint: 'Ctrl+A', run: () => paneApi[ap].current?.selectAll() },
  ]
  const palettePaths = useMemo(() => {
    const seen = new Set<string>(); const out: { path: string; label: string }[] = []
    const add = (path: string, label: string) => { if (path && !seen.has(lower(path))) { seen.add(lower(path)); out.push({ path, label }) } }
    favs.favorites.forEach(f => add(f.path, '⭐ ' + f.name)); favs.frequent.forEach(f => add(f.path, '🕘 ' + f.name))
    places.forEach(p => add(p.path, p.name)); roots.forEach(r => add(r.root, '⚡ ' + baseName(r.root)))
    st?.recent.forEach(r => add(r, baseName(r)))
    return out
  }, [favs, places, roots, st?.recent])

  // ---------- клавиши ----------
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const s = stRef.current
      if (!s || dlg || palette) return
      const inInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement).tagName)
      const mod = e.ctrlKey || e.metaKey
      const key = e.key.toLowerCase()
      const pi = s.activePane
      const tab = ACT(s.panes[pi].tabs, s.panes[pi].active)
      const act = (f: () => void) => { e.preventDefault(); f() }
      if (mod && key === 'k') return act(() => setPalette(true))
      if (mod && key === 'f') return act(() => searchInput.current?.focus())
      if (mod && key === 'l') return act(() => { const el = document.querySelector<HTMLDivElement>(`.fx-pane.on .fx-crumbs`); el?.click() })
      if (mod && key === 't') return act(() => addTab(pi))
      if (mod && key === 'w') return act(() => closeTab(pi, s.panes[pi].active))
      if (mod && key === 'd') return act(() => update(x => ({ ...x, dual: !x.dual, activePane: 0 })))
      if (mod && key === 'h') return act(() => update(x => ({ ...x, hidden: !x.hidden })))
      if (mod && key === 'tab') return act(() => selectTab(pi, (s.panes[pi].active + (e.shiftKey ? -1 : 1) + s.panes[pi].tabs.length) % s.panes[pi].tabs.length))
      if (e.key === 'F1') return act(() => setDlg({ k: 'help' }))
      if (e.key === 'Escape' && tab?.search && !inInput) return act(clearSearch)
      if (inInput) return
      if (mod && e.shiftKey && key === 'c') return act(() => void copyPath())
      if (mod && key === 'b') return act(() => void toggleFav(folderOf(pi)))
      if (mod && key === 'r') return act(() => paneApi[pi].current?.refresh())
      if (e.altKey && e.key === 'ArrowLeft') return act(() => goBack(pi, s.panes[pi].active))
      if (e.altKey && e.key === 'ArrowRight') return act(() => goFwd(pi, s.panes[pi].active))
      if (e.key === 'Tab' && s.dual) return act(() => { update(x => ({ ...x, activePane: 1 - pi })); window.setTimeout(() => paneApi[1 - pi].current?.focus(), 0) })
      if (e.key === 'F2') return act(renameSel)
      if (e.key === 'F3') return act(() => update(x => ({ ...x, preview: !x.preview })))
      if (e.key === 'F5') return act(() => toOther('copy'))
      if (e.key === 'F6') return act(() => toOther('move'))
      if (e.key === 'F7') return act(() => makeNew(true))
      if (e.key === 'Delete') return act(trashSel)
      if (e.key === ' ' && !mod) return act(() => update(x => ({ ...x, preview: !x.preview })))
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  })

  // запоминаем посещённые папки для палитры
  const curPath = st ? activeTab(st.activePane)?.path : ''
  useEffect(() => {
    if (!curPath) return
    update(s => ({ ...s, recent: [curPath, ...s.recent.filter(r => lower(r) !== lower(curPath))].slice(0, 15) }))
    const t = window.setTimeout(reloadFavs, 800)
    return () => window.clearTimeout(t)
  }, [curPath, reloadFavs])

  if (!st) return <div className="fx-load">Загрузка…</div>

  const aTab = activeTab(ap)!
  const folder = folderOf(ap)
  const selRows = sel[ap]
  const one = selRows.length === 1 ? selRows[0] : null
  const panes = st.dual ? [0, 1] : [0]
  const dropRows = (rows: string[], dest: string, copy: boolean) => void transfer(copy ? 'copy' : 'move', rows, dest)

  return (
    <div className="fx-app">
      <header className="fx-top">
        <b className="fx-logo">Поисковик</b>
        <SearchBar folder={folder} spec={aTab.search} indexed={indexed} onSearch={runSearch} onClear={clearSearch} inputRef={searchInput} />
        <div className="fx-tools">
          <button title="Палитра команд (Ctrl+K)" onClick={() => setPalette(true)}>⌘ Команды</button>
          <button className={st.dual ? 'on' : ''} title="Две панели (Ctrl+D)" onClick={() => update(s => ({ ...s, dual: !s.dual, activePane: 0 }))}>▥ Две панели</button>
          <button className={st.preview ? 'on' : ''} title="Предпросмотр (F3)" onClick={() => update(s => ({ ...s, preview: !s.preview }))}>👁 Просмотр</button>
          <button className={st.hidden ? 'on' : ''} title="Скрытые файлы (Ctrl+H)" onClick={() => update(s => ({ ...s, hidden: !s.hidden }))}>⋯ Скрытые</button>
          <button title="Справка (F1)" onClick={() => setDlg({ k: 'help' })}>?</button>
        </div>
      </header>
      <div className="fx-body" style={{ gridTemplateColumns: `${st.sideW}px 1fr ${st.preview ? st.previewW + 'px' : ''}` }}>
        <Sidebar places={places} favs={favs} meta={meta} current={folder} go={go} onFavChanged={reloadFavs} addFav={addFavManual} editMeta={editMeta}
          openTrash={() => setDlg({ k: 'trash' })} openIndex={() => setDlg({ k: 'index' })} openDups={() => setDlg({ k: 'dups', folder })} />
        <main className={'fx-panes' + (st.dual ? ' dual' : '')}>
          {panes.map(pi => {
            const pn = st.panes[pi]
            const tab = ACT(pn.tabs, pn.active)!
            return (
              <section key={pi} className="fx-pcol">
                <div className="fx-tabs">
                  {pn.tabs.map((t, ti) => (
                    <div key={t.id} className={'fx-tab' + (ti === pn.active ? ' on' : '')} title={t.search ? `Поиск: ${t.search.query}` : t.path}
                      onMouseDown={e => { if (e.button === 1) { e.preventDefault(); closeTab(pi, ti) } else selectTab(pi, ti) }}>
                      <span>{t.search ? '🔍 ' + (t.search.query || 'фильтр') : baseName(t.path) || t.path}</span>
                      {pn.tabs.length > 1 && <button onMouseDown={e => e.stopPropagation()} onClick={() => closeTab(pi, ti)}>×</button>}
                    </div>
                  ))}
                  <button className="fx-tabadd" title="Новая вкладка (Ctrl+T)" onClick={() => addTab(pi)}>＋</button>
                </div>
                <Pane key={tab.id} tab={tab} index={pi} active={st.activePane === pi} hidden={st.hidden} nonce={nonce} meta={meta} favs={favs}
                  api={paneApi[pi]} navigate={path => navigate(pi, pn.active, path)} goBack={() => goBack(pi, pn.active)} goFwd={() => goFwd(pi, pn.active)}
                  patch={p => patchTab(pi, pn.active, p)} onActivate={() => st.activePane !== pi && update(s => ({ ...s, activePane: pi }))}
                  onSelection={rows => setSel(v => { const n = v.slice(); n[pi] = rows; return n })}
                  onOpenFile={openFile} onMenu={showMenu} onDropRows={dropRows} onNote={k => { if (k === 'fav') void reloadFavs() }} />
              </section>
            )
          })}
        </main>
        {st.preview && <aside className="fx-pvcol"><Preview path={one?.path ?? ''} isDir={!!one?.dir} /></aside>}
      </div>

      <div className="fx-toasts">
        {toasts.map(t => <div key={t.id} className={'fx-toast ' + t.kind}>{t.text}{t.cancel && <button onClick={t.cancel}>Стоп</button>}</div>)}
      </div>
      {menu && (
        <div className="fx-menu" style={{ left: menu.x, top: menu.y }} onMouseDown={e => e.stopPropagation()}>
          {menu.items.map((m, i) => m.sep ? <hr key={i} /> : <button key={i} disabled={m.disabled} className={m.danger ? 'danger' : ''} onClick={() => { setMenu(null); m.run?.() }}>{m.label}</button>)}
        </div>
      )}
      {palette && <Palette cmds={cmds} paths={palettePaths} onGo={go} onClose={() => setPalette(false)}
        onSearch={q => runSearch({ ...(aTab.search ?? { query: '', root: folder, regex: false, case: false, types: [], sizeMin: '', sizeMax: '', dateFrom: '', dateTo: '', want: 'all', hidden: false, useIndex: true }), query: q, root: folder })} />}
      {dlg?.k === 'prompt' && <Prompt title={dlg.title} label={dlg.label} value={dlg.value} ok={dlg.ok} onDone={v => (v === null ? setDlg(null) : dlg.done(v))} />}
      {dlg?.k === 'confirm' && <Confirm title={dlg.title} text={dlg.text} ok={dlg.ok} danger={dlg.danger} list={dlg.list} onDone={ok => (ok ? dlg.done() : setDlg(null))} />}
      {dlg?.k === 'conflict' && <Conflict names={dlg.names} onDone={c => (c ? dlg.done(c) : setDlg(null))} />}
      {dlg?.k === 'meta' && <MetaDialog path={dlg.path} colors={colors} meta={meta[Object.keys(meta).find(k => lower(k) === lower(dlg.path)) || ''] || {}}
        onDone={async m => { setDlg(null); if (m) { await post('/api/finder/meta', { path: dlg.path, color: m.color, tags: m.tags, note: m.note }); void reloadMeta() } }} />}
      {dlg?.k === 'trash' && <TrashDialog onClose={() => setDlg(null)} onChanged={refreshAll} />}
      {dlg?.k === 'index' && <IndexDialog current={folder} onClose={() => setDlg(null)} onChanged={setRoots} />}
      {dlg?.k === 'help' && <Help onClose={() => setDlg(null)} />}
      {dlg?.k === 'dups' && <DupsDialog folder={dlg.folder} onClose={() => setDlg(null)} onShow={showInFolder} />}
    </div>
  )
}

