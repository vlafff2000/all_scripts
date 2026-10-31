// Фильтр скважин вкладки: группы и скважины пересекаются (логика «И», как в Газовом Атласе). Состояние у каждой вкладки своё
// (useWellFilter хранит его по ключу вкладки), общие у всех вкладок и программ только пресеты скважин (pxg_core/well_presets.py).
// Решение за инженером: фильтр только прячет скважины в этой вкладке, снимается и меняется вручную; видно «N из M скв.».
// Подключение: const [filter, setFilter] = useWellFilter('map'); const keep = wellKeeper(filter, groupOf); <WellFilter ... />.
import { useEffect, useMemo, useState } from 'react'
import { MultiSelect } from './MultiSelect'
import './multiselect.css'
import './wellfilter.css'
import { presetSource, type PresetSource, type WellPreset } from './wellPresets'
import './wellfilter.css'

export interface WellFilterValue { groups: string[]; wells: string[] }
export type { WellPreset }

const isActive = (f: WellFilterValue | null | undefined) => Boolean(f && (f.groups.length || f.wells.length))

const readStored = (key: string): WellFilterValue | null => {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || 'null')
    const clean = { groups: (raw?.groups ?? []).map(String), wells: (raw?.wells ?? []).map(String) }
    return isActive(clean) ? clean : null
  } catch { return null }
}

/** Фильтр вкладки в localStorage (ключ вкладки): другие вкладки его не видят, а второе окно программы получает. Пустой фильтр — null. */
export function useWellFilter(tab: string): [WellFilterValue | null, (v: WellFilterValue | null) => void] {
  const key = 'pxg.wellfilter.' + tab
  const [state, setState] = useState<{ key: string; value: WellFilterValue | null }>(() => ({ key, value: readStored(key) }))
  // вкладка сменилась — берём фильтр новой вкладки сразу, без кадра со старым
  const value = useMemo(() => (state.key === key ? state.value : readStored(key)), [state, key])
  // второе окно программы изменило фильтр этой вкладки
  useEffect(() => {
    const onStorage = (e: StorageEvent) => { if (e.key === key && e.storageArea === localStorage) setState({ key, value: readStored(key) }) }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [key])
  const save = (v: WellFilterValue | null) => {
    const next = isActive(v) ? v : null
    setState({ key, value: next })
    try { if (next) localStorage.setItem(key, JSON.stringify(next)); else localStorage.removeItem(key) } catch { /* без хранилища фильтр живёт до перезагрузки */ }
  }
  return [value, save]
}

/** Остаётся ли скважина после фильтра: из выбранных групп и из выбранных скважин (если выбраны и те и другие, нужны оба условия). */
export function wellKeeper(filter: WellFilterValue | null | undefined, groupOf: (well: string) => string | undefined): (well: string | number) => boolean {
  if (!isActive(filter)) return () => true
  const groups = new Set(filter!.groups), wells = new Set(filter!.wells)
  return well => {
    const w = String(well)
    return (!groups.size || groups.has(groupOf(w) ?? 'Без группы')) && (!wells.size || wells.has(w))
  }
}

/** Короткая подпись для свёрнутых строк параметров. */
export const wellFilterSummary = (f: WellFilterValue | null | undefined) =>
  isActive(f) ? `Фильтр скважин: групп ${f!.groups.length}, скважин ${f!.wells.length}` : ''

interface Props {
  tab: string                                 // для подписи «действует только на эту вкладку»
  wells: string[]                             // все скважины вкладки
  groups: string[]                            // все группы вкладки (пусто — у вкладки нет групп)
  groupOf: (well: string) => string | undefined
  value: WellFilterValue | null
  onChange: (v: WellFilterValue | null) => void
  builtin?: WellPreset[]                      // готовые пресеты программы (по группам и т. п.), поверх общих
  presets?: PresetSource                      // откуда брать общие пресеты (по умолчанию /api/well-presets)
}

export function WellFilter({ wells, groups, groupOf, value, onChange, builtin = [], presets: source = presetSource() }: Props) {
  const [open, setOpen] = useState(false)
  const [g, setG] = useState<string[]>([])           // черновик, применяется кнопкой «Применить»
  const [w, setW] = useState<string[]>([])
  const [presets, setPresets] = useState<WellPreset[]>([])
  const [error, setError] = useState('')
  const active = isActive(value)
  const keep = useMemo(() => wellKeeper(value, groupOf), [value, groupOf])
  const shown = useMemo(() => wells.filter(keep).length, [wells, keep])

  useEffect(() => {
    if (!open) return
    source.list().then(setPresets).catch(() => setPresets([]))
  }, [open, source])

  const openPanel = () => { setG(value?.groups ?? []); setW(value?.wells ?? []); setError(''); setOpen(o => !o) }
  const apply = (groupsNext: string[], wellsNext: string[]) => {
    onChange(groupsNext.length || wellsNext.length ? { groups: groupsNext, wells: wellsNext } : null)
    setOpen(false)
  }
  const all = [...builtin, ...presets]
  const pickPreset = (id: string) => {
    const p = all.find(x => x.id === id)
    if (p) { setG([]); setW(p.wells.filter(x => wells.includes(x))) }
  }
  return (
    <div className={'multi well-filter' + (active ? ' active' : '')}>
      <button type="button" className="field-button" aria-expanded={open} onClick={openPanel}
        title="Группы и скважины пересекаются. Фильтр действует только на эту вкладку; пресеты общие у всех вкладок и программ.">
        <span className="field-label">Фильтр скважин</span>
        <span className="field-value">{active ? `${shown} из ${wells.length} скв.` : 'все'}</span>
      </button>
      {open && (
        <div className="popover well-filter-panel" role="dialog" aria-label="Фильтр скважин">
          <p className="well-filter-hint">
            Действует только на эту вкладку. Остаются скважины выбранных групп из выбранных скважин; пусто — без ограничений.
            Пресеты общие: их видно на всех вкладках.
          </p>
          <div className="well-filter-fields">
            {groups.length > 0 && <MultiSelect label="Группы" options={groups} value={g} onChange={setG} emptyMeaning="все" />}
            <MultiSelect label="Скважины" options={wells} value={w} onChange={setW} emptyMeaning="все" prefix="№ " presets={source} />
          </div>
          <label className="field well-filter-preset">
            <span className="field-label">Применить пресет</span>
            <select value="" onChange={e => pickPreset(e.target.value)} disabled={!all.length}>
              <option value="" />
              {all.map(p => <option key={p.id} value={p.id}>{p.label} ({p.wells.length})</option>)}
            </select>
          </label>
          {error && <p className="well-filter-error" role="alert">{error}</p>}
          <div className="well-filter-actions">
            <button type="button" className="primary" onClick={() => apply(g, w)}>Применить</button>
            <button type="button" onClick={() => apply([], [])} disabled={!active}>Снять фильтр</button>
            <button type="button" className="quiet" onClick={() => setOpen(false)}>Отмена</button>
          </div>
        </div>
      )}
    </div>
  )
}
