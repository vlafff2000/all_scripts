import { useEffect, useRef, useState } from 'react'
import { emptySearch } from './types'
import type { SearchSpec } from './types'

const TYPES: [string, string][] = [['excel', 'Excel/CSV'], ['word', 'Word'], ['pdf', 'PDF'], ['image', 'Картинки'], ['text', 'Текст'], ['archive', 'Архивы'], ['presentation', 'Презентации'], ['model', 'Файлы модели']]

interface Props { folder: string; spec?: SearchSpec; indexed: (folder: string) => boolean; onSearch: (s: SearchSpec) => void; onClear: () => void; inputRef: React.RefObject<HTMLInputElement | null> }

export default function SearchBar({ folder, spec, indexed, onSearch, onClear, inputRef }: Props) {
  const [s, setS] = useState<SearchSpec>(spec ?? emptySearch(folder))
  const [more, setMore] = useState(false)
  const timer = useRef(0)
  // вкладка со своим поиском: показываем его параметры
  useEffect(() => { if (spec) setS(spec) }, [spec])
  const set = (p: Partial<SearchSpec>) => setS(v => ({ ...v, ...p }))
  const ready = (v: SearchSpec) => !!v.query.trim() || v.types.length > 0 || !!v.sizeMin || !!v.sizeMax || !!v.dateFrom || !!v.dateTo || v.want !== 'all'
  const go = (v: SearchSpec = s) => { if (ready(v)) onSearch({ ...v, root: folder }) }
  const change = (p: Partial<SearchSpec>) => {
    const v = { ...s, ...p }
    setS(v)
    window.clearTimeout(timer.current)
    if (indexed(folder) && v.useIndex && ready(v)) timer.current = window.setTimeout(() => go(v), 220) // по индексу ищем на ходу
  }
  const filtersOn = s.types.length > 0 || s.sizeMin || s.sizeMax || s.dateFrom || s.dateTo || s.want !== 'all' || s.regex || s.case || s.hidden || !s.useIndex

  return (
    <div className="fx-search">
      <div className="fx-sbox">
        <span>🔍</span>
        <input ref={inputRef} value={s.query} placeholder={`Поиск в «${folder.split(/[\\/]/).filter(Boolean).pop() || folder}»${indexed(folder) ? ' (по индексу)' : ''} — Ctrl+F`}
          onChange={e => change({ query: e.target.value })}
          onKeyDown={e => { if (e.key === 'Enter') { window.clearTimeout(timer.current); go() } if (e.key === 'Escape') { setS(v => ({ ...v, query: '' })); onClear(); (e.target as HTMLInputElement).blur() } }} />
        {s.query && <button className="fx-x" onClick={() => { set({ query: '' }); onClear() }}>✕</button>}
        <button className={'fx-fbtn' + (filtersOn ? ' on' : '')} onClick={() => setMore(m => !m)}>Фильтры{filtersOn ? ' •' : ''}</button>
      </div>
      {more && (
        <div className="fx-pop" onKeyDown={e => { if (e.key === 'Escape') setMore(false) }}>
          <div className="fx-chips">{TYPES.map(([k, n]) => <button key={k} className={s.types.includes(k) ? 'on' : ''} onClick={() => change({ types: s.types.includes(k) ? s.types.filter(x => x !== k) : [...s.types, k] })}>{n}</button>)}</div>
          <div className="fx-grid">
            <label>Что искать<select value={s.want} onChange={e => change({ want: e.target.value as SearchSpec['want'] })}><option value="all">файлы и папки</option><option value="files">только файлы</option><option value="folders">только папки</option></select></label>
            <label>Размер от<input value={s.sizeMin} placeholder="напр. 500kb" onChange={e => change({ sizeMin: e.target.value })} /></label>
            <label>Размер до<input value={s.sizeMax} placeholder="напр. 10mb" onChange={e => change({ sizeMax: e.target.value })} /></label>
            <label>Изменён с<input type="date" value={s.dateFrom} onChange={e => change({ dateFrom: e.target.value })} /></label>
            <label>Изменён по<input type="date" value={s.dateTo} onChange={e => change({ dateTo: e.target.value })} /></label>
          </div>
          <div className="fx-checks">
            <label><input type="checkbox" checked={s.regex} onChange={e => change({ regex: e.target.checked })} /> регулярное выражение</label>
            <label><input type="checkbox" checked={s.case} onChange={e => change({ case: e.target.checked })} /> учитывать регистр</label>
            <label><input type="checkbox" checked={s.hidden} onChange={e => change({ hidden: e.target.checked })} /> скрытые</label>
            <label title="Если эта папка внесена в индекс, поиск идёт по нему"><input type="checkbox" checked={s.useIndex} onChange={e => change({ useIndex: e.target.checked })} /> по индексу, если есть</label>
          </div>
          <div className="fx-btns"><button onClick={() => { setS(emptySearch(folder)); onClear() }}>Сбросить</button><button className="primary" onClick={() => { go(); setMore(false) }}>Искать</button></div>
        </div>
      )}
    </div>
  )
}
