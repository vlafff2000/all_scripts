import { useEffect } from 'react'
import { GROUP_LABELS, customGroups, newGroup, presetsError, reloadPresets, usePresets, type CustomGroup, type GroupLabel } from './customGroups'

/** «Вид карты → Пользовательские группы»: список скважин берётся из пресета фильтра (общего), оформление у каждой группы своё. */
export default function CustomGroupsPanel({ groups, covered }: { groups: CustomGroup[]; covered: Map<string, number> }) {
  const presets = usePresets()
  useEffect(() => { void reloadPresets() }, [])
  const patch = (id: string, p: Partial<CustomGroup>) => customGroups.set(groups.map(g => (g.id === id ? { ...g, ...p } : g)))
  const move = (i: number, d: number) => { const j = i + d; if (j < 0 || j >= groups.length) return; const a = [...groups]; [a[i], a[j]] = [a[j], a[i]]; customGroups.set(a) }
  const err = presetsError()
  return (
    <>
      <p className="muted small">Скважины группы берутся из пресета фильтра скважин (список сохраняется в «Фильтре скважин» и виден во всех вкладках и программах). Группа только выделяет скважины и ничего не прячет. Если скважина есть в нескольких группах, действует группа выше в списке. При раскраске по значению цвет группы показан обводкой.</p>
      {err && <p className="muted small" role="alert">Пресеты не загружены: {err}</p>}
      {groups.map((g, i) => {
        const p = presets.find(x => x.id === g.preset)
        return (
          <details key={g.id} className="pal-det" open={!g.preset}>
            <summary><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: g.color, opacity: g.on ? 1 : 0.35, marginRight: 6 }} />{g.name}{g.on ? '' : ' · выключена'}{p ? ` · ${covered.get(g.id) ?? 0} из ${p.wells.length} скв. на карте` : ''}</summary>
            <label className="check"><input type="checkbox" checked={g.on} onChange={e => patch(g.id, { on: e.target.checked })} />Показывать выделение</label>
            <label className="row"><span>Название</span><input type="text" value={g.name} onChange={e => patch(g.id, { name: e.target.value })} aria-label="Название группы" /></label>
            <label className="row"><span>Пресет</span>
              <select value={g.preset} onChange={e => { const pr = presets.find(x => x.id === e.target.value); patch(g.id, { preset: e.target.value, ...(pr && /^Группа \d+$/.test(g.name) ? { name: pr.label } : {}) }) }} aria-label="Пресет скважин группы">
                <option value="">— выберите —</option>
                {g.preset && !p && <option value={g.preset}>пресет удалён</option>}
                {presets.map(x => <option key={x.id} value={x.id}>{x.label} ({x.wells.length})</option>)}</select></label>
            {!presets.length && !err && <p className="muted small">Пресетов нет: выберите скважины в «Фильтре скважин» и сохраните список пресетом.</p>}
            {g.preset && !p && <p className="muted small">Пресет не найден (удалён или проект другой): выберите другой.</p>}
            <label className="row"><span>Цвет круга</span><input type="color" value={g.color} onChange={e => patch(g.id, { color: e.target.value })} aria-label="Цвет круга группы" /></label>
            <label className="row"><span>Размер круга</span><input type="range" min={0.4} max={4} step={0.1} value={g.size} onChange={e => patch(g.id, { size: Number(e.target.value) })} aria-label="Размер круга группы" /><span className="muted small">×{g.size.toFixed(1)}</span></label>
            <label className="row"><span>Подпись</span>
              <select value={g.label} onChange={e => patch(g.id, { label: e.target.value as GroupLabel })} aria-label="Формат подписи группы">
                {GROUP_LABELS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
            {g.label !== 'none' && <>
              <label className="row"><span>Размер подписи</span><input type="range" min={0.5} max={2.5} step={0.1} value={g.labelSize} onChange={e => patch(g.id, { labelSize: Number(e.target.value) })} aria-label="Размер подписи группы" /></label>
              <label className="row"><span>Цвет подписи</span><input type="color" value={g.labelColor || '#1b2a31'} onChange={e => patch(g.id, { labelColor: e.target.value })} aria-label="Цвет подписи группы" />
                <button type="button" className="quiet" onClick={() => patch(g.id, { labelColor: '' })} disabled={!g.labelColor}>Как у остальных</button></label>
            </>}
            <div className="row">
              <button type="button" className="quiet" onClick={() => move(i, -1)} disabled={i === 0} title="Выше: приоритет при пересечении">↑</button>
              <button type="button" className="quiet" onClick={() => move(i, 1)} disabled={i === groups.length - 1} title="Ниже">↓</button>
              <button type="button" className="quiet" onClick={() => customGroups.set(groups.filter(x => x.id !== g.id))}>Удалить группу</button>
            </div>
          </details>
        )
      })}
      <button type="button" onClick={() => customGroups.set([...groups, newGroup(groups.length)])}>Добавить группу</button>
    </>
  )
}
