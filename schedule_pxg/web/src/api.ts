import { openFilePicker } from '../../../pxg_core/web-ui/FilePicker'
export interface Template {
  name: string; sheet: string | number | null; header_row: number
  well: string; date: string; rate: string; hourly: string; hours: string; kind: string; group: string; kind_default: string; unit: string; layout?: string
}
export interface AppState { folder: string; project: string; templates: Template[]; units: string[]; kinds: string[]; techmaps: TechMapInfo[]; scenarios: ScenarioInfo[] }
export interface ScenarioInfo { name: string; parent: string | null; note: string; percent: number; seasons: number; results?: string }
export type StrategyTable = Record<string, Record<string, number>>
export interface Season { year: number; techmap: string; percent: number; label: string; volumes?: StrategyTable }
export interface ScenarioValues {
  calendar: Season[]; grid: { step: string; periods: [string, string][]; cuts: string[] }; control: { mode?: string; level?: string; limits?: unknown[] }
  outages: unknown[]; percent: number; tolerance: number; decimals: number; note: string
}
export interface ScenarioView {
  name: string; parent: string | null; values: ScenarioValues; origin: Record<string, string>; children: string[]; notes: string[]
  diff: { field: string; label: string; parent: unknown; own: unknown }[]; fields: Record<string, string>
}
export interface BuildView {
  seasons: { techmap: string; year: number; percent: number; from: string; to: string; steps: number; over: number; strategy?: boolean }[]
  gaps: { from: string; to: string; days: number }[]; notes: string[]; stitch: string[]; steps: number; over: number; rows: number; shares: string
}
export interface TechMapInfo { name: string; kind: string; months: string[]; groups: number; total: number; source: string }
export interface TechMapData {
  name: string; kind: string; months: string[]; days: Record<string, number>; volumes: Record<string, Record<string, number>>
  wells: Record<string, number>; totals: Record<string, number>; source: string
}
export interface TechMapView { techmap: TechMapData; summary: string; issues: { level: string; message: string }[]; kinds: string[] }
export interface Preview {
  sheets: string[]; sheet: string; rows: string[][]; headerRow: number; columns: string[]
  suggest: Record<'well' | 'date' | 'rate' | 'hourly' | 'hours' | 'kind' | 'group', string>; unit: string; total: number; format: string | null
}
export interface Trial {
  groups?: { wells: number; groups: number }
  rows: number; wells: number; from: string; to: string; kinds: Record<string, number>
  sample: [string, string, number | null, number | null, string][]; issues: { level: string; message: string }[]; summary: string
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body.error || 'Ошибка сервера (' + r.status + ')')
  return body as T
}
const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const getState = () => call<AppState>('/api/state')
export const getPreview = (path: string, sheet?: string, headerRow?: number) => {
  const q = new URLSearchParams({ path })
  if (sheet) q.set('sheet', sheet)
  if (headerRow !== undefined) q.set('headerRow', String(headerRow))
  return call<Preview>('/api/preview?' + q)
}
export const runTrial = (path: string, template: Template) => call<Trial>('/api/trial', post({ path, template }))
export const saveTemplate = (template: Template) => call<AppState>('/api/template', post({ template }))
export const deleteTemplate = (name: string) => call<AppState>('/api/template/delete', post({ name }))
// Свой проводник вместо окна Tk; результат того же вида, пустой путь — отмена.
export const pickFile = async (start: string) => ({ path: (await openFilePicker({ start })) || '' })
export const readTechMap = (path: string, name: string, kind: string) => call<TechMapView>('/api/techmap/read', post({ path, name, kind }))
export const getTechMap = (name: string) => call<TechMapView>('/api/techmap?name=' + encodeURIComponent(name))
export const saveTechMap = (techmap: TechMapData, overwrite: boolean) => call<AppState>('/api/techmap/save', post({ techmap, overwrite }))
export const deleteTechMap = (name: string) => call<AppState>('/api/techmap/delete', post({ name }))

