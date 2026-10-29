import { viewGsp, viewSeason, viewSummary, viewWork, mergeAll } from './wellView'
import { openFilePicker } from '../../../pxg_core/web-ui/FilePicker'
import { colorOfGroup, groupColors } from '../../../pxg_core/web-ui/groupColors'
import type { GisModelWells, GisVariants } from './allWells'
export interface FileCheck { id: string; label: string; path: string; ok: boolean; info: string }
export interface AtlasProject { id: string; name: string; updated: string; demo: boolean; tables: Record<string, number> }
export interface AtlasInfo { storage: string; fromEnv: boolean; project: string; chosen: boolean; url: string; projects: AtlasProject[] }
export interface AppState { state: 'idle' | 'loading' | 'ready' | 'error'; log: string[]; paths: Record<string, string>; checks: FileCheck[]; resultsDir: string; gsps: string[]; gspMeta: Record<string, { grid: boolean; xy: boolean }>; atlas: AtlasInfo }
export interface Pos { x: number; y: number; src: 'grid' | 'xy' | 'fit'; dir: string }
export interface Layout { mode: 'grid' | 'xy'; wells: Record<string, Pos>; missing: number[]; notes: string[]; has_grid: boolean; has_xy: boolean }
export interface SeasonInfo { key: string; start: number; end: number; manual?: boolean }
export interface WaterRec { well: number; month: number; year: number; kind: string; season: string; factor: number | null; flow: number | null; note: string }
export interface TrendRow { Скважина: number; Направление: string; Тренд_расхода: number; Тренд_воды: number; Средний_расход: number }
export interface Series { days: number[]; bar: number[] }
export interface GspData {
  gsp: string; wells: number[]; layout: Layout; seasons: Record<'Отбор' | 'Закачка', SeasonInfo[]>
  periods: { day: number; type: string }[]; water: WaterRec[]
  gspFlow: Series; pressure: { gsp?: Series; obj?: Series }; seasonPressure: { gsp: Record<string, number>; obj: Record<string, number> }
  /** Для набора из нескольких ГСП: какие группы вошли и какой группе принадлежит скважина. */
  groups?: string[]; groupOf?: Record<string, string>
  /** Все скважины набора до фильтра скважин вкладки (wellView.ts); без фильтра пусто. */
  all?: { wells: number[]; groupOf: Record<string, string> }
  warnings: string[]; trends: TrendRow[]; depths: Record<string, [number, number]>; altitude: Record<string, number>
}
export interface SeasonData { wells: number[]; days: number[]; flow: number[][] }

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body.error || 'Ошибка сервера (' + r.status + ')')
  return body as T
}
const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const getState = () => call<AppState>('/api/state')
export const saveConfig = (paths: Record<string, string>, resultsDir?: string, load = true) =>
  call<AppState>('/api/config', post({ paths, resultsDir, load }))
/** Ручная правка типа сезона (решение за инженером); to = «auto» возвращает тип из Атласа. */
export const setSeasonKind = (kind: string, season: string, to: string) =>
  call<{ ok: boolean }>('/api/season-kind', post({ kind, season, to }))
/** Режим «весь объект»: все ГСП на одной карте. Данные собираются из обычных запросов по каждому ГСП. */
export const ALL_GSP = 'Весь объект'
let allGroups: string[] = []
export const setAllGroups = (gs: string[]) => { allGroups = gs }
/** Набор из нескольких ГСП называется по именам через « + »; все группы сразу — «Весь объект». */
export const GROUP_SEP = ' + '
export const groupsOf = (name: string): string[] => (name === ALL_GSP ? allGroups : name.includes(GROUP_SEP) ? name.split(GROUP_SEP) : [name])
export const isMulti = (name: string) => groupsOf(name).length > 1
export const nameOf = (sel: string[]) => {
  const ordered = allGroups.filter(n => sel.includes(n))
  return ordered.length === allGroups.length && ordered.length > 1 ? ALL_GSP : ordered.join(GROUP_SEP)
}
/** Цвета групп: сквозная палитра «Атлас-N» (pxg_core/web-ui/groupColors.ts), цвет группы не зависит от того, какие группы выбраны. */
export const groupColor = (name: string) => colorOfGroup(name, groupColors(allGroups))

