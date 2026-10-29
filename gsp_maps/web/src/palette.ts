import { pref, usePref } from './prefs'

/** Палитра как в дизайнере геологии tNavigator: опорные цвета (стопы) на шкале 0…1, плавный или ступенчатый переход,
 *  обращение и ручной диапазон значений. Решение за инженером: всё, что подобрано автоматически, переопределяется. */
export interface PStop { t: number; c: string }
export interface PaletteDef {
  stops: PStop[]
  /** 0 — плавный переход; n ≥ 2 — n ступеней (интервалов) одного цвета каждая. */
  steps: number
  reverse: boolean
  /** Ручные границы шкалы; null — по данным. */
  lo: number | null
  hi: number | null
}

const HEX = /^#[0-9a-f]{6}$/i
export const isHex = (s: unknown): s is string => typeof s === 'string' && HEX.test(s)
const clamp01 = (t: number) => Math.max(0, Math.min(1, t))

/** Равномерно расставленные стопы по списку цветов. */
export function equalStops(colors: string[]): PStop[] {
  const n = colors.length
  return colors.map((c, i) => ({ t: n > 1 ? i / (n - 1) : 0, c }))
}
export const defOf = (colors: string[]): PaletteDef => ({ stops: equalStops(colors), steps: 0, reverse: false, lo: null, hi: null })

const rgb = (s: string) => [1, 3, 5].map(k => parseInt(s.slice(k, k + 2), 16))
const hex = (v: number[]) => '#' + v.map(x => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, '0')).join('')

function smoothAt(stops: PStop[], t: number): string {
  const s = stops
  if (t <= s[0].t) return s[0].c
  if (t >= s[s.length - 1].t) return s[s.length - 1].c
  let i = 0
  while (i < s.length - 2 && t > s[i + 1].t) i++
  const p = s[i], q = s[i + 1], span = q.t - p.t, f = span > 0 ? (t - p.t) / span : 0
  const a = rgb(p.c), b = rgb(q.c)
  return hex(a.map((v, k) => v + (b[k] - v) * f))
}

/** Цвет в точке шкалы t ∈ [0, 1] с учётом обращения и ступеней. */
export function paletteAt(def: PaletteDef, t: number): string {
  let x = clamp01(Number.isFinite(t) ? t : 0)
  if (def.reverse) x = 1 - x
  if (def.steps >= 2) x = (Math.min(def.steps - 1, Math.floor(x * def.steps)) + 0.5) / def.steps
  return smoothAt(def.stops, x)
}

/** Остановки градиента для легенды: у ступенчатой палитры — резкие границы. */
export function gradientStops(def: PaletteDef): { offset: number; color: string }[] {
  if (def.steps >= 2) {
    const n = def.steps, out: { offset: number; color: string }[] = []
    for (let i = 0; i < n; i++) { const c = paletteAt(def, (i + 0.5) / n); out.push({ offset: i / n, color: c }, { offset: (i + 1) / n, color: c }) }
    return out
  }
  return Array.from({ length: 33 }, (_, i) => ({ offset: i / 32, color: paletteAt(def, i / 32) }))
}
export const cssGradient = (def: PaletteDef) => 'linear-gradient(90deg,' + gradientStops(def).map(s => `${s.color} ${(s.offset * 100).toFixed(1)}%`).join(',') + ')'

/** Привести сохранённое значение к допустимому виду (повреждённое — отбросить). */
export function parseDef(raw: unknown): PaletteDef | null {
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  if (!Array.isArray(o.stops)) return null
  const stops = o.stops.map(s => (s && typeof s === 'object' ? { t: Number((s as PStop).t), c: String((s as PStop).c) } : null))
    .filter((s): s is PStop => !!s && Number.isFinite(s.t) && isHex(s.c)).map(s => ({ t: clamp01(s.t), c: s.c.toLowerCase() })).sort((p, q) => p.t - q.t)
  if (stops.length < 2) return null
  const num = (v: unknown) => (v === null || v === '' || v === undefined || !Number.isFinite(Number(v)) ? null : Number(v))
  const steps = Number(o.steps)
  return { stops, steps: Number.isFinite(steps) && steps >= 2 ? Math.min(32, Math.round(steps)) : 0, reverse: !!o.reverse, lo: num(o.lo), hi: num(o.hi) }
}

/** Встроенные палитры (имя, цвета от начала до конца шкалы). */
export const BUILTIN_PALETTES: [string, string[]][] = [
  ['Viridis', ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725']],
  ['Plasma', ['#0d0887', '#7e03a8', '#cc4778', '#f89540', '#f0f921']],
  ['Радуга', ['#2b3a9f', '#2f9be0', '#36b779', '#f6d746', '#e2614f', '#8e2236']],
  ['Холодное — горячее', ['#2166ac', '#92c5de', '#f2f2f2', '#f4a582', '#b2182b']],
  ['Рельеф', ['#2c7bb6', '#7fcdbb', '#e8efd9', '#d9b96b', '#8c5a2b', '#ffffff']],
  ['Голубые', ['#cde2fb', '#6da7ec', '#256abf', '#0d366b']],
  ['Тёплые', ['#fde0c5', '#f19a85', '#c33a3f', '#5c1529']],
  ['Серые', ['#ffffff', '#9a9a9a', '#1a1a1a']],
]

/** Палитры, изменённые инженером: по ключу режима («entry», «depth», …). Нет записи — палитра режима по умолчанию. */
export const paletteOverrides = pref<Record<string, PaletteDef>>('gsp.palettes', {}, raw => {
  const out: Record<string, PaletteDef> = {}
  if (raw && typeof raw === 'object') for (const [k, v] of Object.entries(raw as Record<string, unknown>)) { const d = parseDef(v); if (d) out[k] = d }
  return out
})
/** Свои пресеты: общие для всех режимов. */
export const palettePresets = pref<{ name: string; def: PaletteDef }[]>('gsp.palettePresets', [], raw => {
  if (!Array.isArray(raw)) return []
  return raw.map(r => { const d = parseDef(r?.def); return d && typeof r?.name === 'string' && r.name ? { name: r.name as string, def: d } : null }).filter((x): x is { name: string; def: PaletteDef } => !!x)
})

export function setOverride(key: string, def: PaletteDef | null) {
  const cur = { ...paletteOverrides.get() }
  if (def) cur[key] = def; else delete cur[key]
  paletteOverrides.set(cur)
}
/** Палитра режима: изменённая инженером либо по умолчанию. */
export function usePaletteOverride(key: string): PaletteDef | null {
  return usePref(paletteOverrides)[key] ?? null
}