export const getScenario = (name: string) => call<ScenarioView>('/api/scenario?name=' + encodeURIComponent(name))
export const createScenario = (name: string, parent: string | null, values?: Partial<ScenarioValues>) => call<AppState>('/api/scenario/create', post({ name, parent, values }))
export const setScenario = (name: string, key: string, value: unknown) => call<AppState>('/api/scenario/set', post({ name, key, value }))
export const inheritScenario = (name: string, key: string) => call<AppState>('/api/scenario/inherit', post({ name, key }))
export const reparentScenario = (name: string, parent: string | null) => call<AppState>('/api/scenario/reparent', post({ name, parent }))
export const deleteScenario = (name: string) => call<AppState>('/api/scenario/delete', post({ name }))
export const percentBranches = (parent: string, percents: number[]) => call<AppState>('/api/scenario/percents', post({ parent, percents }))
export const expandPattern = (pattern: string[], firstYear: number, untilYear: number) =>
  call<{ calendar: Season[] }>('/api/scenario/pattern', post({ pattern, firstYear, untilYear }))
export const buildScenario = (name: string) => call<BuildView>('/api/scenario/build?name=' + encodeURIComponent(name))
export const scheduleUrl = (name: string) => '/api/scenario/schedule?name=' + encodeURIComponent(name)

export interface AvgWell {
  well: string; group: string; advice: number[] | null; adviceBy: string; choice: number[] | null; chosen: number[] | null
  excluded: number[]; manual: number; holdout: number | null
}
export interface AvgView {
  kind: string; months: string[]; years: number[]; skippedYears: number[]; combos: string[]; wells: AvgWell[]
  heat: { well: string; values: (number | null)[] }[]; groups: Record<string, Record<string, Record<string, { share: number | null; manual: boolean }>>>
  sums: Record<string, Record<string, number | null>>; exclusions: { well: string; year: number; reason: string; auto: boolean }[]
  unknown: string[]; params: { max_years: number; last_k: number; metric: string }; sources: string[]
}
export interface AvgWellView {
  well: string; group: string; months: string[]; years: number[]; byYear: Record<string, (number | null)[]>; mean: (number | null)[]
  chosen: number[] | null; manual: Record<string, number>; autoExcluded: Record<string, string>; autoMonths: Record<string, string[]>
  table: { years: string; n: number; holdout: number | null; closeness: number | null; stability: number | null; advice: boolean; chosen: boolean }[]
}
const avgBody = (kind: string, rest: object) => post({ kind, ...rest })
export const getAveraging = (kind: string) => call<AvgView>('/api/averaging?kind=' + encodeURIComponent(kind))
export const getAveragingWell = (kind: string, well: string) => call<AvgWellView>('/api/averaging/well?kind=' + encodeURIComponent(kind) + '&well=' + encodeURIComponent(well))
export const setAvgSources = (kind: string, paths: string[], params: object) => call<AvgView>('/api/averaging/sources', avgBody(kind, { paths, params }))
export const avgChoose = (kind: string, well: string, combo: number[] | null) => call<AvgView>('/api/averaging/choose', avgBody(kind, { well, combo }))
export const avgAdvice = (kind: string, wells?: string[]) => call<AvgView>('/api/averaging/advice', avgBody(kind, { wells }))
export const avgExclude = (kind: string, well: string, year: number, on: boolean) => call<AvgView>('/api/averaging/exclude', avgBody(kind, { well, year, on }))
export const avgManual = (kind: string, well: string, month: string, share: number | null) => call<AvgView>('/api/averaging/manual', avgBody(kind, { well, month, share }))

export interface ChartSeries { key: string; label: string; kind: string; season: string; total: number; steps: [string, string, number, number, number, number | null][] }
export interface ChartsView {
  by: string; target: string; unit: string; scenarios: { name: string; series: ChartSeries[]; notes: string[] }[]
  totals: { scenario: string; label: string; kind: string; total: number }[]; targets: { groups: string[]; wells: string[] }
}
export const getCharts = (names: string[], by: string, target: string) =>
  call<ChartsView>('/api/charts?' + new URLSearchParams({ names: names.join('|'), by, target }))

