import { openFilePicker } from '../../../pxg_core/web-ui/FilePicker'
export interface Template {
  name: string; sheet: string | number | null; header_row: number
  well: string; date: string; rate: string; hourly: string; hours: string; kind: string; group: string; kind_default: string; unit: string; layout?: string
}
export interface AppState { folder: string; project: string; templates: Template[]; units: string[]; kinds: string[]; techmaps: TechMapInfo[]; scenarios: ScenarioInfo[]; pzrg_window?: { lo: number; hi: number } }
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
  unknown: string[]; params: AvgParams; sources: string[]
}
export interface AvgWellView {
  well: string; group: string; months: string[]; years: number[]; byYear: Record<string, (number | null)[]>; mean: (number | null)[]
  chosen: number[] | null; manual: Record<string, number>; autoExcluded: Record<string, string>; autoMonths: Record<string, string[]>
  table: { years: string; n: number; holdout: number | null; closeness: number | null; stability: number | null; advice: boolean; chosen: boolean }[]
}
const avgBody = (kind: string, rest: object) => post({ kind, ...rest })
export const getAveraging = (kind: string) => call<AvgView>('/api/averaging?kind=' + encodeURIComponent(kind))
export const getAveragingWell = (kind: string, well: string) => call<AvgWellView>('/api/averaging/well?kind=' + encodeURIComponent(kind) + '&well=' + encodeURIComponent(well))
export interface AvgStatus {
  kind: string; files: number; paths: string[]; template: string; wells: number; groups: number; withoutGroup: number; months: string[]
  reference: boolean; seasons: number[]; problem: '' | 'files' | 'techmap' | 'columns' | 'wells' | 'seasons'; error?: string; rows?: number
  params: AvgParams; methods: string[]
}
export interface AvgParams { max_years: number; last_k: number; metric: string; mode: 'day' | 'month'; seasons: number[]; method: string }
export interface AvgDaily {
  kind: string; seasons: number[]; days: number; method: string; dates?: string[]
  groups: Record<string, { wells: Record<string, (number | null)[]>; filled: { day: number; date: string; how: string }[] }>
  summary: { filled?: number; by?: Record<string, number> }; notes: string[]
}
export const getAvgStatus = (kind: string) => call<AvgStatus>('/api/averaging/status?kind=' + encodeURIComponent(kind))
export const getAvgDaily = (kind: string) => call<AvgDaily>('/api/averaging/daily?kind=' + encodeURIComponent(kind))
export const setAvgParams = (kind: string, params: Partial<AvgParams>) => call<unknown>('/api/averaging/params', avgBody(kind, { params }))
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
  mode: 'daily' | 'dates'; files?: string[]; dates?: string; periods?: string; pzrg_file?: string; split?: Record<string, string[]>; stitch?: string; window_lo?: string; window_hi?: string
}
export interface HistoryLogRow {
  start: string; end: string; method: string; pzrg: number; coef: number; total_after: number; discrepancy: number; category: number; comment: string; unallocated: number; lo: number; hi: number
}
export interface ResidualRow { date: string; kind: string; pzrg: number; wells: number; residual: number; pct: number; pct3: number; hint: string }
export interface ResidualView {
  summary: { days: number; median: number; spread: number; over: number; shift: number; verdict: string }; rows: ResidualRow[]; shown: number; total: number
}
export interface HistoryView {
  mode: string; steps: number; kinds: Record<string, number>; notes: string[]; from: string; to: string; sources: string[]
  correction: { periods: number; corrected: number; skipped: number; worst: number; unallocated: number; by_method: Record<string, number> } | null
  window: { lo: number; hi: number } | null; residual: ResidualView | null
  log: HistoryLogRow[]; stitch: string[]; table: [string, string, string, number, number, number][]; volumes: Record<string, number>
}
export const runHistory = (b: HistoryBody) => call<HistoryView>('/api/history', post(b))
/** Запрос файла: при ошибке сервера - текст из его ответа (JSON с полем error). */
async function fetchFile(url: string, b: object): Promise<Response> {
  const r = await fetch(url, post(b))
  if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { error?: string }).error || 'Ошибка сервера (' + r.status + ')')
  return r
}
async function download(url: string, b: object, fallback: string) {
  const r = await fetchFile(url, b)
  const a = document.createElement('a')
  a.href = URL.createObjectURL(await r.blob()); a.download = fallback; a.click()
  URL.revokeObjectURL(a.href)
}
export const downloadHistorySchedule = (b: HistoryBody) => download('/api/history/schedule', b, 'schedule_history.inc')
export const downloadHistoryResidual = (b: HistoryBody) => download('/api/history/residual', b, 'residual_by_day.csv')
export const downloadHistoryLog = (b: HistoryBody) => download('/api/history/log', b, 'correction_log_periods.csv')

