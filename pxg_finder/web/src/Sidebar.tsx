import { useMemo } from 'react'
import { baseName, dirName, post } from './api'
import type { Favs, Place } from './api'
import { COLOR_HEX } from './types'
import type { MetaMap } from './types'

interface Props {
  places: Place[]; favs: Favs; meta: MetaMap; current: string
  go: (p: string) => void; onFavChanged: () => void; addFav: () => void; editMeta: (p: string) => void
  openTrash: () => void; openIndex: () => void; openDups: () => void
}
const same = (a: string, b: string) => a.replace(/\//g, '\\').toLowerCase() === b.replace(/\//g, '\\').toLowerCase()

export default function Sidebar(p: Props) {
  const tagged = useMemo(() => Object.entries(p.meta).sort((a, b) => baseName(a[0]).localeCompare(baseName(b[0]), 'ru')), [p.meta])
  const fav = (act: string, path: string, name = '') => post('/api/fs/favorites', { action: act, path, name }).then(p.onFavChanged)
  const Btn = ({ path, label, sub, icon }: { path: string; label: string; sub?: string; icon?: string }) => (
    <button className={same(path, p.current) ? 'on' : ''} title={path} onClick={() => p.go(path)}><span>{icon ? icon + ' ' : ''}{label}</span>{sub && <span className="fx-pp">{sub}</span>}</button>
  )
  return (
    <nav className="fx-side">
      <div className="fx-cap">Избранное <button className="fx-mini" title="Добавить путь вручную" onClick={p.addFav}>＋</button></div>
      {p.favs.favorites.map(f => (
        <div key={f.path} className="fx-fav">
          <Btn path={f.path} label={f.name} sub={f.path} icon={f.network ? '🌐' : '⭐'} />
          <span className="fx-fa"><button title="Переименовать" onClick={() => { const n = window.prompt('Название', f.name); if (n) void fav('rename', f.path, n) }}>✎</button><button title="Убрать" onClick={() => void fav('remove', f.path)}>×</button></span>
        </div>
      ))}
      {!p.favs.favorites.length && <div className="fx-hint">Нажмите ☆ у пути или ＋, чтобы добавить папку (в том числе сетевую).</div>}
      {p.favs.frequent.length > 0 && <div className="fx-cap">Часто посещаемые</div>}
      {p.favs.frequent.map(f => (
        <div key={f.path} className="fx-fav">
          <Btn path={f.path} label={f.name} sub={f.path} icon={f.network ? '🌐' : '🕘'} />
          <span className="fx-fa"><button title="В избранное" onClick={() => void fav('add', f.path)}>☆</button><button title="Скрыть" onClick={() => void fav('hide', f.path)}>×</button></span>
        </div>
      ))}
      <div className="fx-cap">Места</div>
      {p.places.map(pl => <Btn key={pl.path} path={pl.path} label={pl.name} icon={pl.kind === 'network' ? '🌐' : pl.kind === 'drive' ? '💽' : pl.kind === 'home' ? '🏠' : '📁'} />)}
      {tagged.length > 0 && <div className="fx-cap">Метки</div>}
      {tagged.map(([path, m]) => (
        <div key={path} className="fx-fav">
          <button title={path + (m.note ? '\n' + m.note : '')} onClick={() => p.go(path)}>
            <span>{m.color && <i className="fx-dot" style={{ background: COLOR_HEX[m.color] }} />}{baseName(path)}</span>
            <span className="fx-pp">{(m.tags || []).join(', ') || dirName(path)}</span>
          </button>
          <span className="fx-fa"><button title="Изменить метки" onClick={() => p.editMeta(path)}>✎</button></span>
        </div>
      ))}
      <div className="fx-cap">Инструменты</div>
      <button onClick={p.openIndex}><span>⚡ Индекс (быстрый поиск)</span></button>
      <button onClick={p.openDups}><span>♊ Дубликаты в папке</span></button>
      <button onClick={p.openTrash}><span>🗑 Корзина программы</span></button>
    </nav>
  )
}
