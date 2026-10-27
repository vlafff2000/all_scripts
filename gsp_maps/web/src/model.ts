import { isMulti, type GspData, type SeasonData, type SeasonInfo, type WaterRec } from './api'
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

const medianNN = (pts: { x: number; y: number }[]) => {
  if (pts.length < 2) return 1
  const nn = pts.map(a => {
    let m = Infinity
    for (const b of pts) if (a !== b) { const d = Math.hypot(a.x - b.x, a.y - b.y); if (d > 0 && d < m) m = d }
    return m
  }).filter(Number.isFinite).sort((p, q) => p - q)
  return nn.length ? nn[Math.floor(nn.length / 2)] : 1
}

/** Схематичная раскладка: скважины разнесены так, чтобы круги не налезали друг на друга, а взаимное расположение сохранялось.
 *  Шаг d выбирается по площади карты (скважины заполняют её равномерно), но не меньше, чем нужно для круга с кольцами воды. Считается один раз на ГСП. */
const spreadCache = new WeakMap<GspData, { pos: Map<number, [number, number]>; unit: number }>()
export function spreadLayout(g: GspData) {
  const hit = spreadCache.get(g)
  if (hit) return hit
  const pts = Object.entries(g.layout.wells).map(([w, p]) => ({ w: Number(w), x: p.x, y: -p.y, x0: p.x, y0: -p.y }))
  const n = pts.length
  const pos = new Map<number, [number, number]>()
  if (n < 2) { pts.forEach(p => pos.set(p.w, [p.x, p.y])); const r = { pos, unit: 1 }; spreadCache.set(g, r); return r }
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y)
  const W = Math.max(...xs) - Math.min(...xs), H = Math.max(...ys) - Math.min(...ys)
  const sp = medianNN(pts)
  const dmin = 3 * 0.58 * sp
  const d = Math.max(dmin, 1.05 * Math.sqrt(Math.max(W, sp) * Math.max(H, sp) / n))
  // совпадающие точки слегка разводим по детерминированным углам, иначе им не из чего расталкиваться
  pts.forEach((p, i) => { p.x += Math.cos(i * 2.399963) * d * 0.02; p.y += Math.sin(i * 2.399963) * d * 0.02 })
  for (let it = 0; it < 220; it++) {
    let worst = 0
    const fx = new Float64Array(n), fy = new Float64Array(n)
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const dx = pts[j].x - pts[i].x, dy = pts[j].y - pts[i].y
      if (Math.abs(dx) >= d || Math.abs(dy) >= d) continue
      const r = Math.hypot(dx, dy)
      if (r >= d) continue
      const push = (d - r) * 0.5, ux = r > 1e-9 ? dx / r : 1, uy = r > 1e-9 ? dy / r : 0
      fx[i] -= ux * push; fy[i] -= uy * push; fx[j] += ux * push; fy[j] += uy * push
      worst = Math.max(worst, d - r)
    }
    // слабая пружина к исходному месту сохраняет форму месторождения
    const k = it < 120 ? 0.02 : 0
    for (let i = 0; i < n; i++) { pts[i].x += fx[i] * 0.8 + (pts[i].x0 - pts[i].x) * k; pts[i].y += fy[i] * 0.8 + (pts[i].y0 - pts[i].y) * k }
    if (worst < d * 0.01) break
  }
  pts.forEach(p => pos.set(p.w, [p.x, p.y]))
  const r = { pos, unit: d / 3 }
  spreadCache.set(g, r)
  return r
}

