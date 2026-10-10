// Сборка графика в формате Атласа (chartTypes.ts) из простых рядов: общий для всех экранов приложений ПХГ.
// Здесь только значения по умолчанию; рисует и ведёт себя график так же, как в Газовом Атласе (ChartView.tsx).
import type { Axis, Cell, Chart, Series } from './chartTypes'
import { PALETTE } from './chartTheme'

export const COLORS = PALETTE

export function mkAxis(label: string, unit = '', scale: Axis['scale'] = 'value', extra: Partial<Axis> = {}): Axis {
  return { label, unit, scale, inverse: false, from_zero: false, step: null, categories: null, minimum: null, maximum: null, ...extra }
}

export interface LineSpec {
  name: string; x: Cell[]; y: Cell[]; slot?: number; color?: string; dashed?: boolean; width?: number
  kind?: Series['kind']; stack?: string; group?: string; facets?: Record<string, string>; opacity?: number
}

export function mkSeries(s: LineSpec): Series {
  return {
    name: s.name, kind: s.kind ?? 'line', group: s.group ?? '', dashed: !!s.dashed,
    // после восьмого ряда цвета повторяются: ряды различаются ещё и штрихом
    dash: s.dashed ? 'dash' : (s.slot ?? 0) >= COLORS.length ? (['dash', 'dot', 'dashdot'] as const)[(Math.floor((s.slot ?? 0) / COLORS.length) - 1) % 3] : 'solid',
    width: s.width ?? 2, legend: true, tooltip: '', color: s.color ?? COLORS[(s.slot ?? 0) % COLORS.length],
    symbol: 'circle', hollow: false, opacity: s.opacity ?? 1, x: s.x, y: s.y, ids: null, labels: null, dataset: null,
    markers: false, axis: 'y', stack: s.stack, total: s.x.length, facets: s.facets ?? null,
  }
}

export function mkChart(id: string, title: string, x: Axis, y: Axis, series: Series[]): Chart {
  return { id, title, x, y, y2: null, series, crosshair: true }
}

/** Дата «ГГГГ-ММ-ДД» ↔ номер суток от эпохи. */
export const dayNum = (iso: string) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 864e5
export const isoOfDay = (n: number) => new Date(n * 864e5).toISOString().slice(0, 10)
