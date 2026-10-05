import { useEffect, useMemo, useState } from 'react'
import { getModules, type ModuleInfo } from './api'
import ModulePage from './ModulePage'
import { sidebarCollapsed, theme, usePref, type Theme } from './prefs'

const routeOf = () => decodeURIComponent(location.hash.replace(/^#\/?/, ''))

function Search({ modules, open, onClose }: { modules: ModuleInfo[]; open: boolean; onClose: () => void }) {
  const [q, setQ] = useState('')
  const [cur, setCur] = useState(0)
  const found = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean)
    return modules.filter(m => words.every(w => (m.title + ' ' + m.group + ' ' + m.description).toLowerCase().includes(w))).slice(0, 12)
  }, [modules, q])
  useEffect(() => { if (open) { setQ(''); setCur(0) } }, [open])
  useEffect(() => setCur(0), [q])
  if (!open) return null
  const go = (m?: ModuleInfo) => { if (m) { location.hash = '#/' + m.id; onClose() } }
  return (
    <div className="overlay" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-label="Найти модуль" onMouseDown={e => e.stopPropagation()}>
        <input autoFocus placeholder="Найти модуль…" value={q} onChange={e => setQ(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Escape') onClose()
            else if (e.key === 'ArrowDown') { e.preventDefault(); setCur(c => Math.min(c + 1, found.length - 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setCur(c => Math.max(c - 1, 0)) }
            else if (e.key === 'Enter') go(found[cur])
          }} />
        <ul>{found.map((m, i) => (
          <li key={m.id}><button className={i === cur ? 'on' : ''} onMouseEnter={() => setCur(i)} onClick={() => go(m)}>
            <b>{m.title}</b><span className="muted">{m.group}</span></button></li>
        ))}{!found.length && <li className="muted none">Ничего не найдено</li>}</ul>
      </div>
    </div>
  )
}

function Home({ groups, modules }: { groups: [string, ModuleInfo[]][]; modules: ModuleInfo[] }) {
  const ready = modules.filter(m => m.web).length
  return (
    <>
      <header className="module-head"><div>
        <h1>База ПХГ</h1>
        <p className="lede">Скрипты подготовки и анализа данных ПХГ в одном окне: выберите модуль слева или найдите его по Ctrl+K.
          С веб-формой работают {ready} из {modules.length} модулей, остальные пока запускаются из консоли.</p>
      </div></header>
      {groups.map(([group, items]) => (
        <section key={group} className="group">
          <h2>{group}</h2>
          <div className="cards">{items.map(m => (
            <a key={m.id} className="card tile" href={'#/' + m.id}>
              <b>{m.title}</b><span className="muted">{m.description}</span>
              <span className={'chip small ' + (m.web ? 'done' : 'idle')}>{m.web ? 'Веб-форма' : 'Консоль'}</span>
            </a>
          ))}</div>
        </section>
      ))}
    </>
  )
}

export default function App() {
  const [modules, setModules] = useState<ModuleInfo[]>([])
  const [loaded, setLoaded] = useState(false)
  const [route, setRoute] = useState(routeOf())
  const [error, setError] = useState('')
  const [search, setSearch] = useState(false)
  const collapsed = usePref(sidebarCollapsed)
  const currentTheme = usePref(theme)

  useEffect(() => {
    getModules().then(m => { setModules(m); setLoaded(true) }).catch(e => setError(String(e.message || e)))
    const onHash = () => setRoute(routeOf())
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K' || e.code === 'KeyK')) { e.preventDefault(); setSearch(o => !o) }
    }
    window.addEventListener('hashchange', onHash)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('hashchange', onHash); window.removeEventListener('keydown', onKey) }
  }, [])

  const groups = useMemo(() => {
    const g: Record<string, ModuleInfo[]> = {}
    for (const m of modules) (g[m.group] ||= []).push(m)
    return Object.entries(g)
  }, [modules])
  const module = modules.find(m => m.id === route)
  useEffect(() => { document.title = (module ? module.title + ' · ' : '') + 'База ПХГ' }, [module])

  if (error) return <div className="fatal"><h1>База ПХГ</h1><p>{error}</p></div>
  return (
    <div className={'shell' + (collapsed ? ' collapsed' : '')}>
      <aside className="sidebar">
        <div className="brand">
          <a href="#/" className="brand-link"><span className="brand-mark" aria-hidden="true" /><span className="brand-name">База ПХГ</span></a>
          <button type="button" className="side-toggle" onClick={() => sidebarCollapsed.set(!collapsed)}
            aria-expanded={!collapsed} title={collapsed ? 'Показать меню' : 'Свернуть меню'}>
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d={collapsed ? 'M6 3.5 10.5 8 6 12.5' : 'M10 3.5 5.5 8 10 12.5'} /></svg>
          </button>
        </div>
        <button type="button" className="side-search" onClick={() => setSearch(true)} title="Найти модуль (Ctrl+K)">
          <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5" /><path d="m10.5 10.5 3 3" /></svg>
          <span className="side-label">Найти модуль</span><kbd className="side-label">Ctrl K</kbd>
        </button>
        <nav aria-label="Модули">
          {groups.map(([group, items]) => (
            <section key={group}>
              <h2>{group}</h2>
              <ul>{items.map(m => (
                <li key={m.id}><a href={'#/' + m.id} aria-current={m.id === route ? 'page' : undefined} title={m.description}>
                  <span>{m.title}</span>{!m.web && <i className="badge">консоль</i>}</a></li>
              ))}</ul>
            </section>
          ))}
        </nav>
        <div className="theme-switch segmented" role="radiogroup" aria-label="Тема">
          {([['light', 'Светлая'], ['dark', 'Тёмная'], ['system', 'Авто']] as [Theme, string][]).map(([t, label]) => (
            <button key={t} type="button" role="radio" aria-checked={currentTheme === t} onClick={() => theme.set(t)}
              title={t === 'system' ? 'Как в системе' : label + ' тема'}>
              {t === 'light' ? <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" /></svg>
                : t === 'dark' ? <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5Z" /></svg>
                : <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="3" width="12" height="8" rx="1" /><path d="M6 13.5h4" /></svg>}
              <span className="side-label">{label}</span>
            </button>
          ))}
        </div>
      </aside>
      <Search modules={modules} open={search} onClose={() => setSearch(false)} />
      <main className="workspace">
        {!loaded ? <p className="muted">Загрузка…</p>
          : module ? <ModulePage key={module.id} module={module} />
          : <Home groups={groups} modules={modules} />}
      </main>
    </div>
  )
}