function mergeGsp(list: GspData[], name: string): GspData {
  const kinds = ['Отбор', 'Закачка'] as const
  const seasons = { Отбор: [], Закачка: [] } as GspData['seasons']
  for (const k of kinds) {
    const m = new Map<string, SeasonInfo>()
    for (const g of list) for (const s of g.seasons[k]) {
      const c = m.get(s.key)
      m.set(s.key, c ? { key: s.key, start: Math.min(c.start, s.start), end: Math.max(c.end, s.end) } : { ...s })
    }
    seasons[k] = [...m.values()].sort((p, q) => p.start - q.start)
  }
  // сетки разных ГСП нарисованы каждая со своего нуля: ставим их рядом по горизонтали; координаты XY общие и не сдвигаются
  const wells: Record<string, Pos> = {}
  let shift = 0
  const allXy = list.every(g => g.layout.mode === 'xy' || !Object.keys(g.layout.wells).length)
  for (const g of list) {
    const ps = Object.values(g.layout.wells)
    const dx = allXy || !ps.length ? 0 : shift - Math.min(...ps.map(p => p.x))
    for (const [w, p] of Object.entries(g.layout.wells)) wells[w] = { ...p, x: p.x + dx }
    if (ps.length && !allXy) shift = Math.max(...ps.map(p => p.x + dx)) + 3
  }
  const days = [...new Set(list.flatMap(g => g.gspFlow.days))].sort((p, q) => p - q)
  const at = new Map(days.map((d, i) => [d, i]))
  const bar = days.map(() => 0)
  for (const g of list) g.gspFlow.days.forEach((d, i) => { bar[at.get(d)!] += g.gspFlow.bar[i] })
  const pr = list.find(g => g.pressure.obj)?.pressure.obj
  return {
    gsp: name, wells: list.flatMap(g => g.wells),
    groups: list.map(g => g.gsp), groupOf: Object.fromEntries(list.flatMap(g => g.wells.map(w => [String(w), g.gsp] as [string, string]))),
    layout: { mode: allXy ? 'xy' : 'grid', wells, missing: list.flatMap(g => g.layout.missing), has_grid: list.some(g => g.layout.has_grid), has_xy: list.some(g => g.layout.has_xy),
      notes: Array.from(new Set(list.flatMap(g => g.layout.notes))).concat(allXy ? [] : ['Положения из сетки: ГСП стоят рядом, масштаб между ними условный.']) },
    seasons, periods: list[0].periods, water: list.flatMap(g => g.water),
    gspFlow: { days, bar }, pressure: pr ? { obj: pr } : {}, seasonPressure: { gsp: {}, obj: list[0].seasonPressure.obj },
    warnings: Array.from(new Set(list.flatMap(g => g.warnings))), trends: list.flatMap(g => g.trends),
    depths: Object.assign({}, ...list.map(g => g.depths)), altitude: Object.assign({}, ...list.map(g => g.altitude)),
  }
}

function mergeSeason(list: SeasonData[]): SeasonData {
  const days = [...new Set(list.flatMap(d => d.days))].sort((p, q) => p - q)
  const at = new Map(days.map((d, i) => [d, i]))
  const wells: number[] = [], flow: number[][] = []
  for (const d of list) d.wells.forEach((w, i) => {
    const row = new Array(days.length).fill(0)
    d.days.forEach((x, j) => { row[at.get(x)!] = d.flow[i][j] })
    wells.push(w); flow.push(row)
  })
  return { wells, days, flow }
}

export interface Locate { well: number; gsp: string; groups: string[] }
/** Адрес карты: настоящее имя группы (с учётом «-»/«_»/пробелов) и все группы, где есть скважина. */
export const locateWell = (gsp: string, well: number) => call<Locate>('/api/locate?' + new URLSearchParams({ gsp, well: String(well) }))

export const getGsp = async (name: string, mode: string): Promise<GspData> => {
  if (!isMulti(name)) return viewGsp(await call<GspData>('/api/gsp?name=' + encodeURIComponent(name) + '&mode=' + mode))
  const list = await Promise.all(groupsOf(name).map(n => getGsp(n, mode)))
  return { ...mergeGsp(list, name), all: mergeAll(list) }
}
export const getSeason = async (gsp: string, kind: string, season: string): Promise<SeasonData> => {
  if (isMulti(gsp)) return mergeSeason((await Promise.all(groupsOf(gsp).map(n => getSeason(n, kind, season)))).filter(d => d.wells.length))
  return viewSeason(await call<SeasonData>('/api/season?gsp=' + encodeURIComponent(gsp) + '&kind=' + encodeURIComponent(kind) + '&season=' + encodeURIComponent(season)), gsp)
}
export const exportExcel = (gsp: string, mode: string) => call<{ name: string; path: string }>('/api/export', post({ gsp, mode }))
// Свой проводник вместо окна Tk; пустой путь — отмена, несколько файлов — по пути на строку.
export const pickPath = async (kind: 'file' | 'folder' | 'files', start: string) => ({ path: (await openFilePicker({ start, mode: kind })) || '' })
export const openFolder = () => call<{ ok: boolean }>('/api/open-folder', post({}))
export const saveImage = (name: string, blob: Blob) =>
  call<{ name: string; path: string }>('/api/image?name=' + encodeURIComponent(name), { method: 'POST', body: blob })

