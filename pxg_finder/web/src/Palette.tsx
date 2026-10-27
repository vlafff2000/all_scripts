import { useEffect, useMemo, useRef, useState } from 'react'

export interface Cmd { id: string; title: string; hint?: string; group?: string; run: () => void }

export default function Palette({ cmds, paths, onGo, onSearch, onClose }: { cmds: Cmd[]; paths: { path: string; label: string }[]; onGo: (p: string) => void; onSearch: (q: string) => void; onClose: () => void }) {
  const [q, setQ] = useState('')
  const [k, setK] = useState(0)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => ref.current?.focus(), [])
  const items = useMemo<Cmd[]>(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean)
    const hit = (t: string) => words.every(w => t.toLowerCase().includes(w))
    const out: Cmd[] = []
    const t = q.trim()
    if (t && /[\\/:]/.test(t)) out.push({ id: 'go', group: 'Путь', title: 'Перейти: ' + t, run: () => onGo(t) })
    out.push(...cmds.filter(c => hit(c.title + ' ' + (c.hint || ''))))
    out.push(...paths.filter(p => hit(p.path + ' ' + p.label)).slice(0, 12).map(p => ({ id: 'p:' + p.path, group: 'Папки', title: p.label, hint: p.path, run: () => onGo(p.path) })))
    if (t) out.push({ id: 'find', group: 'Поиск', title: `Искать «${t}» в текущей папке`, run: () => onSearch(t) })
    return out
  }, [q, cmds, paths, onGo, onSearch])
  useEffect(() => setK(0), [q])
  const run = (c?: Cmd) => { if (c) { onClose(); window.setTimeout(c.run, 0) } }
  return (
    <div className="fx-back top" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="fx-pal">
        <input ref={ref} value={q} placeholder="Команда, папка или путь…" onChange={e => setQ(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Escape') onClose()
            else if (e.key === 'ArrowDown') { e.preventDefault(); setK(v => Math.min(items.length - 1, v + 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setK(v => Math.max(0, v - 1)) }
            else if (e.key === 'Enter') { e.preventDefault(); run(items[k]) }
          }} />
        <div className="fx-pall">
          {items.map((c, i) => (
            <div key={c.id} className={'fx-pi' + (i === k ? ' on' : '')} onMouseEnter={() => setK(i)} onClick={() => run(c)} ref={el => { if (el && i === k) el.scrollIntoView({ block: 'nearest' }) }}>
              <span>{c.title}</span><small>{c.hint || c.group || ''}</small>
            </div>
          ))}
          {!items.length && <div className="fx-pi muted">Ничего не найдено</div>}
        </div>
      </div>
    </div>
  )
}
