import { ALL_GSP, type GspData, type SeasonData, type SeasonInfo, type WaterRec } from './api'
import type { SeasonScope } from './prefs'

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
  const box = (ps: Placed[]) => {
    const xs = ps.map(p => p.x), ys = ps.map(p => p.y)
    return ps.length ? { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) } : { x0: 0, x1: 1, y0: 0, y1: 1 }
  }
  // одиночные далёкие скважины не должны сжимать кадр: рамка строится по основной группе, остальные доступны кнопкой «Показать все»
  let core = placed
  if (placed.length >= 8) {
    const sorted = (v: number[]) => [...v].sort((p, q) => p - q)
    const cx = sorted(placed.map(p => p.x))[Math.floor(placed.length / 2)], cy = sorted(placed.map(p => p.y))[Math.floor(placed.length / 2)]
    const d = placed.map(p => Math.hypot(p.x - cx, p.y - cy)), sd = sorted(d)
    const q1 = sd[Math.floor(sd.length * 0.25)], q3 = sd[Math.floor(sd.length * 0.75)]
    const lim = Math.max(q3 + 2.5 * (q3 - q1), spacing * 8)
    core = placed.filter((_, k) => d[k] <= lim)
    if (core.length < placed.length * 0.6) core = placed
  }
  const far = placed.filter(p => !core.includes(p)).map(p => p.well)
  return { placed, unplaced, spacing, bounds: box(core), boundsAll: box(placed), far }
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

/** Цвета колец воды по месяцам: от голубого к фиолетовому, раньше — светлее. */
export const WATER_STOPS = ['#6dd3ee', '#2f9be0', '#2f6fd0', '#4a4fc4', '#7a3fb0']
/** Месяцы с водой в окне (год·12+месяц) по порядку и их цвета. */
export function waterMonths(water: Map<number, WaterPoint[]>): { list: number[]; color: Map<number, string> } {
  const set = new Set<number>()
  for (const pts of water.values()) for (const p of pts) if ((p.flow ?? 0) > 0) set.add(p.year * 12 + p.month)
  const list = [...set].sort((p, q) => p - q), color = new Map<number, string>()
  list.forEach((ym, i) => color.set(ym, rampColor(WATER_STOPS, list.length > 1 ? i / (list.length - 1) : 0.4)))
  return { list, color }
}

/** Какие сезоны брать для раскраски: один выбранный, отмеченные или все. */
export function scopeKeys(mode: SeasonScope, picked: string[], seasons: SeasonInfo[], season: string): string[] {
  if (mode === 'all') return seasons.map(s => s.key)
  if (mode === 'pick') { const k = seasons.map(s => s.key).filter(x => picked.includes(x)); if (k.length) return k }
  return [season]
}
export interface Scope { mode: SeasonScope; keys: string[]; calcs: Map<string, SeasonCalc> }

/** Раскраска карты: по умолчанию круги по расходу газа, остальные режимы красят скважины одной шкалой. */
export type Paint = 'flow' | 'entry' | 'depth' | 'wf'
export const PAINTS: [Paint, string][] = [
  ['flow', 'Расход газа'], ['entry', 'Ввод по дате'], ['depth', 'Глубина перфорации'], ['wf', 'Обводнённость'],
]
export interface PaintVal { v: number; label: string; tip: string }
export interface PaintData {
  vals: Map<number, PaintVal>; lo: number; hi: number; stops: string[]; title: string; fmt: (v: number) => string; note: string
  /** Подписи под шкалой в легенде: только края (для очерёдности) или ещё середина. */
  mid?: boolean; scopeNote?: string
}

