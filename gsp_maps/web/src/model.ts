import type { GspData, SeasonData, WaterRec } from './api'

export const MONTH_SHORT = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
export const MONTH_NAME = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
/** Цвета месяцев: ряд Окабе–Ито, различимый и при нарушениях цветовосприятия; соседние месяцы сезона разведены по тону. */
export const MONTH_COLOR = ['#56b4e9', '#009e73', '#e69f00', '#f0e442', '#8c564b', '#6a3d9a', '#1b9e77', '#e7298a', '#7f7f7f', '#d55e00', '#cc79a7', '#0072b2']
export const GAS = '#e63946'
export const WATER = '#2f7fd0'

export const dayDate = (d: number) => new Date(d * 86400000)
export const fmtDay = (d: number) => {
  const t = dayDate(d)
  return String(t.getUTCDate()).padStart(2, '0') + '.' + String(t.getUTCMonth() + 1).padStart(2, '0') + '.' + t.getUTCFullYear()
}
export const monthOf = (d: number) => dayDate(d).getUTCMonth()
const nf = (digits: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: digits })
const nf0 = nf(0), nf1 = nf(1), nf2 = nf(2)
export const fmtInt = (v: number) => nf0.format(v)
export const fmtMln = (v: number) => nf2.format(v / 1e6)
export const fmtTh = (v: number) => nf1.format(v / 1e3)
export const fmtPct = (v: number) => nf1.format(v * 100) + ' %'
export const fmt1 = (v: number) => nf1.format(v)

export interface WellStat { total: number; mean: number; days: number }

/** Суточные расходы сезона и префиксные суммы: итоги по любому окну дат считаются за O(число скважин). */
export class SeasonCalc {
  nw: number; nd: number; wells: number[]; days: number[]; flow: number[][]
  cum: Float64Array; psum: Float64Array; cnt: Int32Array; index: Map<number, number>; daily: Float64Array
  constructor(d: SeasonData) {
    this.nw = d.wells.length; this.nd = d.days.length; this.wells = d.wells; this.days = d.days; this.flow = d.flow
    const w = this.nd + 1
    this.cum = new Float64Array(this.nw * w); this.psum = new Float64Array(this.nw * w); this.cnt = new Int32Array(this.nw * w)
    this.daily = new Float64Array(this.nd)
    this.index = new Map(d.wells.map((x, i) => [x, i]))
    for (let i = 0; i < this.nw; i++) {
      const row = d.flow[i], o = i * w
      for (let j = 0; j < this.nd; j++) {
        const v = row[j]
        this.cum[o + j + 1] = this.cum[o + j] + v
        this.psum[o + j + 1] = this.psum[o + j] + (v > 0 ? v : 0)
        this.cnt[o + j + 1] = this.cnt[o + j] + (v > 0 ? 1 : 0)
        this.daily[j] += v
      }
    }
  }
  stat(i: number, a: number, b: number): WellStat {
    const o = i * (this.nd + 1), n = this.cnt[o + b + 1] - this.cnt[o + a]
    const sp = this.psum[o + b + 1] - this.psum[o + a]
    return { total: this.cum[o + b + 1] - this.cum[o + a], mean: n > 0 ? sp / n : 0, days: n }
  }
  /** Первый и последний индексы дней, попадающие в диапазон дат. */
  clampWindow(a: number, b: number): [number, number] {
    const n = this.nd - 1
    return [Math.max(0, Math.min(n, a)), Math.max(0, Math.min(n, b))]
  }
  monthly(i: number, a: number, b: number): number[] {
    const out = new Array(12).fill(0)
    const row = this.flow[i]
    for (let j = a; j <= b; j++) if (row[j] > 0) out[monthOf(this.days[j])] += row[j]
    return out
  }
}

