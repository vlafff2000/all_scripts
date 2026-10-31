import { WorkspacePanel } from './WorkspacePanel'
import { Icon } from '../../../pxg_core/web-ui/Icon'
import { useEffect, useMemo, useState } from 'react'
import { getModules, type ModuleInfo } from './api'
import ModulePage from './ModulePage'
import { sidebarCollapsed, theme, usePref, type Theme } from './prefs'
import { WindowButtons } from '../../../pxg_core/web-ui/WindowButtons'

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
        <h1>Работа с исходными данными</h1>
        <p className="lede">Скрипты подготовки и анализа данных ПХГ в одном окне: выберите модуль слева или найдите его по Ctrl+K.
          С веб-формой работают {ready} из {modules.length}. Остальное — скрипты будущих приложений («ГИС и ГВК», «Отчёты и файлы», группа «ГДМ»), они лежат в папке apps и пока запускаются из консоли.</p>
      </div></header>
      <WorkspacePanel />
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
  useEffect(() => { document.title = (module ? module.title + ' · ' : '') + 'Работа с исходными данными' }, [module])

  if (error) return <div className="fatal"><h1>Работа с исходными данными</h1><p>{error}</p></div>
  return (
    <div className={'shell' + (collapsed ? ' collapsed' : '')}>
      <aside className="sidebar">
        <div className="brand">
          <a href="#/" className="brand-link"><span className="brand-mark" aria-hidden="true" /><span className="brand-name">Работа с исходными данными</span></a>
          <button type="button" className="side-toggle" onClick={() => sidebarCollapsed.set(!collapsed)}
            aria-expanded={!collapsed} title={collapsed ? 'Показать меню' : 'Свернуть меню'}>
            <Icon name={collapsed ? 'chevron-right' : 'chevron-left'} />
          </button>
        </div>
        <button type="button" className="side-search" onClick={() => setSearch(true)} title="Найти модуль (Ctrl+K)">
          <Icon name="search" />
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
        <WindowButtons page={route} />
        <div className="theme-switch segmented" role="radiogroup" aria-label="Тема">
          {([['light', 'Светлая'], ['dark', 'Тёмная'], ['system', 'Авто']] as [Theme, string][]).map(([t, label]) => (
            <button key={t} type="button" role="radio" aria-checked={currentTheme === t} onClick={() => theme.set(t)}
              title={t === 'system' ? 'Как в системе' : label + ' тема'}>
              <Icon name={t === 'light' ? 'sun' : t === 'dark' ? 'moon' : 'screen'} />
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
