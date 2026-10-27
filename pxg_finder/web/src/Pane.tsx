// Одна панель: вкладка с папкой или результатами поиска, список с выделением мышью и клавишами, быстрые действия.
import { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import type { Ref } from 'react'
import { baseName, crumbs, dirName, fmtSize, getJson, iconOf, joinPath, post, watchJob } from './api'
import type { Favs, Listing } from './api'
import { COLOR_HEX } from './types'
import type { MetaMap, PaneApi, Row, SearchSpec, Tab } from './types'

const ROW_H = 28
const lowerKey = (p: string) => p.replace(/\//g, '\\').toLowerCase()

interface Props {
  tab: Tab
  index: number
  active: boolean
  hidden: boolean
  nonce: number
  meta: MetaMap
  favs: Favs
  api: Ref<PaneApi>
  navigate: (path: string) => void
  goBack: () => void
  goFwd: () => void
  patch: (p: Partial<Tab>) => void
  onActivate: () => void
  onSelection: (rows: Row[]) => void
  onOpenFile: (r: Row) => void
  onMenu: (e: React.MouseEvent, rows: Row[], folder: string) => void
  onDropRows: (rows: string[], dest: string, copy: boolean) => void
  onNote: (t: string) => void
}

export default function Pane(p: Props) {
  const { tab } = p
  const [list, setList] = useState<Listing | null>(null)
  const [found, setFound] = useState<Row[] | null>(null)
  const [searchInfo, setSearchInfo] = useState<{ running: boolean; scanned: number; source: string; truncated: boolean; error: string; secs: number }>({ running: false, scanned: 0, source: '', truncated: false, error: '', secs: 0 })
  const [busy, setBusy] = useState(false)
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [focus, setFocus] = useState(-1)
  const [pathText, setPathText] = useState('')
  const [editPath, setEditPath] = useState(false)
  const [quick, setQuick] = useState('')
  const [top, setTop] = useState(0)
  const [viewH, setViewH] = useState(400)
  const [band, setBand] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null)
  const [dropOn, setDropOn] = useState<string>('')
  const box = useRef<HTMLDivElement>(null)
  const anchor = useRef(-1)
  const reqId = useRef(0)
  const typed = useRef({ s: '', t: 0 })
  const searching = !!tab.search

  const rows: Row[] = useMemo(() => {
    if (searching) return found ?? []
    return (list?.items ?? []).map(i => ({ ...i, path: joinPath(list!.path, i.name) }))
  }, [list, found, searching])

  // ---------- загрузка папки ----------
  const load = useCallback(async (path: string, fresh = false) => {
    const q = new URLSearchParams({ path, sort: tab.sort, limit: '5000' })
    if (tab.desc) q.set('desc', '1')
    if (p.hidden) q.set('hidden', '1')
    if (fresh) q.set('fresh', '1')
    const id = ++reqId.current
    if (!fresh) setBusy(true)
    const r = await getJson<Listing>('/api/fs/list?' + q).catch(() => null)
    if (id !== reqId.current) return
    setBusy(false)
    if (!r) return
    setList(r)
    if (!fresh) { setSel(new Set()); setFocus(-1); anchor.current = -1; box.current?.scrollTo(0, 0) }
    if (r.path && !r.error) {
      setPathText(r.path)
      if (!fresh) void post('/api/fs/visit', { path: r.path })
    }
    if (r.cached && !r.error) { void load(r.path, true); return } // сеть: кэш показан сразу, свежий листинг подменит его
    if (r.lazy && !r.error) {
      const names = r.items.slice(0, 300).map(i => i.name)
      const st = await post<{ stats: Record<string, { size: number; mtime: string; locked?: boolean }> }>('/api/fs/stat', { path: r.path, names }).catch(() => null)
      if (st && id === reqId.current) setList(l => l && l.path === r.path ? { ...l, lazy: false, items: l.items.map(i => st.stats[i.name] ? { ...i, ...st.stats[i.name] } : i) } : l)
    }
  }, [tab.sort, tab.desc, p.hidden])

  useEffect(() => { if (!searching) void load(tab.path) }, [tab.path, tab.sort, tab.desc, p.hidden, searching, load])
  useEffect(() => { if (p.nonce && !searching) void load(tab.path, true) }, [p.nonce]) // eslint-disable-line react-hooks/exhaustive-deps

  // ---------- поиск ----------
  useEffect(() => {
    const spec = tab.search
    if (!spec) { setFound(null); return }
    const run = ++reqId.current
    setFound([]); setSel(new Set()); setFocus(-1); anchor.current = -1
    setSearchInfo({ running: true, scanned: 0, source: '', truncated: false, error: '', secs: 0 })
    let jobId = ''
    ;(async () => {
      const r = await post<{ job?: string; error?: string }>('/api/finder/search', spec)
      if (r.error || !r.job) { setSearchInfo(s => ({ ...s, running: false, error: r.error || 'Не удалось начать поиск' })); return }
      jobId = r.job
      await watchJob(r.job, s => {
        if (run !== reqId.current) return
        const add: Row[] = s.items.map((i: any) => ({ ...i, where: dirName(i.path) }))
        if (add.length) setFound(f => (f ? f.concat(add) : add))
        setSearchInfo({ running: !s.done, scanned: s.info.scanned || 0, source: s.info.source || '', truncated: !!s.info.truncated || !!s.info.timeout, error: s.error, secs: s.elapsed })
      })
    })()
    return () => { reqId.current++; if (jobId) void post('/api/finder/job/cancel', { id: jobId }) }
  }, [tab.search, tab.runId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ---------- выбранное ----------
  const selRows = useMemo(() => [...sel].sort((a, b) => a - b).map(i => rows[i]).filter(Boolean), [sel, rows])
  useEffect(() => { p.onSelection(selRows) }, [selRows]) // eslint-disable-line react-hooks/exhaustive-deps
  const folder = searching ? tab.search!.root : (list?.path || tab.path)

  useImperativeHandle(p.api, () => ({
    selection: () => selRows,
    focusedFolder: () => folder,
    refresh: () => (searching ? p.patch({ runId: (tab.runId || 0) + 1 }) : void load(tab.path, true)),
    selectAll: () => setSel(new Set(rows.map((_, i) => i))),
    focus: () => box.current?.focus(),
  }), [selRows, folder, searching, rows, tab.path, tab.runId, load]) // eslint-disable-line react-hooks/exhaustive-deps

  const open = (r: Row) => {
    if (r.dir) { if (searching) p.patch({ search: undefined, path: r.path }); else p.navigate(r.path) } else p.onOpenFile(r)
  }
  const goUp = () => { if (list?.parent) p.navigate(list.parent) }

  // ---------- мышь ----------
  const click = (i: number, e: React.MouseEvent) => {
    p.onActivate()
    box.current?.focus()
    if (e.shiftKey && anchor.current >= 0) {
      const [a, b] = [Math.min(anchor.current, i), Math.max(anchor.current, i)]
      const s = new Set(e.ctrlKey || e.metaKey ? sel : []) as Set<number>
      for (let k = a; k <= b; k++) s.add(k)
      setSel(s)
    } else if (e.ctrlKey || e.metaKey) {
      const s = new Set(sel); if (s.has(i)) s.delete(i); else s.add(i)
      setSel(s); anchor.current = i
    } else { setSel(new Set([i])); anchor.current = i }
    setFocus(i)
  }

  const bandStart = (e: React.MouseEvent) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest('.fx-row')) return
    p.onActivate(); box.current?.focus()
    const el = box.current!
    const rect = el.getBoundingClientRect()
    const pt = (ev: { clientX: number; clientY: number }) => ({ x: ev.clientX - rect.left + el.scrollLeft, y: ev.clientY - rect.top + el.scrollTop })
    const s0 = pt(e)
    const base = e.ctrlKey || e.metaKey ? new Set(sel) : new Set<number>()
    if (!(e.ctrlKey || e.metaKey)) setSel(new Set())
    const move = (ev: MouseEvent) => {
      const s1 = pt(ev)
      setBand({ x0: s0.x, y0: s0.y, x1: s1.x, y1: s1.y })
      const a = Math.max(0, Math.floor((Math.min(s0.y, s1.y) - ROW_H) / ROW_H)), b = Math.min(rows.length - 1, Math.floor((Math.max(s0.y, s1.y) - ROW_H) / ROW_H))
      const s = new Set(base) as Set<number>
      for (let k = a; k <= b; k++) s.add(k)
      setSel(s)
    }
    const up = () => { setBand(null); window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
  }

  const onDragStart = (i: number, e: React.DragEvent) => {
    const paths = sel.has(i) ? selRows.map(r => r.path) : [rows[i].path]
    if (!sel.has(i)) { setSel(new Set([i])); anchor.current = i }
    e.dataTransfer.setData('application/x-pxg-paths', JSON.stringify(paths))
    e.dataTransfer.effectAllowed = 'copyMove'
  }
  const dropTo = (dest: string, e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDropOn('')
    try {
      const paths = JSON.parse(e.dataTransfer.getData('application/x-pxg-paths') || '[]') as string[]
      if (paths.length && dest) p.onDropRows(paths, dest, e.ctrlKey)
    } catch { /* чужой объект */ }
  }

  // ---------- клавиши ----------
  const move = (to: number, extend: boolean) => {
    if (!rows.length) return
    const n = Math.max(0, Math.min(rows.length - 1, to))
    if (extend) {
      const a = anchor.current >= 0 ? anchor.current : Math.max(focus, 0)
      const s = new Set<number>(); for (let k = Math.min(a, n); k <= Math.max(a, n); k++) s.add(k)
      setSel(s); if (anchor.current < 0) anchor.current = a
    } else { setSel(new Set([n])); anchor.current = n }
    setFocus(n)
    const el = box.current
    if (el) {
      const y = n * ROW_H + ROW_H
      if (y < el.scrollTop + ROW_H) el.scrollTop = y - ROW_H
      else if (y + ROW_H > el.scrollTop + el.clientHeight) el.scrollTop = y + ROW_H - el.clientHeight
    }
  }
  const onKey = (e: React.KeyboardEvent) => {
    const mod = e.ctrlKey || e.metaKey
    if (e.key === 'ArrowDown') { e.preventDefault(); move((focus < 0 ? -1 : focus) + 1, e.shiftKey) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(focus < 0 ? 0 : focus - 1, e.shiftKey) }
    else if (e.key === 'PageDown') { e.preventDefault(); move(focus + Math.floor(viewH / ROW_H), e.shiftKey) }
    else if (e.key === 'PageUp') { e.preventDefault(); move(focus - Math.floor(viewH / ROW_H), e.shiftKey) }
    else if (e.key === 'Home') { e.preventDefault(); move(0, e.shiftKey) }
    else if (e.key === 'End') { e.preventDefault(); move(rows.length - 1, e.shiftKey) }
    else if (e.key === 'Enter' && !mod) { e.preventDefault(); const r = rows[focus] ?? selRows[0]; if (r) open(r) }
    else if (e.key === 'Backspace' && !searching) { e.preventDefault(); goUp() }
    else if (e.key === 'ArrowRight' && !mod && rows[focus]?.dir) { e.preventDefault(); open(rows[focus]) }
    else if (e.key === 'ArrowLeft' && !mod && !searching) { e.preventDefault(); goUp() }
    else if (mod && e.key.toLowerCase() === 'a') { e.preventDefault(); setSel(new Set(rows.map((_, i) => i))) }
    else if (e.key === 'Insert') { e.preventDefault(); if (focus >= 0) { const s = new Set(sel); if (s.has(focus)) s.delete(focus); else s.add(focus); setSel(s); move(focus + 1, false); setSel(s) } }
    else if (!mod && !e.altKey && e.key.length === 1 && e.key !== ' ') {
      // быстрый переход по первым буквам имени
      const now = Date.now()
      const s = (now - typed.current.t > 900 ? '' : typed.current.s) + e.key.toLowerCase()
      typed.current = { s, t: now }
      setQuick(s)
      const k = rows.findIndex(r => r.name.toLowerCase().startsWith(s))
      if (k >= 0) move(k, false)
      window.setTimeout(() => setQuick(q => (Date.now() - typed.current.t >= 850 ? '' : q)), 900)
    }
  }

  // ---------- вид ----------
  const first = Math.max(0, Math.floor(top / ROW_H) - 6)
  const last = Math.min(rows.length, Math.ceil((top + viewH) / ROW_H) + 6)
  const total = searching ? rows.length : list?.total ?? 0
  const crumbList = crumbs(folder || '')
  const setSort = (s: 'name' | 'mtime' | 'size') => p.patch(tab.sort === s ? { desc: !tab.desc } : { sort: s, desc: s !== 'name' })
  const arrow = (s: string) => (tab.sort === s ? (tab.desc ? ' ▼' : ' ▲') : '')
  const favSet = useMemo(() => new Set(p.favs.favorites.map(f => lowerKey(f.path))), [p.favs])
  const isFav = !!folder && favSet.has(lowerKey(folder))

  const submitPath = () => {
    setEditPath(false)
    const t = pathText.trim().replace(/^"|"$/g, '')
    if (t && t !== list?.path) p.navigate(t)
  }

  return (
    <div className={'fx-pane' + (p.active ? ' on' : '')} onMouseDown={p.onActivate}
      onDragOver={e => { if (e.dataTransfer.types.includes('application/x-pxg-paths')) { e.preventDefault(); setDropOn('_pane') } }}
      onDragLeave={() => setDropOn('')} onDrop={e => dropTo(folder, e)}>
      <div className="fx-pbar">
        <button title="Назад (Alt+←)" disabled={!tab.back.length} onClick={p.goBack}>←</button>
        <button title="Вперёд (Alt+→)" disabled={!tab.fwd.length} onClick={p.goFwd}>→</button>
        <button title="Вверх (Backspace)" disabled={searching || !list?.parent} onClick={goUp}>↑</button>
        <button title="Обновить (F5 в списке — копирование, Ctrl+R — обновить)" onClick={() => (searching ? p.patch({ runId: (tab.runId || 0) + 1 }) : void load(tab.path, true))}>⟳</button>
        {editPath || searching ? (
          <input className="fx-path" autoFocus={editPath} value={searching ? `Поиск «${tab.search!.query}» в ${tab.search!.root}` : pathText} readOnly={searching}
            onChange={e => setPathText(e.target.value)} onBlur={() => setEditPath(false)}
            onKeyDown={e => { if (e.key === 'Enter') submitPath(); if (e.key === 'Escape') { setEditPath(false); setPathText(list?.path || '') } }} />
        ) : (
          <div className="fx-crumbs" onClick={e => { if (e.target === e.currentTarget) setEditPath(true) }} title="Щёлкните по пустому месту, чтобы ввести путь">
            {crumbList.map(c => <button key={c.path} onClick={() => p.navigate(c.path)}>{c.name}</button>)}
          </div>
        )}
        {searching && <button title="Закрыть поиск (Esc)" onClick={() => p.patch({ search: undefined })}>✕ поиск</button>}
        <button title={isFav ? 'Убрать из избранного' : 'В избранное'} className={isFav ? 'fx-star on' : 'fx-star'} disabled={!folder}
          onClick={() => void post('/api/fs/favorites', { action: isFav ? 'remove' : 'add', path: folder }).then(() => p.onNote('fav'))}>{isFav ? '★' : '☆'}</button>
      </div>

      <div className="fx-list" ref={box} tabIndex={0} onKeyDown={onKey} onMouseDown={bandStart}
        onScroll={e => setTop(e.currentTarget.scrollTop)} onContextMenu={e => { if (!(e.target as HTMLElement).closest('.fx-row')) { e.preventDefault(); p.onActivate(); p.onMenu(e, [], folder) } }}
        >
        <Measure box={box} onH={setViewH} />
        <div className="fx-head fx-row-h" style={{ height: ROW_H }}>
          <span className="fx-ico" />
          <span className="fx-name" onClick={() => !searching && setSort('name')}>Имя{!searching && arrow('name')}</span>
          {searching && <span className="fx-where">Папка</span>}
          <span className="fx-date" onClick={() => !searching && setSort('mtime')}>Изменён{!searching && arrow('mtime')}</span>
          <span className="fx-size" onClick={() => !searching && setSort('size')}>Размер{!searching && arrow('size')}</span>
        </div>
        <div style={{ height: rows.length * ROW_H, position: 'relative' }}>
          {rows.slice(first, last).map((r, k) => {
            const i = first + k
            const m = p.meta[Object.keys(p.meta).find(x => lowerKey(x) === lowerKey(r.path)) || '']
            return (
              <div key={r.path} className={'fx-row' + (sel.has(i) ? ' sel' : '') + (i === focus ? ' foc' : '') + (r.locked ? ' locked' : '') + (dropOn === r.path ? ' drop' : '')}
                style={{ top: i * ROW_H, height: ROW_H }} draggable
                onClick={e => click(i, e)} onDoubleClick={() => open(r)}
                onContextMenu={e => { e.preventDefault(); e.stopPropagation(); let rr = selRows; if (!sel.has(i)) { setSel(new Set([i])); anchor.current = i; setFocus(i); rr = [r] } p.onActivate(); p.onMenu(e, rr, folder) }}
                onDragStart={e => onDragStart(i, e)}
                onDragOver={e => { if (r.dir && e.dataTransfer.types.includes('application/x-pxg-paths')) { e.preventDefault(); e.stopPropagation(); setDropOn(r.path) } }}
                onDrop={e => r.dir ? dropTo(r.path, e) : undefined}>
                <span className="fx-ico">{iconOf(r)}</span>
                <span className="fx-name" title={r.name}>
                  {m?.color && <i className="fx-dot" style={{ background: COLOR_HEX[m.color] }} />}
                  {r.name}
                  {m?.tags?.map(t => <em key={t} className="fx-tag">{t}</em>)}
                </span>
                {searching && <span className="fx-where" title={r.where}>{r.where}</span>}
                <span className="fx-date">{r.mtime}</span>
                <span className="fx-size">{r.dir ? '' : fmtSize(r.size)}</span>
              </div>
            )
          })}
          {band && <div className="fx-band" style={{ left: Math.min(band.x0, band.x1), top: Math.min(band.y0, band.y1) - ROW_H, width: Math.abs(band.x1 - band.x0), height: Math.abs(band.y1 - band.y0) }} />}
        </div>
        {!rows.length && !busy && !searchInfo.running && (
          <div className="fx-empty">{list?.error ? <span className="bad">{list.error}</span> : searching ? (searchInfo.error ? <span className="bad">{searchInfo.error}</span> : 'Ничего не найдено') : 'Папка пуста'}</div>
        )}
        {busy && !rows.length && <div className="fx-empty">Загрузка…</div>}
      </div>

      <div className="fx-pfoot">
        {searching ? (
          <span>{searchInfo.running ? 'Идёт поиск… ' : 'Найдено: '}{rows.length}{searchInfo.truncated ? '+ (показана часть, уточните запрос)' : ''}
            {' · '}{searchInfo.source === 'index' ? 'по индексу' : searchInfo.source === 'disk' ? `обход диска, просмотрено ${searchInfo.scanned.toLocaleString('ru')}` : ''}{!searchInfo.running && searchInfo.secs ? `, ${searchInfo.secs.toFixed(1)} с` : ''}
            {searchInfo.running && <button className="fx-link" onClick={() => p.patch({ search: { ...(tab.search as SearchSpec) } })}>перезапуск</button>}</span>
        ) : (
          <span>{total} эл.{list?.truncated ? ' (показана часть)' : ''}{list?.network ? ' · сеть' : ''}{list?.cached ? ' · обновляется…' : ''}{sel.size ? ` · выбрано ${sel.size}` : ''}
            {selRows.length > 0 && selRows.every(r => !r.dir) ? ' · ' + fmtSize(selRows.reduce((a, r) => a + r.size, 0)) : ''}</span>
        )}
        {quick && <span className="fx-quick">{quick}</span>}
        {selRows.length === 1 && <span className="fx-pick" title={selRows[0].path}>{baseName(selRows[0].path)}</span>}
      </div>
    </div>
  )
}

/** Следит за высотой видимой области списка (для окна рисуемых строк). */
function Measure({ box, onH }: { box: React.RefObject<HTMLDivElement | null>; onH: (h: number) => void }) {
  useEffect(() => {
    const el = box.current
    if (!el) return
    onH(el.clientHeight)
    const ro = new ResizeObserver(() => onH(el.clientHeight))
    ro.observe(el)
    return () => ro.disconnect()
  }, [box, onH])
  return null
}