export function rampColor(stops: string[], t: number): string {
  const x = Math.max(0, Math.min(1, t)) * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(x)), f = x - i
  const c = (s: string) => [1, 3, 5].map(k => parseInt(s.slice(k, k + 2), 16))
  const p = c(stops[i]), q = c(stops[i + 1])
  return '#' + p.map((v, k) => Math.round(v + (q[k] - v) * f).toString(16).padStart(2, '0')).join('')
}
// ввод: разноцветная шкала от жёлтого (первые) к тёмно-фиолетовому (последние), чтобы соседние по времени скважины различались
const ENTRY_STOPS = ['#f6d746', '#a0da39', '#36b779', '#25858e', '#3e4a89', '#46186a']
const DEPTH_STOPS = ['#c4e8e5', '#5fbab4', '#1b8780', '#0b4f4b']
const WF_STOPS = ['#cde2fb', '#6da7ec', '#256abf', '#0d366b']
/** Месяцы сезона на круге: порядковая шкала одного тёплого тона, раньше — светлее, позже — темнее. */
export const SEASON_STOPS = ['#f19a85', '#e2614f', '#c33a3f', '#8e2236', '#5c1529']
// на тёмном фоне тот же тон, но без самых тёмных ступеней: они сливались бы с фоном
export const SEASON_STOPS_DARK = ['#f7c2b4', '#f19a85', '#e2614f', '#c94347', '#a32d3f']

const seasonsWord = (n: number) => (n % 10 === 1 && n % 100 !== 11 ? 'сезону' : 'сезонам')
const scopeTitle = (sc: Scope | undefined, season: string, kind: string) =>
  !sc || sc.mode === 'one' ? `${kind.toLowerCase()} ${season}` : sc.mode === 'all' ? `среднее по всем сезонам (${sc.keys.length})` : `среднее по ${sc.keys.length} ${seasonsWord(sc.keys.length)}`

