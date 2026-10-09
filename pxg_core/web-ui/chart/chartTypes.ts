// Контракт графика (подмножество atlas/contract.py, копия из web/src/api.ts Атласа): ось, серия, график.
export type Cell = string | number | boolean | null
export interface Axis {
  label: string; unit: string; scale: 'value' | 'log' | 'time' | 'category'; inverse: boolean; from_zero: boolean
  step: number | null; categories: string[] | null; minimum: number | null; maximum: number | null
}
export interface Series {
  name: string; kind: 'points' | 'line' | 'bar' | 'box'; group: string; dashed: boolean; dash: string; width: number
  legend: boolean; tooltip: string
  color: string; symbol: 'circle' | 'square' | 'diamond' | 'triangle'; hollow: boolean; opacity: number
  x: Cell[]; y: Cell[]; ids: string[] | null; labels: string[] | null; dataset: string | null
  markers: boolean; axis: 'y' | 'y2'; stack?: string
  total: number
  facets: Record<string, string> | null
}
export type WindowSeries = Pick<Series, 'x' | 'y' | 'ids' | 'labels' | 'total'> & { window: number }
export interface WindowReply { chart: string; revision: number; series: Record<string, WindowSeries> }
export interface ChartEvent { x: string | number; label: string; kind: 'gdi' | 'regime' | 'repair' | 'peak' | 'other'; well: string }
export interface Chart {
  id: string; title: string; x: Axis; y: Axis; y2: Axis | null; series: Series[]; crosshair: boolean
  events?: ChartEvent[]
}
