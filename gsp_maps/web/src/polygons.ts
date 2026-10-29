import { useSyncExternalStore } from 'react'
import { getPolygons, type Poly } from './api'
import { pref } from './prefs'
import type { Placed } from './model'

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

/** Аффинное преобразование: x' = a·x + b·y + c, y' = d·x + e·y + f. По умолчанию — отражение Y, как у скважин в XY. */
export interface Affine { a: number; b: number; c: number; d: number; e: number; f: number }
export const FLIP_Y: Affine = { a: 1, b: 0, c: 0, d: 0, e: -1, f: 0 }
export const applyAffine = (t: Affine, x: number, y: number): [number, number] => [t.a * x + t.b * y + t.c, t.d * x + t.e * y + t.f]

const det3 = (m: number[][]) =>
  m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])

/** Аффинное преобразование по трём парам точек (правило Крамера); null — точки на одной прямой. */
export function affineFrom3(src: [number, number][], dst: [number, number][]): Affine | null {
  const M = src.map(([x, y]) => [x, y, 1])
  const d = det3(M)
  const scale = Math.max(1, ...src.flat().map(Math.abs))
  if (src.length !== 3 || Math.abs(d) < 1e-9 * scale * scale) return null
  const solve = (v: number[]) => [0, 1, 2].map(j => det3(M.map((row, i) => row.map((x, k) => (k === j ? v[i] : x)))) / d)
  const [a, b, c] = solve(dst.map(p => p[0]))
  const [dd, e, f] = solve(dst.map(p => p[1]))
  return { a, b, c, d: dd, e, f }
}

/** Привязка по трём точкам: точка контура (X, Y из файла) и номер скважины, стоящей в той же точке на карте. */
export interface AlignPoint { x: number | null; y: number | null; well: number | null }
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
export const emptyAlign = (): AlignPoint[] => [0, 1, 2].map(() => ({ x: null, y: null, well: null }))
export const parseAlign = (raw: unknown): AlignPoint[] => (Array.isArray(raw) && raw.length === 3
  ? (raw as Partial<AlignPoint>[]).map(p => ({ x: num(p?.x), y: num(p?.y), well: num(p?.well) })) : emptyAlign())
export const polyAlign = pref<AlignPoint[]>('gsp.polyalign', emptyAlign(), parseAlign)

/** Преобразование контура в координаты карты и пояснение, что с привязкой. */
export function alignTransform(pts: AlignPoint[], placed: Placed[]): { t: Affine | null; status: string } {
  const filled = pts.filter(p => p.x !== null || p.y !== null || p.well !== null).length
  if (filled === 0) return { t: null, status: 'Привязки нет: координаты файла берутся как XY (Y с минусом), как у скважин.' }
  if (!pts.every(p => p.x !== null && p.y !== null && p.well !== null)) return { t: null, status: 'Заполните все три точки: X, Y из файла и номер скважины.' }
  const dst = pts.map(p => placed.find(q => q.well === p.well))
  const missing = pts.filter((_, i) => !dst[i]).map(p => p.well)
  if (missing.length) return { t: null, status: `Скважин нет на карте: ${missing.join(', ')}.` }
  const t = affineFrom3(pts.map(p => [p.x!, p.y!]), dst.map(q => [q!.x, q!.y]))
  return t ? { t, status: 'Привязка по трём точкам задана.' } : { t: null, status: 'Три точки лежат на одной прямой: выберите другие.' }
}
