// Пользовательские группы скважин на карте: скважины берутся из пресета фильтра (он общий во всех вкладках и программах,
// pxg_core/well_presets.py), оформление группы (цвет, размер круга, подпись) — своё у каждой группы.
// Решение за инженером: группа только выделяет скважины, ничего не прячет и не исключает; пересечение — выигрывает группа выше в списке.
import { useSyncExternalStore } from 'react'
import { presetSource, type WellPreset } from '../../../pxg_core/web-ui/wellPresets'
import { pref } from './prefs'

/** Что писать у кружка: как у всех скважин, номер, расход, «номер · расход», название группы или ничего. */
export type GroupLabel = 'auto' | 'num' | 'val' | 'both' | 'name' | 'none'
export const GROUP_LABELS: [GroupLabel, string][] = [['auto', 'как у остальных'], ['num', 'номер'], ['val', 'расход'], ['both', 'номер · расход'], ['name', 'название группы'], ['none', 'нет']]

export interface CustomGroup {
  id: string; name: string; on: boolean
  /** Пресет фильтра скважин, из которого берётся список скважин. */
  preset: string
  color: string
  /** Множитель радиуса круга относительно обычного. */
  size: number
  label: GroupLabel
  /** Множитель размера подписи и её цвет («» — как у остальных). */
  labelSize: number
  labelColor: string
}

export const GROUP_COLORS = ['#e4572e', '#7a3db8', '#1b9e77', '#d4a017', '#2a6fdb', '#c2185b']
const HEX = /^#[0-9a-f]{6}$/i
const num = (v: unknown, lo: number, hi: number, d: number) => { const x = Number(v); return Number.isFinite(x) && x >= lo && x <= hi ? x : d }

export function newGroup(index: number, preset = '', name = ''): CustomGroup {
  return { id: Math.random().toString(36).slice(2, 10), name: name || `Группа ${index + 1}`, on: true, preset, color: GROUP_COLORS[index % GROUP_COLORS.length], size: 1.4, label: 'auto', labelSize: 1, labelColor: '' }
}

/** Восстановление из localStorage: лишнее отбрасывается, повреждённые поля берут значения по умолчанию. */
export function parseGroups(raw: unknown): CustomGroup[] {
  if (!Array.isArray(raw)) return []
  const out: CustomGroup[] = []
  raw.forEach((x, i) => {
    if (!x || typeof x !== 'object') return
    const o = x as Record<string, unknown>, d = newGroup(i)
    out.push({
      id: typeof o.id === 'string' && o.id ? o.id : d.id, name: typeof o.name === 'string' && o.name.trim() ? o.name : d.name, on: o.on !== false,
      preset: typeof o.preset === 'string' ? o.preset : '', color: HEX.test(String(o.color)) ? String(o.color) : d.color, size: num(o.size, 0.4, 4, 1.4),
      label: GROUP_LABELS.some(([k]) => k === o.label) ? o.label as GroupLabel : 'auto', labelSize: num(o.labelSize, 0.5, 2.5, 1), labelColor: HEX.test(String(o.labelColor)) ? String(o.labelColor) : '',
    })
  })
  return out
}

export const customGroups = pref<CustomGroup[]>('gsp.customGroups', [], parseGroups)

/** Скважина → оформляющая её группа: берётся первая включённая группа, в пресете которой есть скважина. Номера из пресета приводятся как «31», «31.0» → 31. */
export function groupOfWells(groups: CustomGroup[], presets: WellPreset[]): Map<number, CustomGroup> {
  const byId = new Map(presets.map(p => [p.id, p]))
  const out = new Map<number, CustomGroup>()
  for (const g of groups) {
    if (!g.on) continue
    for (const w of byId.get(g.preset)?.wells ?? []) {
      const n = Number(w)
      if (Number.isFinite(n) && !out.has(n)) out.set(n, g)
    }
  }
  return out
}

/** Текст подписи скважины группы; `fallback` — подпись, которая была бы без группы (режим «как у остальных»), `flow` — подпись расхода (пусто — расхода нет). */
export function groupLabel(g: CustomGroup, well: number, fallback: string, flow: string): string {
  switch (g.label) {
    case 'num': return String(well)
    case 'val': return flow || String(well)
    case 'both': return flow ? `${well} · ${flow}` : String(well)
    case 'name': return g.name
    case 'none': return ''
    default: return fallback
  }
}

// Список пресетов фильтра один на приложение; обновляется при открытии панели групп и после сохранения нового пресета в фильтре.
let presets: WellPreset[] = []
let error = ''
const subs = new Set<() => void>()
const snapshot = { get: () => presets, subscribe: (cb: () => void) => { subs.add(cb); return () => { subs.delete(cb) } } }
export const usePresets = (): WellPreset[] => useSyncExternalStore(snapshot.subscribe, snapshot.get)
export const presetsError = () => error
export function reloadPresets(): Promise<void> {
  return presetSource().list().then(p => { presets = p; error = '' }).catch(e => { error = String(e?.message || e) }).then(() => { subs.forEach(s => s()) })
}
void reloadPresets()
