// Копия gas_atlas web/src/projectLooks.ts @ 9497bc6. Не править: tools/sync_charts_from_atlas.py обновляет копию.
// Оформление графиков хранится в проекте (settings.chart_formats = {theme, types}, atlas/chart_style.py): одинаково на всех
// компьютерах, в копиях проекта и в выгрузке. Вид рядов — theme.series («Настройка» ряда), оформление графика и осей — theme
// (весь проект) или types[модуль] (графики этого раздела). На экране правка видна сразу, в проект пишется с паузой.
import { projectFormats } from './chartPrefs'
import type { ChartFormat, FormatStore } from './chartFormat'

export type FormatScope = 'type' | 'project'

/** Убирает пустое: пустые объекты, пустые строки и неопределённое не хранятся. */
function tidy<T>(value: T): T | undefined {
  if (value === null || value === undefined || value === '') return undefined
  if (Array.isArray(value) || typeof value !== 'object') return value
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(value)) { const t = tidy(v); if (t !== undefined) out[k] = t }
  return Object.keys(out).length ? out as T : undefined
}

/** Документ оформления (график и оси) выбранного уровня: тема проекта или тип графика (id модуля). */
export function formatDoc(store: FormatStore, scope: FormatScope, module: string): ChartFormat {
  const doc = scope === 'project' ? store.theme : store.types?.[module]
  return { chart: doc?.chart, axes: doc?.axes }
}

/** Записывает оформление графика и осей на уровень: на экране сразу, в проект — с паузой. Вид рядов не затрагивается. */
export function setFormatDoc(scope: FormatScope, module: string, doc: ChartFormat) {
  const store = projectFormats.get()
  const part = { chart: doc.chart, axes: doc.axes }
  const next: FormatStore = scope === 'project'
    ? { ...store, theme: { ...store.theme, ...part } }
    : { ...store, types: { ...store.types, [module]: { ...store.types?.[module], ...part } } }
  projectFormats.set(tidy(next) ?? {})
}