export interface StrategyView {
  index: number; year: number; techmap: string; kind: string; months: string[]; days: Record<string, number>; groups: string[]
  base: StrategyTable; table: StrategyTable; custom: boolean; percent: number
  totals: { groups: Record<string, number>; months: Record<string, number>; season: number }
  base_totals: { groups: Record<string, number>; months: Record<string, number>; season: number }
  changes: { months: Record<string, number>; season: number }
  target: number; residual: number; percents: Record<string, number>; locks: [string, string][]
}
export interface StrategyExtra { group?: string; month?: string; value?: number; groups?: string[]; months?: string[]; mode?: string }
export interface CopyReport { index: number; year: number; techmap: string; moved: number; skipped: string[]; delta: number; message: string }
export const getStrategy = (name: string, index: number) => call<StrategyView>('/api/strategy?name=' + encodeURIComponent(name) + '&index=' + index)
export const strategyOp = (name: string, index: number, table: StrategyTable, op: string, extra: StrategyExtra = {},
  locks: [string, string][] = [], target?: number) =>
  call<StrategyView>('/api/strategy/op', post({ name, index, table, op, locks, target, ...extra }))
export const saveStrategy = (name: string, index: number, table: StrategyTable | null, all: boolean, locks: [string, string][] = []) =>
  call<AppState>('/api/strategy/save', post({ name, index, table, all, locks }))
export const copyStrategy = (name: string, index: number, table: StrategyTable, locks: [string, string][], targets: number[]) =>
  call<AppState & { report: CopyReport[] }>('/api/strategy/copy', post({ name, index, table, locks, targets }))
export const loadStrategy = (name: string, path: string) => call<{ state: AppState; report: string[] }>('/api/strategy/load', post({ name, path }))
export const downloadStrategy = (name: string) => download('/api/strategy/xlsx', { name }, 'strategy.xlsx')
export interface SourcesView {
  sources: { flows?: { paths: string[]; template: string; kind_default: string }; groups?: { mode: 'file' | 'column'; path: string }; daily_total?: { path: string; unit: string }; gis?: { folder?: string; perf_file?: string } }
  wells: number; groups: number; withoutGroup: number; techmaps: number
  daily: { days: number; from: string; to: string; error?: string } | null
}
export interface SourcesCheck extends SourcesView { summary: string; issues: { level: string; message: string; well: string }[] }
export const getSources = () => call<SourcesView>('/api/sources')
export const setSources = (body: { flows?: { paths: string[]; template?: string; kind_default?: string }; groups?: { mode: string; path: string }; daily_total?: { path: string; unit: string }; gis?: { folder: string; perf_file: string } }) =>
  call<SourcesView>('/api/sources/set', post(body))
export const buildSources = () => call<SourcesCheck>('/api/sources/build', post({}))
/** Папка выгрузок Базы ПХГ: сервер находит базу расходов по имени и ставит её источником. */
export const sourcesFromFolder = (folder: string) => call<SourcesView & { found: string[] }>('/api/sources/folder', post({ folder }))
export const pickFiles = async (start: string) => ((await openFilePicker({ start, mode: 'files' })) || '').split('\n').filter(Boolean)
export const pickFolder = async (start: string) => (await openFilePicker({ start, mode: 'folder' })) || ''