export interface HistoryBody {
  mode: 'daily' | 'dates'; files?: string[]; dates?: string; periods?: string; pzrg_file?: string; split?: Record<string, string[]>; stitch?: string
}
export interface HistoryLogRow {
  start: string; end: string; method: string; pzrg: number; coef: number; total_after: number; discrepancy: number; category: number; comment: string
}
export interface HistoryView {
  mode: string; steps: number; kinds: Record<string, number>; notes: string[]; from: string; to: string; sources: string[]
  correction: { periods: number; corrected: number; skipped: number; worst: number; by_method: Record<string, number> } | null
  log: HistoryLogRow[]; stitch: string[]; table: [string, string, string, number, number, number][]; volumes: Record<string, number>
}
export const runHistory = (b: HistoryBody) => call<HistoryView>('/api/history', post(b))
async function download(url: string, b: object, fallback: string) {
  const r = await fetch(url, post(b))
  if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { error?: string }).error || 'Ошибка сервера (' + r.status + ')')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(await r.blob()); a.download = fallback; a.click()
  URL.revokeObjectURL(a.href)
}
export const downloadHistorySchedule = (b: HistoryBody) => download('/api/history/schedule', b, 'schedule_history.inc')
export const downloadHistoryLog = (b: HistoryBody) => download('/api/history/log', b, 'correction_log_periods.csv')

export interface StrategyView {
  index: number; year: number; techmap: string; kind: string; months: string[]; days: Record<string, number>; groups: string[]
  base: StrategyTable; table: StrategyTable; custom: boolean; percent: number
  totals: { groups: Record<string, number>; months: Record<string, number>; season: number }
  base_totals: { groups: Record<string, number>; months: Record<string, number>; season: number }
  changes: { months: Record<string, number>; season: number }
}
export const getStrategy = (name: string, index: number) => call<StrategyView>('/api/strategy?name=' + encodeURIComponent(name) + '&index=' + index)
export const strategyOp = (name: string, index: number, table: StrategyTable, op: string, extra: { group?: string; month?: string; value?: number } = {}) =>
  call<StrategyView>('/api/strategy/op', post({ name, index, table, op, ...extra }))
export const saveStrategy = (name: string, index: number, table: StrategyTable | null, all: boolean) =>
  call<AppState>('/api/strategy/save', post({ name, index, table, all }))
export const loadStrategy = (name: string, path: string) => call<{ state: AppState; report: string[] }>('/api/strategy/load', post({ name, path }))
export const downloadStrategy = (name: string) => download('/api/strategy/xlsx', { name }, 'strategy.xlsx')
export interface SourcesView {
  sources: { flows?: { paths: string[]; template: string; kind_default: string }; groups?: { mode: 'file' | 'column'; path: string }; daily_total?: { path: string; unit: string } }
  wells: number; groups: number; withoutGroup: number; techmaps: number
  daily: { days: number; from: string; to: string; error?: string } | null
}
export interface SourcesCheck extends SourcesView { summary: string; issues: { level: string; message: string; well: string }[] }
export const getSources = () => call<SourcesView>('/api/sources')
export const setSources = (body: { flows?: { paths: string[]; template?: string; kind_default?: string }; groups?: { mode: string; path: string }; daily_total?: { path: string; unit: string } }) =>
  call<SourcesView>('/api/sources/set', post(body))
export const buildSources = () => call<SourcesCheck>('/api/sources/build', post({}))
export const pickFiles = async (start: string) => ((await openFilePicker({ start, mode: 'files' })) || '').split('\n').filter(Boolean)

export interface ResultsInfo {
  scenario: string; path: string; files: Record<string, string>; missing: string[]; start: string | null; end: string | null; steps: number
  vectors: { keyword: string; label: string; unit: string; objects: number }[]
}
export interface IndicatorRow { date: string; gas_pore_volume: number; cells: number; columns: number; gwc_min: number | null; gwc_mean: number | null; gwc_mean_area: number | null; gwc_max: number | null }
export const getResults = (scenario: string) => call<ResultsInfo>('/api/results?scenario=' + encodeURIComponent(scenario))
export const attachResults = (scenario: string, path: string) => call<{ scenario: string; path: string }>('/api/results/attach', post({ scenario, path }))
export const getResultSeries = (scenario: string, keyword: string, objects: string[]) =>
  call<{ keyword: string; series: Record<string, { dates: string[]; values: number[] }> }>('/api/results/series?' + new URLSearchParams({ scenario, keyword, objects: objects.join('|') }))
export const getIndicators = (scenario: string, sg: string, dates: string[]) =>
  call<{ rows: IndicatorRow[]; notes: string[] }>('/api/results/indicators?' + new URLSearchParams({ scenario, sg, dates: dates.join('|') }))
