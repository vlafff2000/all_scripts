import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { exportExcel, getGsp, getSeason, getState, saveImage, type AppState, type GspData } from './api'
import Inspector from './Inspector'
import MapView, { type MapHandle } from './MapView'
import { SeasonCalc, fmtDay } from './model'
import SharesPage from './SharesPage'
import WorkPage from './WorkPage'
import { DataPage, PressurePage, TablePage, TrendsPage } from './Pages'
import { paintMode, fixedScale, inspectorOpen, lastGsp, lastKind, posMode, sectors, showShare, showWater, sidebarCollapsed, theme, usePref, type Theme } from './prefs'
import Timeline from './Timeline'

const PAGES = [
  { id: 'map', title: 'Карта', icon: 'M8 1.5a4.5 4.5 0 0 1 4.5 4.5c0 3-4.5 8.5-4.5 8.5S3.5 9 3.5 6A4.5 4.5 0 0 1 8 1.5Zm0 3a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Z' },
  { id: 'work', title: 'Работа скважин', icon: 'M2 3h12M2 8h12M2 13h12M4 3v0M7 8v0M10 13v0M3 5.5h5M6 10.5h7' },
  { id: 'shares', title: 'Доли', icon: 'M8 2a6 6 0 1 0 6 6H8zM9.5 1.5A5 5 0 0 1 14.5 6.5H9.5z' },
  { id: 'table', title: 'Таблица', icon: 'M2 3h12v10H2zM2 6.5h12M2 10h12M6 3v10' },
  { id: 'pressure', title: 'Давление', icon: 'M2 13V3M2 13h12M4 10l3-3 2 2 4-5' },
  { id: 'trends', title: 'Тренды', icon: 'M2 12l4-4 3 2 5-6M10 4h4v4' },
  { id: 'data', title: 'Данные', icon: 'M3 3h10v3H3zM3 8h10v3H3zM5 4.5h.01M5 9.5h.01M3 13h10' },
] as const
type PageId = (typeof PAGES)[number]['id']
const routeOf = (): PageId => { const r = location.hash.replace(/^#\/?/, ''); return (PAGES.find(p => p.id === r)?.id || 'map') }

function Issues({ notes, warnings }: { notes: string[]; warnings: string[] }) {
  const [open, setOpen] = useState(false)
  const all = [...notes, ...warnings]
  if (!all.length) return null
  return (
    <div className="issues">
      <button type="button" className="quiet warn" aria-expanded={open} onClick={() => setOpen(o => !o)} title="Замечания по файлам и положению скважин">⚠ {all.length}</button>
      {open && <div className="issues-pop" role="dialog" aria-label="Замечания">{all.map((t, i) => <p key={i}>{t}</p>)}</div>}
    </div>
  )
}

export default function App() {
  const [app, setApp] = useState<AppState | null>(null)
  const [error, setError] = useState('')
  const [page, setPage] = useState<PageId>(routeOf())
  const collapsed = usePref(sidebarCollapsed), currentTheme = usePref(theme)
  const mode = usePref(posMode), kind = usePref(lastKind), gspPref = usePref(lastGsp)
  const sec = usePref(sectors), water = usePref(showWater), share = usePref(showShare), fixed = usePref(fixedScale), paint = usePref(paintMode), insp = usePref(inspectorOpen)
  const [g, setG] = useState<GspData | null>(null)
  const [gErr, setGErr] = useState('')
  const [seasonKey, setSeasonKey] = useState('')
  const [calc, setCalc] = useState<SeasonCalc | null>(null)
  const [win, setWin] = useState<[number, number]>([0, 0])
  const [selected, setSelected] = useState<number | null>(null)
  const [find, setFind] = useState('')
  const [note, setNote] = useState('')
  const map = useRef<MapHandle>(null)

  const refresh = useCallback(() => getState().then(setApp).catch(e => setError(String(e.message || e))), [])
  useEffect(() => { refresh() }, [refresh])
  useEffect(() => {
    if (app?.state !== 'loading') return
    const t = setInterval(refresh, 500)
    return () => clearInterval(t)
  }, [app?.state, refresh])
  useEffect(() => {
    const onHash = () => setPage(routeOf())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const ready = app?.state === 'ready'
  const withMap = ready ? app!.gsps.find(x => app!.gspMeta[x]?.grid || app!.gspMeta[x]?.xy) : undefined
  const gsp = ready ? (app!.gsps.includes(gspPref) ? gspPref : withMap || app!.gsps[0] || '') : ''
  useEffect(() => {
    if (!ready || !gsp) return
    let live = true
    setGErr('')
    getGsp(gsp, mode).then(d => { if (live) { setG(d); setSelected(null) } }).catch(e => live && setGErr(String(e.message || e)))
    return () => { live = false }
  }, [ready, gsp, mode])

  const seasons = g ? g.seasons[kind as 'Отбор' | 'Закачка'] || [] : []
  const season = seasons.find(s => s.key === seasonKey) ? seasonKey : seasons.length ? seasons[seasons.length - 1].key : ''
  useEffect(() => {
    if (!g || !season) { setCalc(null); return }
    let live = true
    getSeason(g.gsp, kind, season).then(d => {
      if (!live) return
      const c = new SeasonCalc(d)
      setCalc(c); setWin([0, Math.max(0, c.nd - 1)])
    }).catch(e => live && setGErr(String(e.message || e)))
    return () => { live = false }
  }, [g, kind, season])

  const setWindow = useCallback((a: number, b: number) => setWin([a, b]), [])
  const [a, b] = calc ? calc.clampWindow(win[0], win[1]) : [0, 0]
  const title = g && calc ? `${g.gsp} · ${kind} ${season} · ${fmtDay(calc.days[a])} — ${fmtDay(calc.days[b])}` : ''
  useEffect(() => { document.title = 'Карты ГСП' + (gsp ? ' · ' + gsp : '') }, [gsp])

  const flash = (t: string) => { setNote(t); setTimeout(() => setNote(''), 6000) }
  const png = async () => {
    try {
      const blob = await map.current!.toPng()
      const name = `Карта_${gsp.replace(/\s/g, '_')}_${kind}_${season}.png`
      try { const r = await saveImage(name, blob); flash('Картинка сохранена: ' + r.path) } catch {
        const u = URL.createObjectURL(blob), el = document.createElement('a'); el.href = u; el.download = name; el.click(); URL.revokeObjectURL(u)
      }
    } catch (e) { flash(String((e as Error).message || e)) }
  }
  const excel = async () => { try { const r = await exportExcel(gsp, mode); flash('Excel сохранён: ' + r.path) } catch (e) { flash(String((e as Error).message || e)) } }
  const goFind = (v: string) => {
    setFind(v)
    const n = Number(v)
    if (calc && calc.index.has(n)) { setSelected(n); map.current?.focus(n) }
  }

  const groupedNav = useMemo(() => PAGES, [])
  if (error) return <div className="fatal"><h1>Карты ГСП</h1><p>{error}</p></div>
  const body = () => {
    if (!app) return <p className="muted">Загрузка…</p>
    if (page === 'data') return <DataPage app={app} setApp={setApp} mode={mode} setMode={posMode.set} gsp={gsp} onReload={refresh} />
    if (app.state === 'loading') return (
      <section className="card loading"><div className="spinner" aria-hidden="true" /><div><h2>Загружаю базу расходов</h2>
        <pre className="log">{app.log.join('\n') || 'Подготовка…'}</pre>
        <p className="muted">Первый раз это занимает до минуты: книга большая. Дальше она открывается из кэша меньше чем за секунду.</p></div></section>)
    if (app.state !== 'ready') return (
      <section className="card"><h2>{app.state === 'error' ? 'База не загрузилась' : 'Сначала подключите данные'}</h2>
        {app.state === 'error' && <pre className="log">{app.log.join('\n')}</pre>}
        <p className="muted">Откройте раздел «Данные»: выберите папку с файлами или укажите БД_расходы.xlsx.</p>
        <p><a className="primary linkbtn" href="#/data">Перейти к данным</a></p></section>)
    if (!g || !calc) return gErr ? <div className="note warning">{gErr}</div> : <p className="muted">Считаю…</p>
    if (page === 'table') return <TablePage g={g} calc={calc} kind={kind} season={season} a={a} b={b} mode={mode} />
    if (page === 'pressure') return <PressurePage g={g} kind={kind} season={season} range={[calc.days[a], calc.days[b]]} />
    if (page === 'work') return <WorkPage g={g} calc={calc} kind={kind} season={season} selected={selected} onSelect={setSelected} />
    if (page === 'shares') return <SharesPage g={g} kind={kind} selected={selected} onSelect={setSelected} />
    if (page === 'trends') return <TrendsPage g={g} />
    return (
      <div className={'map-page' + (insp ? '' : ' no-insp')}>
        <div className="map-main">
          <MapView ref={map} g={g} calc={calc} kind={kind} season={season} a={a} b={b} selected={selected} onSelect={setSelected} title={title}
            options={{ sectors: sec, water, share, fixed, paint }}
            onOptions={o => { if (o.sectors) sectors.set(o.sectors); if (o.water !== undefined) showWater.set(o.water); if (o.share !== undefined) showShare.set(o.share); if (o.fixed !== undefined) fixedScale.set(o.fixed); if (o.paint) paintMode.set(o.paint) }} />
          <Timeline g={g} calc={calc} a={a} b={b} setWindow={setWindow} />
        </div>
        {insp && <Inspector g={g} calc={calc} kind={kind} season={season} a={a} b={b} selected={selected} onSelect={setSelected} onFocus={w => map.current?.focus(w)} />}
      </div>)
  }
  const showBar = ready && !!g && page !== 'data'
  return (
    <div className={'shell' + (collapsed ? ' collapsed' : '')}>
      <aside className="sidebar">
        <div className="brand">
          <a href="#/" className="brand-link"><span className="brand-mark" aria-hidden="true" /><span className="brand-name">Карты ГСП</span></a>
          <button type="button" className="side-toggle" onClick={() => sidebarCollapsed.set(!collapsed)} aria-expanded={!collapsed} title={collapsed ? 'Показать меню' : 'Свернуть меню'}>
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d={collapsed ? 'M6 3.5 10.5 8 6 12.5' : 'M10 3.5 5.5 8 10 12.5'} /></svg></button>
        </div>
        <nav aria-label="Разделы"><ul>{groupedNav.map(p => (
          <li key={p.id}><a href={'#/' + p.id} aria-current={p.id === page ? 'page' : undefined} title={p.title}>
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d={p.icon} /></svg><span className="side-label">{p.title}</span></a></li>))}</ul></nav>
        <div className="theme-switch segmented" role="radiogroup" aria-label="Тема">
          {([['light', 'Светлая'], ['dark', 'Тёмная'], ['system', 'Авто']] as [Theme, string][]).map(([t, label]) => (
            <button key={t} type="button" role="radio" aria-checked={currentTheme === t} onClick={() => theme.set(t)} title={t === 'system' ? 'Как в системе' : label + ' тема'}>
              {t === 'light' ? <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" /></svg>
                : t === 'dark' ? <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5Z" /></svg>
                : <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="3" width="12" height="8" rx="1" /><path d="M6 13.5h4" /></svg>}
              <span className="side-label">{label}</span></button>))}
        </div>
      </aside>
      <main className={'workspace' + (page === 'map' ? ' wide' : '')}>
        {showBar && (
          <div className="topbar">
            <label className="sel"><span>ГСП</span>
              <select value={gsp} onChange={e => lastGsp.set(e.target.value)}>{app!.gsps.map(x => <option key={x} value={x}>{x}{app!.gspMeta[x] && !app!.gspMeta[x].grid && !app!.gspMeta[x].xy ? ' · нет карты' : ''}</option>)}</select></label>
            <div className="segmented" role="radiogroup" aria-label="Вид">
              {['Отбор', 'Закачка'].map(k => <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => lastKind.set(k)}>{k}</button>)}</div>
            <label className="sel"><span>Сезон</span>
              <select value={season} onChange={e => setSeasonKey(e.target.value)}>{seasons.map(s => <option key={s.key}>{s.key}</option>)}</select></label>
            {page === 'map' && <>
              <input className="find" inputMode="numeric" placeholder="Скважина №" aria-label="Найти скважину" value={find} onChange={e => goFind(e.target.value)} />
              <span className="spacer" />
              {g && <Issues notes={g.layout.notes} warnings={g.warnings} />}
              <button type="button" className="quiet" onClick={png} title="Сохранить карту как картинку">PNG</button>
              <button type="button" className="quiet" onClick={excel} title="Выгрузить таблицы в Excel">Excel</button>
              <button type="button" className="quiet" onClick={() => inspectorOpen.set(!insp)} aria-pressed={insp} title="Панель сведений">Сведения</button>
            </>}
          </div>)}
        {note && <div className="note info" role="status">{note}</div>}
        {body()}
      </main>
    </div>
  )
}