export interface ResultsInfo {
  model: string; path: string; files: Record<string, string>; missing: string[]; start: string | null; end: string | null; steps: number
  vectors: { keyword: string; label: string; unit: string; objects: number }[]
}
export interface ModelEntry { id: string; name: string; folder: string; files: string[]; summary: boolean; indicators: boolean; missing: string[]; selected: boolean }
export interface ModelsView { folders: string[]; models: ModelEntry[] }
export interface IndicatorRow { date: string; gas_pore_volume: number; cells: number; columns: number; gwc_min: number | null; gwc_mean: number | null; gwc_mean_area: number | null; gwc_max: number | null }
export const getModels = () => call<ModelsView>('/api/models')
export const setModelFolders = (folders: string[]) => call<ModelsView>('/api/models/folders', post({ folders }))
export const setModelSelection = (selected: string[]) => call<ModelsView>('/api/models/select', post({ selected }))
export const getResults = (model: string) => call<ResultsInfo>('/api/results?' + new URLSearchParams({ model }))
export const getResultSeries = (model: string, keyword: string, objects: string[]) =>
  call<{ keyword: string; series: Record<string, { dates: string[]; values: number[] }> }>('/api/results/series?' + new URLSearchParams({ model, keyword, objects: objects.join('|') }))
export const getIndicators = (model: string, sg: string, dates: string[]) =>
  call<{ rows: IndicatorRow[]; notes: string[] }>('/api/results/indicators?' + new URLSearchParams({ model, sg, dates: dates.join('|') }))
export interface WellGwcRow { well: string; date: string; columns: number; cell_top_down: number | null; interp_top_down: number | null; cell_lowest: number | null; interp_lowest: number | null; torn: boolean; at_grid_edge: boolean }
export const getWellGwc = (model: string, sgr: string, dates: string[], wells: string[]) =>
  call<{ rows: WellGwcRow[]; notes: string[]; sgr_source: string; wells: string[] }>('/api/results/wellgwc?' + new URLSearchParams({ model, sgr, dates: dates.join('|'), wells: wells.join('|') }))

export const getResultsReport = (path: string, kind: 'model' | 'restart') =>
  call<{ text: string }>('/api/results/report?' + new URLSearchParams({ path, kind }))

export interface QualityRow { id: string; dataset: string; well: string; date: string; kind: string; check: string; level: string; value: string; details: string; excluded: boolean }
export interface QualityView {
  jump: number; total: number; errors: number; excluded: number; shown: number; datasets: Record<string, string>
  summary: { dataset: string; check: string; level: string; count: number }[]; rows: QualityRow[]
  excludedRows: { id: string; dataset: string; well: string; date: string; kind: string }[]
}
export const getQuality = (jump: number) => call<QualityView>('/api/quality?jump=' + jump)
export const excludeRows = (b: { ids?: string[]; level?: string; check?: string; dataset?: string; jump?: number; on?: boolean; all_restore?: boolean }) =>
  call<{ changed: number; excluded: number }>('/api/quality/exclude', post(b))

export interface GroupMapRow { key: string; techmaps: string[]; volume: number; group: string | null; source: 'auto' | 'manual' | 'none'; wells: number }
export interface GroupMap { rows: GroupMapRow[]; groups: { group: string; wells: number }[]; unused: string[] }
export const getGroupMap = () => call<GroupMap>('/api/groupmap')
export const setGroupMap = (key: string, group: string) => call<GroupMap>('/api/groupmap/set', post({ key, group }))

// ───── Адаптация по ГДИ ─────
export interface AdaptConfig {
  strategy: string; inflow: string; objective: string; pi_mult_bounds: [number, number]; dfac_bounds: [number, number]
  r2_ok: number; min_regimes: number; bad_gdi_policy: string; qc_enabled: boolean; n_starts: number; include_only_ok: boolean; all_dates?: boolean; include_sequential?: boolean
  well_bounds?: Record<string, { pi_mult_bounds?: [number, number]; dfac_bounds?: [number, number] }> | null
  [k: string]: unknown
}
export interface AdaptSettings { p_units: string; q_units: string; min_status: string; max_age_years: number | null; from_date: string | null }
export interface AdaptState {
  config: AdaptConfig; settings: AdaptSettings; p_units: string[]; q_units: string[]
  db: string; sheet: string; cols: Record<string, string>; saved_settings: Partial<AdaptSettings>; saved_config: Partial<AdaptConfig>
  overrides: Record<string, boolean>; study_overrides: Record<string, boolean>; scenario: string; kit: string; scenarios: { name: string; path: string }[]
}
export interface AdaptColumns { columns: string[]; detected: Record<string, string>; rows: number }
export interface AdaptRow {
  well: string; model: string; n_studies: number; n_usable: number; date: string; status: string; age_years: number | null
  a: number | null; b: number | null; n_regimes: number; note: string; include: boolean; auto: boolean; manual: number
}
/** Исследование ГДИ: заключение программы и решение инженера (manual: null - не трогали, true - взять, false - не брать). */
export interface AdaptStudy {
  well: string; model: string; date: string; key: string; status: string; reasons: string; warnings: string; n_regimes: number
  a: number | null; b: number | null; auto: boolean; manual: boolean | null; use: boolean
}
export interface AdaptSelection {
  rows: AdaptRow[]; model_only: string[]; notes: string[]; cols: Record<string, string>; studies: AdaptStudy[]
  counts: { wells_db: number; included: number; no_model: number; all_bad: number; old: number; model_only: number; manual: number }
}
export interface AdaptRequest {
  db: string; sheet?: string; cols?: Record<string, string>; settings: Partial<AdaptSettings>; config: Partial<AdaptConfig>
  overrides: Record<string, boolean>; study_overrides: Record<string, boolean>; scenario: string
}
export const getAdapt = () => call<AdaptState>('/api/adapt')
export const getAdaptColumns = (path: string, sheet = '') => call<AdaptColumns>('/api/adapt/columns?' + new URLSearchParams({ path, sheet }))
export const adaptSelect = (b: AdaptRequest) => call<AdaptSelection>('/api/adapt/select', post(b))
export const adaptKit = (b: AdaptRequest & { out: string }) => call<{ folder: string; wells: string[]; files: string[]; code: string }>('/api/adapt/kit', post(b))