export interface WorkSeason { kind: 'Отбор' | 'Закачка'; key: string; total: number[]; days: number[]; first: number[]; idle: number[]; start: number; end: number }
export interface WorkData { wells: number[]; seasons: WorkSeason[]; months: number[]; monthFlow: number[][]; monthDays: number[][]; monthWater: number[][] }
/** Параметр проекта Атласа по скважинам: таблица и числовая колонка (см. /api/params). */
export interface ParamItem { table: string; column: string; title: string; label: string; rows: number; perWell: boolean }
export interface ParamValues { table: string; column: string; agg: string; title: string; values: Record<string, number>; warnings: string[] }
/** ГИС и ГВК из базы ГИС проекта Атласа: что есть (пачки, сезоны, показатели) и значения по скважинам (см. /api/gis). */
export interface GisCatalog { packs: string[]; seasons: { key: string; wells: number }[]; metrics: { key: string; label: string }[]; note: string }
export interface GisValues { values: Record<string, number>; dates: Record<string, string>; options: Record<string, string[]>; title: string; warnings: string[] }
/** ГВК модели и отклонение «модель − факт» из последнего сравнения в ГДМ. */
export interface GisModel { model: Record<string, number>; delta: Record<string, number>; dates: Record<string, string>; info: string; warnings: string[] }
export const getGisModel = (pack: string, season: string) => call<GisModel>('/api/gis/model?' + new URLSearchParams({ pack, season }))
/** ГВК всех скважин модели на шаге рестарта у даты («» — последний); preset — пресет критерия «газ». */
/** ГВК всех скважин модели по нескольким критериям (варианты из настройки, см. parseSpec). */
export const getGisModelWellsVariants = (model: string, date: string, spec: [string, number[]][]) => call<GisVariants>('/api/gis/model-wells-variants?' + new URLSearchParams({ model, date, spec: JSON.stringify(spec) }))
export const getGisModelWells = (model: string, date: string, preset: string) => call<GisModelWells>('/api/gis/model-wells?' + new URLSearchParams({ model, date, preset }))
/** Кровля пласта из модели: растр отметок (а.о.) верха ячеек слоя; строки идут по возрастанию Y, пропуск — null. */
export interface RoofGrid { x0: number; y0: number; dx: number; dy: number; nx: number; ny: number; z: (number | null)[][]; layers: number; note: string; mapaxes?: boolean }
/** Многоугольники из файла «имя X Y» (координаты как в XY tNavigator). */
export interface Poly { name: string; pts: [number, number][] }
export const getPolygons = () => call<{ polygons: Poly[]; warnings: string[] }>('/api/polygons')
export const getRoof = (model: string, layer: number) => call<RoofGrid>('/api/roof?' + new URLSearchParams({ model, layer: String(layer) }))
/** Сбой или пустой результат в окне — в лог программы (Проект/logs/gsp_maps.log), чтобы причину можно было найти. Сам не падает. */
export const reportIssue = (where: string, text: string) => { fetch('/api/client-log', post({ where, text })).catch(() => undefined) }
/** Наблюдательные и геофизические скважины по фондам проекта Атласа (вкладка «Фонды скважин»); без координат — в missing. */
export interface ObserverWell { well: number; fund: 'observation' | 'geophysical'; why: string[]; manual: boolean; x?: number; y?: number }
export interface Observers { wells: ObserverWell[]; missing: ObserverWell[]; note: string }
export const getObservers = () => call<Observers>('/api/observers')
export const getGis = () => call<GisCatalog>('/api/gis')
export const getGisValues = (pack: string, metric: string, season: string, against: string, pins: Record<string, string>) =>
  call<GisValues>('/api/gis/values?' + new URLSearchParams({ pack, metric, season, against, pins: Object.entries(pins).map(([w, d]) => `${w}:${d}`).join(',') }))
export const getParams = () => call<{ items: ParamItem[] }>('/api/params')
export const getParam = (table: string, column: string, agg: string) =>
  call<ParamValues>('/api/param?' + new URLSearchParams({ table, column, agg }))
export const getWork = async (gsp: string) => viewWork(await call<WorkData>('/api/work?name=' + encodeURIComponent(gsp)), gsp)

/** Модели tNavigator: папки из общего списка (~/.pxg), найденные модели и отмеченные для карты. */
export interface TnavModel { id: string; name: string; folder: string; files: string[]; summary: boolean; indicators: boolean; missing: string[]; selected: boolean }
export interface ModelsView { folders: string[]; models: TnavModel[]; selected: string[] }
export interface ModelKeyword { keyword: string; unit: string; wells: number }
export interface ModelValues { keyword: string; agg: string; models: Record<string, { values?: Record<string, number>; unit?: string; error?: string }> }
export const getModels = () => call<ModelsView>('/api/models')
export const setModelFolders = (folders: string[]) => call<ModelsView>('/api/models/folders', post({ folders }))
export const selectModels = (selected: string[]) => call<ModelsView>('/api/models/select', post({ selected }))
export const getModelKeywords = (model: string) => call<{ model: string; items: ModelKeyword[] }>('/api/model-keywords?' + new URLSearchParams({ model }))
export const getModelValues = (keyword: string, start: string, end: string, agg: string, models: string[]) =>
  call<ModelValues>('/api/model-values?' + new URLSearchParams({ keyword, start, end, agg, models: models.join('|') }))

export interface SummaryData { columns: string[]; rows: (string | number | null)[][] }
export const getSummary = async (gsp: string, kind: string, season: string, mode: string) =>
  viewSummary(await call<SummaryData>('/api/summary?gsp=' + encodeURIComponent(gsp) + '&kind=' + encodeURIComponent(kind) + '&season=' + encodeURIComponent(season) + '&mode=' + mode), gsp)