export interface WaterPoint { month: number; year: number; factor: number | null; flow: number | null; note: string }
/** Замеры воды по скважинам, попадающие в сезон (по месяцу замера) и в окно дат. */
export function waterByWell(water: WaterRec[], kind: string, season: string, d0: number, d1: number) {
  const out = new Map<number, WaterPoint[]>()
  const from = dayDate(d0), to = dayDate(d1)
  const lo = from.getUTCFullYear() * 12 + from.getUTCMonth(), hi = to.getUTCFullYear() * 12 + to.getUTCMonth()
  for (const r of water) {
    const [s, k] = seasonOf(r.month - 1, r.year)
    if (s !== season || k !== kind) continue
    const ym = r.year * 12 + (r.month - 1)
    if (ym < lo || ym > hi) continue
    const arr = out.get(r.well) || []
    arr.push({ month: r.month - 1, year: r.year, factor: r.factor, flow: r.flow, note: r.note })
    out.set(r.well, arr)
  }
  for (const arr of out.values()) arr.sort((p, q) => p.year * 12 + p.month - (q.year * 12 + q.month))
  return out
}
/** Сезон и вид по месяцу (0–11) и году — как get_season_from_month в старом скрипте. */
export function seasonOf(month0: number, year: number): [string, string] {
  const m = month0 + 1
  if (m >= 10) return [year + '-' + (year + 1), 'Отбор']
  if (m <= 4) return [year - 1 + '-' + year, 'Отбор']
  return [String(year), 'Закачка']
}

export interface Placed { well: number; i: number; x: number; y: number; src: string; dir: string }
/** Скважины сезона с координатами и расстояние между ближайшими соседями (по нему выбираются размеры кругов). */
export function place(g: GspData, calc: SeasonCalc) {
  const placed: Placed[] = [], unplaced: number[] = []
  calc.wells.forEach((w, i) => {
    const p = g.layout.wells[String(w)]
    if (p) placed.push({ well: w, i, x: p.x, y: -p.y, src: p.src, dir: p.dir })
    else unplaced.push(w)
  })
  let spacing = 1
  if (placed.length > 1) {
    const nn = placed.map(a => {
      let m = Infinity
      for (const b of placed) if (a !== b) { const d = Math.hypot(a.x - b.x, a.y - b.y); if (d > 0 && d < m) m = d }
      return m
    }).filter(Number.isFinite).sort((p, q) => p - q)
    spacing = nn.length ? nn[Math.floor(nn.length / 2)] : 1
  }
  const xs = placed.map(p => p.x), ys = placed.map(p => p.y)
  const bounds = placed.length ? { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) } : { x0: 0, x1: 1, y0: 0, y1: 1 }
  return { placed, unplaced, spacing, bounds }
}

export function sectorPath(cx: number, cy: number, r: number, a0: number, a1: number, r0 = 0) {
  if (a1 - a0 >= Math.PI * 2 - 1e-6) {
    return r0 > 0
      ? `M${cx - r},${cy}a${r},${r} 0 1 0 ${2 * r},0a${r},${r} 0 1 0 ${-2 * r},0ZM${cx - r0},${cy}a${r0},${r0} 0 1 1 ${2 * r0},0a${r0},${r0} 0 1 1 ${-2 * r0},0Z`
      : `M${cx - r},${cy}a${r},${r} 0 1 0 ${2 * r},0a${r},${r} 0 1 0 ${-2 * r},0Z`
  }
  const p = (rr: number, a: number) => [cx + rr * Math.sin(a), cy - rr * Math.cos(a)]
  const [x0, y0] = p(r, a0), [x1, y1] = p(r, a1), big = a1 - a0 > Math.PI ? 1 : 0
  if (r0 > 0) {
    const [x2, y2] = p(r0, a1), [x3, y3] = p(r0, a0)
    return `M${x0},${y0}A${r},${r} 0 ${big} 1 ${x1},${y1}L${x2},${y2}A${r0},${r0} 0 ${big} 0 ${x3},${y3}Z`
  }
  return `M${cx},${cy}L${x0},${y0}A${r},${r} 0 ${big} 1 ${x1},${y1}Z`
}

export function niceStep(span: number, target = 5) {
  const raw = span / target, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p
}