export interface AdaptResultRow {
  well: string; date: string; source: string; qc: string; n_regimes: number
  pi_mult: number | null; pi_lo: number | null; pi_hi: number | null; d: number | null; old_d: number | null
  r2_old: number | null; r2: number | null; mape_old: number | null; mape: number | null
  a_gdi: number | null; b_gdi: number | null; a_model: number | null; b_model: number | null
  wbp_model: number | null; q_op: number | null; q_ratio: number | null; dp2_err_before: number | null; dp2_err_after: number | null
  ok: boolean; problems: string[]; notes: string[]; substituted: boolean; t_name: string
  q_gdi: (number | null)[]; q_before: (number | null)[]; q_after: (number | null)[]; dp2_gdi: (number | null)[]
  curve_q: (number | null)[]; curve_before: (number | null)[]; curve_after: (number | null)[]; at_bound: boolean; dep_qmax: number | null
}
export interface AdaptGroupRow { group: string; wells: number; q_gdi: number; q_before: number; q_after: number; err_before: number | null; err_after: number | null }
export interface AdaptView {
  run_dir: string; made: string; rows: AdaptResultRow[]; failures: { well: string; reason: string }[]
  summary: { wells: number; ok: number; with_problems: number; skipped: number; at_bound: number; unstable: number; r2_old: number | null; r2: number | null
    mape_old: number | null; mape: number | null; pi_mult: number | null; d: number | null; improved: number }
  groups: AdaptGroupRow[]
}
export interface AdaptRun { dir: string; name: string; has_snapshots: boolean; has_results: boolean; has_inc: boolean }
export const adaptRecompute = (kit: string, snapshots: string, config: Partial<AdaptConfig>) => call<AdaptView>('/api/adapt/recompute', post({ kit, snapshots, config }))
export const adaptRuns = (kit: string) => call<{ runs: AdaptRun[] }>('/api/adapt/runs?' + new URLSearchParams({ kit }))
export const adaptRun = (dir: string) => call<AdaptView>('/api/adapt/run?' + new URLSearchParams({ dir }))
export interface AdaptColCheck { ok: boolean; rows: number; problems: string[]; roles: { role: string; title: string; col: string; total: number; valid: number; examples: string[] }[] }
export const adaptCheckColumns = (b: { db: string; sheet?: string; cols: Record<string, string> }) => call<AdaptColCheck>('/api/adapt/columns/check', post(b))
export const adaptCode = (kit: string) => call<{ code: string; path: string }>('/api/adapt/code?' + new URLSearchParams({ kit }))
export const adaptFileUrl = (dir: string, kind: 'inc' | 'xlsx' | 'csv') => '/api/adapt/file?' + new URLSearchParams({ dir, kind })
/** Оформление графика: значения по умолчанию, пределы и подписи приходят с сервера (/api/adapt/export/options); null - авто. */
export interface AdaptChartFormat {
  font: string; font_size: number | null; x_label: string | null; y_label: string | null; title_on: boolean; title: string | null
  legend: boolean; legend_pos: string; line_width: number | null; marker: string; marker_size: number | null; grid: boolean
  x_min: number | null; x_max: number | null; y_min: number | null; y_max: number | null
}
/** Настройки индикаторной диаграммы для выгрузки: ось Y, какие кривые, оформление, ширина графика (мм), оформление. */
export interface AdaptChartStyle extends AdaptChartFormat { y: 'dp2' | 'dp2q'; variant: 'both' | 'before' | 'after'; look: 'default' | 'excel'; width: number; height?: number | null; dpi: number }
/** Значения по умолчанию вида и оформления графика (как их отдаёт сервер: размеры в мм). */
export type AdaptChartDefaults = { y: string; variant: string; look: string; dpi: number; width_mm: number; height_mm: number | null } & AdaptChartFormat
/** Причина по исследованию: «График» - скважина и дата, «Ошибка» - текст для пользователя. */
export interface AdaptExportError { 'График': string; 'Ошибка': string }
/** Одна диаграмма исследования (id = «скважина|дата»): скачивается файлом PNG / SVG / PDF / XLSX. */
export const adaptExportChart = (b: AdaptChartStyle & { run_dir: string; id: string; format: string }, fallback: string) =>
  download('/api/adapt/export/chart', b, fallback)
