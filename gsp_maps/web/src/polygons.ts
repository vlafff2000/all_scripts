import { useSyncExternalStore } from 'react'
import { getPolygons, type Poly } from './api'
import { pref } from './prefs'

/** Оформление многоугольника: что переопределено инженером (остальное — по умолчанию, цвет по порядку в файле). */
export interface PolyStyle {
  show: boolean; stroke: string; fill: string; fillOpacity: number; width: number; dash: boolean
  marker: 'none' | 'circle' | 'square' | 'cross'; markerSize: number; markerColor: string
}
export const POLY_COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e', '#17becf', '#8c564b', '#e377c2']
export const DEFAULT_STYLE: Omit<PolyStyle, 'stroke' | 'fill' | 'markerColor'> = { show: true, fillOpacity: 0.08, width: 1.5, dash: false, marker: 'none', markerSize: 4 }
export const MARKERS: [PolyStyle['marker'], string][] = [['none', 'нет'], ['circle', 'кружок'], ['square', 'квадрат'], ['cross', 'крест']]

/** Переопределения стиля по имени многоугольника (localStorage, как остальные настройки Карт). */
export const polyStyles = pref<Record<string, Partial<PolyStyle>>>('gsp.polystyle', {}, raw => (raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, Partial<PolyStyle>> : {}))

export function styleOf(name: string, index: number, overrides: Record<string, Partial<PolyStyle>>): PolyStyle {
  const color = POLY_COLORS[index % POLY_COLORS.length]
  return { ...DEFAULT_STYLE, stroke: color, fill: color, markerColor: color, ...overrides[name] }
}

export function setStyle(name: string, patch: Partial<PolyStyle>) {
  const all = polyStyles.get()
  polyStyles.set({ ...all, [name]: { ...all[name], ...patch } })
}

export function resetStyle(name: string) {
  const { [name]: _drop, ...rest } = polyStyles.get()
  polyStyles.set(rest)
}

/** Загруженные из файла многоугольники: один общий список на приложение, обновляется после смены файла. */
interface PolyState { polys: Poly[]; warnings: string[] }
let state: PolyState = { polys: [], warnings: [] }
const subs = new Set<() => void>()
const polyStore = { get: () => state, subscribe: (cb: () => void) => { subs.add(cb); return () => { subs.delete(cb) } } }

export const usePolygons = (): PolyState => useSyncExternalStore(polyStore.subscribe, polyStore.get)

export async function refreshPolygons() {
  try {
    const r = await getPolygons()
    state = { polys: r.polygons, warnings: r.warnings }
  } catch (e) {
    state = { polys: [], warnings: ['Многоугольники не прочитаны: ' + String((e as Error).message || e)] }
  }
  subs.forEach(f => f())
}
