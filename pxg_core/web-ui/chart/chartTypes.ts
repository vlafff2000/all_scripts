// Копия gas_atlas web/src/chartTypes.ts @ 37f2840. Не править: tools/sync_charts_from_atlas.py обновляет копию.
import type { Look } from './chartStyle'
export type Cell = string | number | boolean | null
/** Ручное оформление оси; пусто — авто (atlas/chart_style.py). */
export interface AxisStyle { decimals?: number; date_format?: string; font?: string; tick_size?: number; title_size?: number }
/** Ручное оформление графика: заголовок, шрифты, легенда, сетка, фон (atlas/chart_style.py). */
export interface ChartStyle {
  title_font?: string; title_size?: number; title_bold?: boolean; title_color?: string; title_align?: 'left' | 'center' | 'right'
  font?: string; text_color?: string; legend?: 'bottom' | 'top' | 'right' | 'hide'; legend_font?: string; legend_size?: number
  grid?: 'both' | 'h' | 'v' | 'none'; grid_color?: string; background?: string; plot_background?: string
}
export interface Axis {
  color?: string                       // цвет правой шкалы под один ряд; пусто — по умолчанию
  style?: AxisStyle                    // ручное оформление оси (конструктор): знаки, шрифт, размеры
  label: string; unit: string; scale: 'value' | 'log' | 'time' | 'category'; inverse: boolean; from_zero: boolean
  step: number | null; categories: string[] | null; minimum: number | null; maximum: number | null
}
export interface Series {
  name: string; kind: 'points' | 'line' | 'bar' | 'box'; group: string; dashed: boolean; dash: string; width: number
  legend: boolean; tooltip: string
  color: string; symbol: 'circle' | 'square' | 'diamond' | 'triangle'; hollow: boolean; opacity: number
  x: Cell[]; y: Cell[]; ids: string[] | null; labels: string[] | null; dataset: string | null
  markers: boolean; axis: 'y' | 'y2' | 'y3' | 'y4' | 'y5'; stack?: string
  fill?: boolean; step?: boolean            // линия с заливкой (область) и ступенчатая линия (конструктор графиков)
  suspect?: boolean                         // сомнительные точки выбросов: двойной щелчок снимает сомнение
  total: number      // точек в серии на самом деле; если больше x.length — линия прорежена (М4: пики и провалы сохранены)
  facets: Record<string, string> | null     // признаки для легенды рядами: {'Скважина': '№ 101', 'Период': '2024'}
  captions?: string[] | null                // текст над каждой точкой (подписи причин отсутствия замеров)
  values?: (number | null)[] | null         // третье значение точки: по нему красятся точки (шкала цвета справа)
  values_label?: string
  segments?: string[] | null                // подпись внутри каждого сегмента столбца стопки (число скважин)
  look?: Look                              // личный вид ряда из окна «Настройка» (только на клиенте)
}
/** Точки серии в видимом окне оси X (ответ /window): `window` — сколько их в окне до прореживания. */
export type WindowSeries = Pick<Series, 'x' | 'y' | 'ids' | 'labels' | 'values' | 'total'> & { window: number }
export interface WindowReply { chart: string; revision: number; series: Record<string, WindowSeries> }
export interface ChartBand { first: number; last: number; label: string; shaded: boolean }
export interface ChartEvent { x: string | number; label: string; kind: 'gdi' | 'regime' | 'repair' | 'peak' | 'other'; well: string }
export interface ChartTable { rows: string[]; columns: string[]; cells: string[][]; colors: string[]; swatches: boolean; aligned?: boolean }
export interface HeatMap {
  rows: string[]; columns: string[]; values: (number | null)[][]; texts: string[][]
  unit: string; maximum: number | null; missing_text: string
}
export interface WellStrips {
  rows: string[]; groups: string[]; columns: string[]; cells: (number | null)[][]; counts: number[]
  layout: 'matrix' | 'panels'; missing_text: string; colors?: Record<string, string>
}
export interface Chart {
  id: string; title: string; x: Axis; y: Axis; y2: Axis | null; y3?: Axis | null; y4?: Axis | null; y5?: Axis | null; series: Series[]; crosshair: boolean
  events?: ChartEvent[]
  bands?: ChartBand[]                       // годы над категориями оси X: подпись и серая/белая подложка
  callouts?: 'box' | 'dot'                  // узкие сегменты с подписью: выноска в рамке или точка (числа — в table)
  table?: ChartTable | null                 // таблица под графиком
  strips?: WellStrips | null                // скважины × сезоны (матрица или панели по ГСП)
  heat?: HeatMap | null                     // тепловая карта вместо рядов (ГСП × сезоны)
  style?: ChartStyle
}

/** Вид графика на экране для выгрузки: оформление рядов, границы осей, масштаб по времени, скрытые пункты легенды (atlas/chart_view.py). */
export interface ChartExportView {
  looks?: Record<string, unknown>
  ranges?: Partial<Record<'y' | 'y2' | 'y3' | 'y4' | 'y5', [number, number]>>
  x?: [number, number]
  hidden?: string[]
  facets?: string[]
}