/** Пакет диаграмм в ZIP: ids = null - все исследования запуска, иначе выбранные. */
export const adaptExportZip = (b: AdaptChartStyle & { run_dir: string; ids: string[] | null; formats: string[] }) =>
  download('/api/adapt/export/zip', b, 'indicator_charts_' + b.y + '.zip')
/** Причины из заголовка X-Charts-Errors-List (URL-кодированный JSON); при сбое разбора - пусто. */
function reasonsOf(r: Response): AdaptExportError[] {
  const raw = r.headers.get('X-Charts-Errors-List')
  if (!raw) return []
  try { return JSON.parse(decodeURIComponent(raw)) as AdaptExportError[] } catch { return [] }
}
/** Скачивание файла из ответа и итоги: число графиков, число неудачных исследований, их причины. */
async function saveResponse(r: Response, name: string) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click()
  URL.revokeObjectURL(a.href)
  return { count: Number(r.headers.get('X-Charts-Count') || 0), errors: Number(r.headers.get('X-Charts-Errors') || 0), reasons: reasonsOf(r) }
}
/** Макет Word: плоский словарь Layout (pxg_core/word_export.py). Значения, пределы и умолчания приходят с сервера. */
export type AdaptLayout = Record<string, string | number | boolean>
export interface AdaptExportOptions {
  layout: {
    defaults: AdaptLayout; papers: Record<string, [number, number]>; fonts: string[]; aligns: string[]; dpis: number[]
    orientations: string[]; caption_pos: string[]; caption_modes: string[]; borders: string[]; width_modes: string[]
    limits: Record<string, { min: number; max: number; label: string }>
  }
  chart: { y: string[]; variant: string[]; look: string[]; dpi_png: number[]; width: [number, number]; height: [number, number]
    defaults: AdaptChartDefaults
    format: {
      fonts: [string, string][]; legend_pos: [string, string][]; markers: [string, string][]; limits: Record<string, [number, number]>
      labels: { x: string; y: Record<string, string>; title: string }; title_fields: string[]
    } }
  caption: { default: string; fields: string[] }
  preview_dpi: number
}
/** Тело выгрузки Word и предпросмотра: исследования (null - все), вид графика, макет листа, подпись и первый номер. */
export interface AdaptExportBody {
  run_dir: string; ids: string[] | null; style: AdaptChartStyle; layout: AdaptLayout; caption: string; start: number; object: string
}
export const adaptExportOptions = () => call<AdaptExportOptions>('/api/adapt/export/options')
/** Word скачивается файлом; в заголовках ответа - число графиков, число неудачных исследований и их причины. */
export async function adaptExportDocx(b: AdaptExportBody) {
  return saveResponse(await fetchFile('/api/adapt/export/docx', b), 'indicator_charts.docx')
}
/** Пакет результата одним ZIP: Word, картинки по форматам (png / svg / pdf), XLSX с точками, settings.json, errors.txt. */
export async function adaptExportAll(b: AdaptExportBody & { formats: string[] }) {
  return saveResponse(await fetchFile('/api/adapt/export/all', b), 'indicator_package_' + (b.style.y === 'dp2q' ? 'dp2_q' : 'dp2') + '.zip')
}
/** Лист Word как PNG: page - номер листа с 1, сервер ограничивает его числом листов (заголовки X-Pages, X-Page). */
export async function adaptExportPreview(b: AdaptExportBody & { page: number }): Promise<{ blob: Blob; pages: number; page: number }> {
  const r = await fetchFile('/api/adapt/export/preview', b)
  return { blob: await r.blob(), pages: Number(r.headers.get('X-Pages') || 1), page: Number(r.headers.get('X-Page') || 1) }
}