export interface Placed { well: number; i: number; x: number; y: number; src: string; dir: string }
/** Скважины сезона с координатами и расстояние между ближайшими соседями (по нему выбираются размеры кругов). */
export function place(g: GspData, calc: SeasonCalc, spread = false) {
  const sl = spread ? spreadLayout(g) : null
  const placed: Placed[] = [], unplaced: number[] = []
  calc.wells.forEach((w, i) => {
    const p = g.layout.wells[String(w)]
    const q = sl?.pos.get(w)
    if (p) placed.push({ well: w, i, x: q ? q[0] : p.x, y: q ? q[1] : -p.y, src: p.src, dir: p.dir })
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
  return { placed, unplaced, spacing: sl ? sl.unit * 3 * 0.6 : spacing, bounds: box(core), boundsAll: box(placed), far, unit: sl ? sl.unit : null }
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
export type Paint = 'flow' | 'entry' | 'depth' | 'wf' | 'atlas' | 'model' | 'gis' | 'ref'
export const PAINTS: [Paint, string][] = [
  ['flow', 'Расход газа'], ['entry', 'Ввод по дате'], ['depth', 'Глубина перфорации'], ['wf', 'Обводнённость'], ['atlas', 'Параметр Атласа'], ['model', 'Модели tNavigator'], ['gis', 'ГИС и ГВК'], ['ref', 'Опорная сетка'],
]
export const ATLAS_AGGS: [string, string][] = [['mean', 'среднее'], ['sum', 'сумма'], ['last', 'последнее'], ['count', 'число записей']]
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
/** Шкала изменения: синий — уменьшилось, красный — выросло, светлая середина — без изменений. */
const DELTA_STOPS = ['#2166ac', '#92c5de', '#f2f2f2', '#f4a582', '#b2182b']
/** ГИС и ГВК: значения по скважинам; для изменения между сезонами (delta) шкала симметрична вокруг нуля и подписана знаком. */
export function gisPaint(values: Record<string, number>, dates: Record<string, string>, title: string, note: string[], delta: boolean): PaintData | null {
  const entries = Object.entries(values)
  if (!entries.length) return null
  const nums = entries.map(([, v]) => v)
  const f = (v: number) => (delta && v > 0 ? '+' : '') + fmt1(v)
  const vals = new Map<number, PaintVal>(entries.map(([w, v]) => [Number(w), { v, label: f(v), tip: `${title}: ${f(v)}${dates[w] ? ' · замер ' + dates[w] : ''}` }]))
  if (delta) {
    const m = Math.max(Math.abs(Math.min(...nums)), Math.abs(Math.max(...nums))) || 1
    return { vals, lo: -m, hi: m, stops: DELTA_STOPS, title, fmt: f, note: note.join(' '), mid: true }
  }
  const lo = Math.min(...nums), hi = Math.max(...nums)
  return { vals, lo, hi: hi > lo ? hi : lo + 1, stops: SEASON_STOPS, title, fmt: f, note: note.join(' ') }
}

/** Раскраска по параметру Атласа: шкала от наименьшего до наибольшего значения; без значения — без цвета. */
export function atlasPaint(values: Record<string, number>, title: string, note: string[]): PaintData | null {
  const entries = Object.entries(values)
  if (!entries.length) return null
  const nums = entries.map(([, v]) => v)
  const lo = Math.min(...nums), hi = Math.max(...nums)
  const vals = new Map<number, PaintVal>(entries.map(([w, v]) => [Number(w), { v, label: fmt1(v), tip: `${title}: ${fmt1(v)}` }]))
  return { vals, lo, hi: hi > lo ? hi : lo + 1, stops: SEASON_STOPS, title, fmt: fmt1, note: note.join(' ') }
}

export function paintFor(paint: Paint, g: GspData, calc: SeasonCalc, kind: string, season: string, a: number, b: number, scope?: Scope): PaintData | null {
  if (paint === 'flow' || paint === 'atlas' || paint === 'model' || paint === 'gis' || paint === 'ref') return null   // параметр Атласа и модели считаются в API и передаются отдельно
  const vals = new Map<number, PaintVal>()
  const multi = !!scope && scope.mode !== 'one' && scope.keys.length > 0
  const keys = multi ? scope!.keys : [season]
  if (paint === 'entry') {
    // внутри ГСП важна очерёдность включения (цвет — место в ряду), для всего объекта — дни от начала сезона
    const byDays = isMulti(g.gsp)
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

/** Изолинии показателя ГИС (например ГВК) по скважинам: взвешенная по обратному квадрату расстояния сетка и марширующие квадраты.
 *  Скважин мало, поэтому за край не экстраполируем: считаются только клетки внутри выпуклой оболочки скважин и не дальше
 *  `reach` средних расстояний между соседними скважинами от ближайшей. Уверенность клетки — доля остатка радиуса (1 у скважины, 0 на краю). */
export interface IsoPoint { x: number; y: number; v: number }
export interface IsoResult { lines: { level: number; d: string; at: [number, number] }[]; conf: { d: string; a: number }[]; step: number; note: string }
const hullOf = (ps: [number, number][]): [number, number][] => {
  const p = [...ps].sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const cross = (o: [number, number], a: [number, number], b: [number, number]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const half = (list: [number, number][]) => { const h: [number, number][] = []; for (const q of list) { while (h.length > 1 && cross(h[h.length - 2], h[h.length - 1], q) <= 0) h.pop(); h.push(q) } return h }
  const lo = half(p), up = half([...p].reverse())
  return [...lo.slice(0, -1), ...up.slice(0, -1)]
}
const inHull = (h: [number, number][], x: number, y: number) => h.every((a, i) => { const b = h[(i + 1) % h.length]; return (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]) >= -1e-9 })
export function niceLevelStep(range: number): number {
  const raw = range / 6, p = Math.pow(10, Math.floor(Math.log10(raw || 1))), f = raw / p
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p
}
/** Изолинии растра (марширующие квадраты): клетки с пропуском в углах пропускаются; линии по уровням, кратным шагу. */
export function contourSegments(z: ArrayLike<number>, nx: number, ny: number, x0: number, y0: number, dx: number, dy: number, level: number): [[number, number], [number, number]][] {
  const out: [[number, number], [number, number]][] = []
  const cross = (ax: number, ay: number, av: number, bx: number, by: number, bv: number): [number, number] => { const t = (level - av) / (bv - av); return [ax + t * (bx - ax), ay + t * (by - ay)] }
  for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
    const a = z[j * nx + i], b = z[j * nx + i + 1], c = z[(j + 1) * nx + i + 1], e = z[(j + 1) * nx + i]
    if (!(Number.isFinite(a) && Number.isFinite(b) && Number.isFinite(c) && Number.isFinite(e))) continue
    const k = (a >= level ? 1 : 0) | (b >= level ? 2 : 0) | (c >= level ? 4 : 0) | (e >= level ? 8 : 0)
    if (k === 0 || k === 15) continue
    const X = x0 + i * dx, Y = y0 + j * dy
    const T = () => cross(X, Y, a, X + dx, Y, b), R = () => cross(X + dx, Y, b, X + dx, Y + dy, c), B = () => cross(X, Y + dy, e, X + dx, Y + dy, c), Lf = () => cross(X, Y, a, X, Y + dy, e)
    const segs: [() => [number, number], () => [number, number]][] = {
      1: [[Lf, T]], 2: [[T, R]], 3: [[Lf, R]], 4: [[R, B]], 5: [[Lf, T], [B, R]], 6: [[T, B]], 7: [[Lf, B]],
      8: [[Lf, B]], 9: [[T, B]], 10: [[Lf, B], [T, R]], 11: [[R, B]], 12: [[Lf, R]], 13: [[T, R]], 14: [[Lf, T]],
    }[k] as [() => [number, number], () => [number, number]][]
    for (const [p, q] of segs) out.push([p(), q()])
  }
  return out
}
export function contourLines(z: ArrayLike<number>, nx: number, ny: number, x0: number, y0: number, dx: number, dy: number, step: number, lo: number, hi: number): IsoResult['lines'] {
  const lines: IsoResult['lines'] = []
  const f = (v: number) => v.toFixed(1)
  if (!(step > 0)) return lines
  for (let L = Math.ceil(lo / step) * step; L <= hi + 1e-9; L += step) {
    const level = Math.round(L / step) * step
    let d = '', at: [number, number] | null = null
    for (const [P, Q] of contourSegments(z, nx, ny, x0, y0, dx, dy, level)) { d += `M${f(P[0])} ${f(P[1])}L${f(Q[0])} ${f(Q[1])}`; at = at ?? [(P[0] + Q[0]) / 2, (P[1] + Q[1]) / 2] }
    if (d && at) lines.push({ level, d, at })
  }
  return lines
}
export function isolines(points: IsoPoint[], spacing: number, step: number, reach: number, n = 70): IsoResult {
  const empty = (note: string): IsoResult => ({ lines: [], conf: [], step, note })
  if (points.length < 3) return empty('Для изолиний нужно не меньше трёх скважин со значением.')
  const hull = hullOf(points.map(p => [p.x, p.y]))
  if (hull.length < 3) return empty('Скважины лежат на одной линии: изолинии не построить.')
  const xs = points.map(p => p.x), ys = points.map(p => p.y)
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
  const dx = (x1 - x0) / (n - 1), dy = (y1 - y0) / (n - 1), rad = Math.max(reach * spacing, 1e-9)
  const z = new Float64Array(n * n).fill(NaN), cf = new Float64Array(n * n)
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const x = x0 + i * dx, y = y0 + j * dy
    if (!inHull(hull, x, y)) continue
    let sw = 0, sv = 0, dm = Infinity
    for (const p of points) {
      const d = Math.hypot(p.x - x, p.y - y)
      if (d < dm) dm = d
      if (d < 1e-9) { sw = 1; sv = p.v; break }
      const w = 1 / (d * d); sw += w; sv += w * p.v
    }
    if (dm > rad) continue
    z[j * n + i] = sv / sw; cf[j * n + i] = 1 - dm / rad
  }
  const vs = [...z].filter(Number.isFinite)
  if (!vs.length) return empty('Вокруг скважин нет клеток в радиусе доверия: увеличьте радиус.')
  const lo = Math.min(...vs), hi = Math.max(...vs)
  const lines = contourLines(z, n, n, x0, y0, dx, dy, step, lo, hi)
  const f = (v: number) => v.toFixed(1)
  // уверенность тремя ступенями: чем дальше от скважин, тем прозрачнее заливка
  const conf: IsoResult['conf'] = [{ d: '', a: 0.16 }, { d: '', a: 0.09 }, { d: '', a: 0.04 }]
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const c = cf[j * n + i]
    if (!Number.isFinite(z[j * n + i])) continue
    conf[c > 0.66 ? 0 : c > 0.33 ? 1 : 2].d += `M${f(x0 + (i - 0.5) * dx)} ${f(y0 + (j - 0.5) * dy)}h${f(dx)}v${f(dy)}h${f(-dx)}z`
  }
  return { lines, conf, step, note: lines.length ? '' : 'В этой области значения почти не меняются: изолиний с таким шагом нет.' }
}

/** Контур ГВК по кровле: линия, где кровля пласта (растр модели) пересекает поверхность ГВК, проведённую через замерные скважины.
 *  Так контур идёт вдоль изолиний кровли, а у скважины встаёт туда, где кровля на глубине ГВК. Поверхность ГВК — плоскость
 *  (наименьшие квадраты; меньше трёх скважин или скважины на линии — среднее) или взвешенная по расстоянию (idw), как есть по скважинам.
 *  Считается только в радиусе доверия `reach` средних расстояний между скважинами и только там, где у кровли есть значение. */
export interface RoofRaster { z: Float64Array; nx: number; ny: number; x0: number; y0: number; dx: number; dy: number }
export interface GwcContour { d: string; at: [number, number] | null; note: string; surface: string }
export function gwcContour(wells: IsoPoint[], roof: RoofRaster, spacing: number, reach: number, mode: 'plane' | 'idw'): GwcContour {
  const none = (note: string): GwcContour => ({ d: '', at: null, note, surface: '' })
  if (!wells.length) return none('Нет скважин с ГВК для контура.')
  const mean = wells.reduce((s, w) => s + w.v, 0) / wells.length
  let g: (x: number, y: number) => number = () => mean
  let surface = 'среднее ГВК скважин'
  if (mode === 'plane' && wells.length >= 3) {
    // z = a + b·(x−cx) + c·(y−cy): нормальные уравнения 3×3
    const cx = wells.reduce((s, w) => s + w.x, 0) / wells.length, cy = wells.reduce((s, w) => s + w.y, 0) / wells.length
    let sxx = 0, sxy = 0, syy = 0, sxz = 0, syz = 0
    for (const w of wells) { const u = w.x - cx, v = w.y - cy, z = w.v - mean; sxx += u * u; sxy += u * v; syy += v * v; sxz += u * z; syz += v * z }
    const det = sxx * syy - sxy * sxy
    if (Math.abs(det) > 1e-9 * (sxx * syy + 1)) {
      const b = (sxz * syy - syz * sxy) / det, c = (syz * sxx - sxz * sxy) / det
      g = (x, y) => mean + b * (x - cx) + c * (y - cy)
      surface = `плоскость ГВК по ${wells.length} скважинам (наклон ${(Math.hypot(b, c) * 1000).toFixed(1)} м на км)`
    }
  } else if (mode === 'idw') {
    g = (x, y) => {
      let sw = 0, sv = 0
      for (const w of wells) { const d = Math.hypot(w.x - x, w.y - y); if (d < 1e-9) return w.v; const k = 1 / (d * d); sw += k; sv += k * w.v }
      return sv / sw
    }
    surface = 'ГВК по скважинам (взвешенное по расстоянию)'
  }
  const rad = Math.max(reach * spacing, 1e-9)
  const D = new Float64Array(roof.nx * roof.ny).fill(NaN)
  for (let j = 0; j < roof.ny; j++) for (let i = 0; i < roof.nx; i++) {
    const r = roof.z[j * roof.nx + i]
    if (!Number.isFinite(r)) continue
    const x = roof.x0 + i * roof.dx, y = roof.y0 + j * roof.dy
    if (wells.some(w => Math.hypot(w.x - x, w.y - y) <= rad)) D[j * roof.nx + i] = r - g(x, y)
  }
  const line = contourLines(D, roof.nx, roof.ny, roof.x0, roof.y0, roof.dx, roof.dy, 1, 0, 0)
  if (!line.length) return { d: '', at: null, note: 'Кровля нигде не пересекает ГВК в радиусе доверия: контур не построен (проверьте слой кровли и радиус).', surface }
  return { d: line[0].d, at: line[0].at, note: '', surface }
}

/** Единый контур ГВК залежи (как контуры газоносности на рис. 5.40 отчёта авторского надзора): гладкая поверхность ГВК по всем
 *  замерам, линия — там, где кровля пласта (растр модели) пересекает эту поверхность; внутри линии газ. Не кружки вокруг скважин.
 *  Вклад скважины в поверхность: 1/(d²+ε²)^(p/2) · exp(−(Δ/σ)²), где d — расстояние до точки, ε = сглаживание·среднее расстояние между
 *  скважинами, Δ — разность между кровлей в самой скважине и её ГВК (скважина с ГВК далеко от кровли у себя не на контуре и почти не
 *  влияет). Из контура остаются только линии не дальше `reach` средних расстояний от скважины с заметным вкладом (чтобы не рисовать
 *  пересечения на другой структуре, где замеров нет). Все параметры задаёт инженер, авто — подсказка. */
export interface GwcWell extends IsoPoint { w: string }
export interface GwcParams { sigma: number; power: number; smooth: number; reach: number }
export interface GwcShare { w: string; v: number; delta: number | null; share: number }
export interface GwcUnified { d: string; at: [number, number] | null; note: string; surface: string; shares: GwcShare[]; closed: number; open: number }
export const GWC_DEFAULTS: GwcParams = { sigma: 15, power: 2, smooth: 0.5, reach: 3 }
export function roofAt(r: RoofRaster, x: number, y: number): number {
  const fi = (x - r.x0) / r.dx, fj = (y - r.y0) / r.dy
  const i = Math.floor(fi), j = Math.floor(fj)
  if (i < 0 || j < 0 || i >= r.nx - 1 || j >= r.ny - 1) return NaN
  const a = r.z[j * r.nx + i], b = r.z[j * r.nx + i + 1], c = r.z[(j + 1) * r.nx + i], e = r.z[(j + 1) * r.nx + i + 1]
  if (!(Number.isFinite(a) && Number.isFinite(b) && Number.isFinite(c) && Number.isFinite(e))) return NaN
  const u = fi - i, t = fj - j
  return (a * (1 - u) + b * u) * (1 - t) + (c * (1 - u) + e * u) * t
}
/** Закрывает узкие дыры растра кровли (пустые колонны между ячейками, до двух клеток): значение — среднее соседей; широкие дыры остаются. */
export function fillRoofGaps(r: RoofRaster, rounds = 2): RoofRaster {
  let z = Float64Array.from(r.z)
  for (let n = 0; n < rounds; n++) {
    const next = Float64Array.from(z)
    for (let j = 0; j < r.ny; j++) for (let i = 0; i < r.nx; i++) {
      if (Number.isFinite(z[j * r.nx + i])) continue
      const nb = [[i - 1, j], [i + 1, j], [i, j - 1], [i, j + 1]].filter(([a, b]) => a >= 0 && b >= 0 && a < r.nx && b < r.ny && Number.isFinite(z[b * r.nx + a])).map(([a, b]) => z[b * r.nx + a])
      if (nb.length >= 2) next[j * r.nx + i] = nb.reduce((p, q) => p + q, 0) / nb.length
    }
    z = next
  }
  return { ...r, z }
}
type Pt = [number, number]
function chain(segs: [Pt, Pt][]): { pts: Pt[]; closed: boolean }[] {
  const key = (p: Pt) => p[0].toFixed(3) + ',' + p[1].toFixed(3)
  const at = new Map<string, number[]>()
  segs.forEach(([p, q], i) => { for (const k of [key(p), key(q)]) { const l = at.get(k); if (l) l.push(i); else at.set(k, [i]) } })
  const used = new Array(segs.length).fill(false)
  const take = (k: string): number => { for (const i of at.get(k) ?? []) if (!used[i]) return i; return -1 }
  const out: { pts: Pt[]; closed: boolean }[] = []
  const walk = (pts: Pt[], forward: boolean) => {
    for (;;) {
      const i = take(key(forward ? pts[pts.length - 1] : pts[0]))
      if (i < 0) return
      used[i] = true
      const [p, q] = segs[i], tail = forward ? pts[pts.length - 1] : pts[0]
      const next = key(p) === key(tail) ? q : p
      if (forward) pts.push(next); else pts.unshift(next)
    }
  }
  for (let s = 0; s < segs.length; s++) {
    if (used[s]) continue
    used[s] = true
    const pts: Pt[] = [segs[s][0], segs[s][1]]
    walk(pts, true); walk(pts, false)
    out.push({ pts, closed: pts.length > 3 && key(pts[0]) === key(pts[pts.length - 1]) })
  }
  return out
}
export function gwcUnified(wells: GwcWell[], roofRaw: RoofRaster, spacing: number, par: GwcParams): GwcUnified {
  const roof = fillRoofGaps(roofRaw)
  const none = (note: string): GwcUnified => ({ d: '', at: null, note, surface: '', shares: [], closed: 0, open: 0 })
  if (!wells.length) return none('Нет скважин с ГВК для контура (все исключены или нет значений).')
  const sigma = Math.max(par.sigma, 1e-6), eps2 = Math.pow(Math.max(par.smooth, 0) * spacing, 2) + 1e-12
  // вес по близости ГВК скважины к кровле в ней; без кровли в точке скважины вес 1 (скважина помечается пустой разностью)
  const fw = wells.map(w => { const rz = roofAt(roof, w.x, w.y); const delta = Number.isFinite(rz) ? rz - w.v : null; return { delta, f: Math.max(delta === null ? 1 : Math.exp(-Math.pow(delta / sigma, 2)), 1e-9) } })
  const weights = (x: number, y: number): number[] => wells.map((w, i) => fw[i].f * Math.pow((x - w.x) ** 2 + (y - w.y) ** 2 + eps2, -par.power / 2))
  const surf = (x: number, y: number) => { const k = weights(x, y); let s = 0, t = 0; k.forEach((q, i) => { s += q; t += q * wells[i].v }); return t / s }
  const D = new Float64Array(roof.nx * roof.ny).fill(NaN)
  for (let j = 0; j < roof.ny; j++) for (let i = 0; i < roof.nx; i++) {
    const r = roof.z[j * roof.nx + i]
    if (Number.isFinite(r)) D[j * roof.nx + i] = r - surf(roof.x0 + i * roof.dx, roof.y0 + j * roof.dy)
  }
  const near = wells.filter((_, i) => fw[i].f > 0.05), rad = Math.max(par.reach * spacing, 1e-9)
  const lines = chain(contourSegments(D, roof.nx, roof.ny, roof.x0, roof.y0, roof.dx, roof.dy, 0))
    .filter(l => l.pts.length > 2 && l.pts.some(p => near.some(w => Math.hypot(w.x - p[0], w.y - p[1]) <= rad)))
  const surface = `поверхность ГВК по ${wells.length} скв., вес по близости и по разности ГВК с кровлей (σ ${par.sigma} м, степень ${par.power}, сглаживание ${par.smooth})`
  if (!lines.length) return { ...none('Кровля не пересекает поверхность ГВК рядом со скважинами: контур не построен (проверьте слой кровли, σ и радиус влияния).'), surface }
  // реальный вклад: средняя доля веса скважины вдоль построенного контура
  const acc = new Array(wells.length).fill(0); let n = 0
  for (const l of lines) for (const p of l.pts) { const k = weights(p[0], p[1]), s = k.reduce((a, b) => a + b, 0); k.forEach((q, i) => { acc[i] += q / s }); n++ }
  const shares = wells.map((w, i) => ({ w: w.w, v: w.v, delta: fw[i].delta, share: acc[i] / n })).sort((a, b) => b.share - a.share)
  const f1 = (v: number) => v.toFixed(1)
  const d = lines.map(l => 'M' + l.pts.map(p => `${f1(p[0])} ${f1(p[1])}`).join('L') + (l.closed ? 'Z' : '')).join('')
  const first = lines[0].pts[Math.floor(lines[0].pts.length / 2)]
  return { d, at: first, note: '', surface, shares, closed: lines.filter(l => l.closed).length, open: lines.filter(l => !l.closed).length }
}

/** Опорная замерная сетка скважин: таблица 1.2 отчёта «Авторский надзор, Касимовское ПХГ, 2025» (скважина → ГСП). Цвет на карте берётся по группе из проекта. */
export const REF_PRESET_AN2025 = '56, 83, 220, 182, 237, 264, 437, 520'
/** Номера скважин из текста списка: запятая, точка с запятой, пробел или перевод строки; «№», «Скв.» и повторы отбрасываются. */
export function parseRefWells(raw: string): number[] {
  const out: number[] = []
  for (const m of String(raw).matchAll(/\d+/g)) { const n = Number(m[0]); if (!out.includes(n)) out.push(n) }
  return out
}