/** Значения выбранной раскраски по скважинам сезона. Скважины без значения в карту не попадают (рисуются серыми). */
export function paintFor(paint: Paint, g: GspData, calc: SeasonCalc, kind: string, season: string, a: number, b: number, scope?: Scope): PaintData | null {
  if (paint === 'flow') return null
  const vals = new Map<number, PaintVal>()
  const multi = !!scope && scope.mode !== 'one' && scope.keys.length > 0
  const keys = multi ? scope!.keys : [season]
  if (paint === 'entry') {
    // внутри ГСП важна очерёдность включения (цвет — место в ряду), для всего объекта — дни от начала сезона
    const byDays = g.gsp === ALL_GSP
    const info = new Map((g.seasons[kind as 'Отбор' | 'Закачка'] || []).map(s => [s.key, s]))
    const per = new Map<number, { frac: number[]; off: number[]; rank: number[]; of: number[]; keys: string[]; day: number[] }>()
    let used = 0
    for (const key of keys) {
      const c = key === season ? calc : scope?.calcs.get(key)
      if (!c) continue
      used++
      const start = info.get(key)?.start ?? c.days[0]
      const first: [number, number][] = []
      c.wells.forEach((w, i) => { const j = c.flow[i].findIndex(v => v > 0); if (j >= 0) first.push([c.days[j], w]) })
      first.sort((p, q) => p[0] - q[0] || p[1] - q[1])
      const dates = [...new Set(first.map(f => f[0]))]  // очередь считается по датам: скважины с одним днём ввода делят место
      first.forEach(([d, w]) => {
        const rank = dates.indexOf(d)
        const e = per.get(w) || { frac: [], off: [], rank: [], of: [], keys: [], day: [] }
        e.frac.push(dates.length > 1 ? rank / (dates.length - 1) : 0); e.off.push(d - start); e.rank.push(rank + 1); e.of.push(dates.length); e.keys.push(key); e.day.push(d)
        per.set(w, e)
      })
    }
    const mean = (v: number[]) => v.reduce((p, q) => p + q, 0) / v.length
    let hi = 1
    const raw = new Map<number, number>()
    per.forEach((e, w) => { const v = byDays ? mean(e.off) : mean(e.frac); raw.set(w, v); hi = Math.max(hi, v) })
    if (!byDays) hi = 1
    per.forEach((e, w) => {
      const v = raw.get(w)!
      if (!multi) {
        const d = e.day[0], off = e.off[0]
        vals.set(w, { v, label: byDays ? String(off) : String(e.rank[0]), tip: `Очередь ввода ${e.rank[0]} из ${e.of[0]}: ${fmtDay(d)}, на ${off}-й день от старта сезона` })
      } else {
        const m = mean(e.off), r = mean(e.rank)
        const list = e.keys.map((k, i) => `${k}: день ${e.off[i]}, очередь ${e.rank[i]}`).slice(0, 6).join('; ') + (e.keys.length > 6 ? '…' : '')
        vals.set(w, { v, label: byDays ? String(Math.round(m)) : String(Math.round(r)),
          tip: `Ввод в среднем на ${Math.round(m)}-й день от старта, очередь в среднем ${r.toFixed(1).replace('.', ',')} (сезонов ${e.keys.length} из ${used}). ${list}` })
      }
    })
    return {
      vals, lo: 0, hi, stops: ENTRY_STOPS, mid: byDays,
      title: byDays ? `Дни до ввода, ${scopeTitle(scope, season, kind)}` : `Очерёдность ввода, ${scopeTitle(scope, season, kind)}`,
      fmt: byDays ? v => Math.round(v) + ' дн.' : v => (v <= 0 ? 'первые' : v >= 1 ? 'последние' : Math.round(v * 100) + ' %'),
      note: byDays ? 'число — день ввода от старта' : 'число — очередь ввода (1 — первая)',
      scopeNote: multi ? scopeTitle(scope, season, kind) : undefined,
    }
  }
  if (paint === 'depth') {
    let lo = Infinity, hi = -Infinity
    const ok: [number, number, number][] = []
    for (const w of calc.wells) {
      const d = g.depths[String(w)]
      if (!d || d[0] < 100 || d[0] > 5000 || d[1] < 100 || d[1] > 5000 || d[0] > d[1]) continue
      ok.push([w, d[0], d[1]]); lo = Math.min(lo, d[0]); hi = Math.max(hi, d[0])
    }
    for (const [w, top, bot] of ok) vals.set(w, { v: top, label: String(Math.round(top)), tip: `Перфорация: ${Math.round(top)} — ${Math.round(bot)} м` })
    if (!ok.length) { lo = 0; hi = 1 }
    return { vals, lo, hi: hi === lo ? lo + 10 : hi, stops: DEPTH_STOPS, title: 'Глубина верха перфорации, м', fmt: v => String(Math.round(v)), note: 'число на круге — верх перфорации, м' }
  }
  // обводнённость: за окно одного сезона — максимум водного фактора; за несколько сезонов — среднее из максимумов по сезонам
  const have = new Set(calc.wells)
  const perSeason = new Map<number, [string, number][]>()
  for (const key of keys) {
    const src = multi ? waterByWell(g.water, kind, key, -1e7, 1e7) : waterByWell(g.water, kind, key, calc.days[a], calc.days[b])
    for (const [w, pts] of src) {
      if (!have.has(w)) continue
      const f = pts.map(p => p.factor).filter((v): v is number => v !== null)
      if (!f.length) continue
      const arr = perSeason.get(w) || []
      arr.push([key, Math.max(...f)])
      perSeason.set(w, arr)
    }
  }
  let hi = 0
  perSeason.forEach((arr, w) => {
    const v = arr.reduce((p, q) => p + q[1], 0) / arr.length
    hi = Math.max(hi, v)
    if (!multi) { vals.set(w, { v, label: String(Math.round(v)), tip: `Водный фактор: максимум ${Math.round(v)} л/1000 м³ за окно` }); return }
    const peak = arr.reduce((p, q) => (q[1] > p[1] ? q : p))
    const withWater = arr.filter(q => q[1] > 0).length
    vals.set(w, { v, label: String(Math.round(v)), tip: `Водный фактор в среднем ${Math.round(v)} л/1000 м³ по ${arr.length} сез. из ${keys.length}, с водой ${withWater}; пик ${Math.round(peak[1])} (${peak[0]})` })
  })
  return {
    vals, lo: 0, hi: hi || 1, stops: WF_STOPS, mid: true,
    title: multi ? 'ВФ, среднее по сезонам, л/1000 м³' : 'Макс. ВФ в окне, л/1000 м³',
    fmt: v => String(Math.round(v)), note: 'число — водный фактор', scopeNote: multi ? scopeTitle(scope, season, kind) : undefined,
  }
}
