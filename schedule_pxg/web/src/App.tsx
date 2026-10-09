import { useEffect, useState } from 'react'
import { sidebarCollapsed, theme, usePref, type Theme } from './prefs'
import Averaging from './Averaging'
import Charts from './Charts'
import Results from './Results'
import History from './History'
import Scenarios from './Scenarios'
import Strategies from './Strategies'
import TechMaps from './TechMaps'
import Import from './Import'
import { AppState, getState } from './api'

type Tab = 'import' | 'techmaps' | 'averaging' | 'scenarios' | 'strategies' | 'charts' | 'results' | 'history'
const NAV: [string, [Tab, string, string][]][] = [
  ['Данные', [['import', 'Импорт', 'M8 2v8M4.5 6.5 8 10l3.5-3.5M2.5 11v2.5h11V11'], ['techmaps', 'Тех.карты', 'M2.5 3h11v10h-11zM2.5 7h11M6.5 3v10'], ['averaging', 'Осреднение', 'M2 8h2.5l1.5-4 2 8 1.5-4H14']]],
  ['Расчёт', [['scenarios', 'Сценарии', 'M3 3v4a3 3 0 0 0 3 3h7M3 7v6'], ['strategies', 'Стратегии', 'M2.5 13V8M6.5 13V4M10.5 13V6.5M14 13H2']]],
  ['Результат', [['charts', 'Графики', 'M2 13h12M3.5 10 7 6.5l2.5 2.5L13 4.5'], ['results', 'Результаты расчёта', 'M3 2.5h10v11H3zM6 6h4M6 9h4'], ['history', 'История', 'M3 8a5 5 0 1 0 1.6-3.7M3 2.5v3h3M8 5v3.5l2 1.5']]],
]
const tabOf = (): Tab => {
  const h = decodeURIComponent(location.hash.replace(/^#\/?/, ''))
  return NAV.some(([, items]) => items.some(i => i[0] === h)) ? (h as Tab) : 'import'
}

export default function App() {
  const [tab, setTabState] = useState<Tab>(tabOf())
  const collapsed = usePref(sidebarCollapsed)
  const currentTheme = usePref(theme)
  useEffect(() => {
    const onHash = () => setTabState(tabOf())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => { document.title = NAV.flatMap(([, i]) => i).find(i => i[0] === tab)![1] + ' · Скедул ПХГ' }, [tab])
  const [st, setSt] = useState<AppState | null>(null)
  useEffect(() => { getState().then(setSt).catch(() => undefined) }, [])

  return (
    <div className={'shell' + (collapsed ? ' collapsed' : '')}>
      <aside className="sidebar">
        <div className="brand">
          <a href="#/" className="brand-link"><span className="brand-mark" aria-hidden="true" /><span className="brand-name">Скедул ПХГ</span></a>
          <button type="button" className="side-toggle" onClick={() => sidebarCollapsed.set(!collapsed)}
            aria-expanded={!collapsed} title={collapsed ? 'Показать меню' : 'Свернуть меню'}>
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d={collapsed ? 'M6 3.5 10.5 8 6 12.5' : 'M10 3.5 5.5 8 10 12.5'} /></svg>
          </button>
        </div>
        <nav aria-label="Разделы">
          {NAV.map(([group, items]) => (
            <section key={group}>
              <h2>{group}</h2>
              <ul>{items.map(([id, title, icon]) => (
                <li key={id}><a href={'#/' + id} aria-current={id === tab ? 'page' : undefined} title={title}>
                  <svg viewBox="0 0 16 16" aria-hidden="true"><path d={icon} /></svg><span className="side-label">{title}</span></a></li>
              ))}</ul>
            </section>
          ))}
        </nav>
        {st && !collapsed && <p className="muted small side-project" title={st.folder}>Проект: {st.folder}</p>}
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
      {tab === 'history' && st ? <History st={st} /> : tab === 'charts' && st ? <Charts st={st} /> : tab === 'results' && st ? <Results st={st} setSt={setSt} /> : tab === 'averaging' && st ? <Averaging st={st} /> : tab === 'scenarios' && st ? <Scenarios st={st} setSt={setSt} /> : tab === 'strategies' && st ? <Strategies st={st} setSt={setSt} /> : tab === 'techmaps' && st ? <TechMaps st={st} setSt={setSt} /> : st ? <Import st={st} setSt={setSt} /> : <main className="workspace" />}
    </div>
  )
}