export interface FactInterval { top: number; bottom: number; kg: number | null; kp: number | null; pack: string; status: string }
export interface FactPack { pack: string; gvk: number | null; label: string; top: number | null; bottom: number | null }
export interface FactWell {
  well: string; date: string; dates: string[]; season?: string; altitude: number | null
  intervals: FactInterval[]; packs: FactPack[]; notes: string[]; perforation: { top: number | null; bottom: number | null } | null
}
export const getPlanshetFact = (wells: string[], date: string, alts: Record<string, string> = {}) =>
  call<{ rows: FactWell[]; notes: string[] }>('/api/planshet/fact?' + new URLSearchParams({
    wells: wells.join('|'), date, alts: Object.entries(alts).filter(([, v]) => v.trim() !== '').map(([w, v]) => w + ':' + v.trim()).join('|') }))
export interface ProfileCell { top: number; bottom: number; sg: number; perforated: boolean; thr: number }
export interface ModelGwc { cell: number; interp: number; at_grid_edge: boolean; lowest_cell: number; torn: boolean }
/** gwc — ГВК колонны прежней логикой «ГВК по скважинам» (сверху вниз), считает сервер. */
export interface WellProfile { well: string; date: string; column: number[]; columns: number; cells: ProfileCell[]; gwc: ModelGwc | null }
export const getWellProfile = (model: string, wells: string[], date: string, sgr = '') =>
  call<{ rows: WellProfile[]; step_date: string; missing: string[] }>('/api/results/wellprofile?' + new URLSearchParams({ model, wells: wells.join('|'), date, sgr }))

export interface CompareRow {
  key: string; well: string; group: string; date: string; season: string; slice: string; slice_why: string; pack: string; label: string
  fact: number; model: number | null; delta: number | null; status: string; excluded: boolean
}
export interface CompareResult { rows: CompareRow[]; skipped: Record<string, number>; notes: string[] }
export const comparePlanshet = (body: { model: string; wells: string[]; thr: number; slices: Record<string, string>; alts: Record<string, string> }) =>
  call<CompareResult>('/api/planshet/compare', post(body))

export interface HmRow { key: string; well: string; group: string; hist: number; model: number; diff: number; hist_avg: number; model_avg: number; diff_avg: number
  pct: number | null; status: string; label: string; why: string; excluded: boolean }
export interface HmTotal { hist: number; model: number; ref: number | null; hist_avg: number; model_avg: number; ref_avg: number | null; model_field: number | null
  status: string; label: string; why: string; differs_from_db: boolean; hist_vs_ref: number | null }
export interface HmSeason { name: string; kind: string; start: string; end: string; compared: { start: string; end: string; days: number; full: boolean } | null
  rows: HmRow[]; groups: { group: string; hist: number; model: number; diff: number; pct: number | null }[]; notes: string[]; total?: HmTotal }
export interface HmSettings { rel_pct: number; abs_k: number }
export interface HmResult { seasons: HmSeason[]; notes: string[]; settings: HmSettings; history_source: string; atlas: { projects: { id: string; name: string }[]; selected: string }
  saved: { seasons: { name: string; kind: string; start: string; end: string }[]; excluded: string[]; unit_k: number | null; schedule_path: string; atlas_project: string } }
export interface HmBody { model: string; settings?: Partial<HmSettings>; seasons?: { name: string; kind: string; start: string; end: string }[]; excluded?: string[]; unit_k?: number | null; schedule_path?: string; atlas_project?: string }
export const histModel = (b: HmBody) => call<HmResult>('/api/results/histmodel', post(b))
export const histModelXlsx = (b: HmBody) => download('/api/results/histmodel/xlsx', b, 'История_и_модель.xlsx')
