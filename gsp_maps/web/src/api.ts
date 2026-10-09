import { openFilePicker } from '../../../pxg_core/web-ui/FilePicker'
export interface FileCheck { id: string; label: string; path: string; ok: boolean; info: string }
export interface AppState { state: 'idle' | 'loading' | 'ready' | 'error'; log: string[]; paths: Record<string, string>; checks: FileCheck[]; resultsDir: string; gsps: string[]; gspMeta: Record<string, { grid: boolean; xy: boolean }> }
export interface Pos { x: number; y: number; src: 'grid' | 'xy' | 'fit'; dir: string }
export interface Layout { mode: 'grid' | 'xy'; wells: Record<string, Pos>; missing: number[]; notes: string[]; has_grid: boolean; has_xy: boolean }
export interface SeasonInfo { key: string; start: number; end: number }
export interface WaterRec { well: number; month: number; year: number; factor: number | null; flow: number | null; note: string }
export interface TrendRow { Скважина: number; Направление: string; Тренд_расхода: number; Тренд_воды: number; Средний_расход: number }
export interface Series { days: number[]; bar: number[] }
export interface GspData {
  gsp: string; wells: number[]; layout: Layout; seasons: Record<'Отбор' | 'Закачка', SeasonInfo[]>
  periods: { day: number; type: string }[]; water: WaterRec[]
  gspFlow: Series; pressure: { gsp?: Series; obj?: Series }; seasonPressure: { gsp: Record<string, number>; obj: Record<string, number> }
  /** Для набора из нескольких ГСП: какие группы вошли и какой группе принадлежит скважина. */
  groups?: string[]; groupOf?: Record<string, string>
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
export const scanFolder = (folder: string) => call<AppState>('/api/scan', post({ folder }))
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
/** Цвета групп: ряд Окабе–Ито, цвет группы не зависит от того, какие группы выбраны. */
const GROUP_COLORS = ['#0072b2', '#d55e00', '#009e73', '#cc79a7', '#e69f00', '#56b4e9', '#7a5195', '#8c564b', '#6b8e23', '#b8860b', '#17becf', '#e377c2']
export const groupColor = (name: string) => GROUP_COLORS[Math.max(0, allGroups.indexOf(name)) % GROUP_COLORS.length]

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

export const getGsp = async (name: string, mode: string): Promise<GspData> => {
  if (!isMulti(name)) return call<GspData>('/api/gsp?name=' + encodeURIComponent(name) + '&mode=' + mode)
  return mergeGsp(await Promise.all(groupsOf(name).map(n => getGsp(n, mode))), name)
}
export const getSeason = async (gsp: string, kind: string, season: string): Promise<SeasonData> => {
  if (isMulti(gsp)) return mergeSeason((await Promise.all(groupsOf(gsp).map(n => getSeason(n, kind, season)))).filter(d => d.wells.length))
  return call<SeasonData>('/api/season?gsp=' + encodeURIComponent(gsp) + '&kind=' + encodeURIComponent(kind) + '&season=' + encodeURIComponent(season))
}
export const exportExcel = (gsp: string, mode: string) => call<{ name: string; path: string }>('/api/export', post({ gsp, mode }))
// Свой проводник вместо окна Tk; пустой путь — отмена, несколько файлов — по пути на строку.
export const pickPath = async (kind: 'file' | 'folder' | 'files', start: string) => ({ path: (await openFilePicker({ start, mode: kind })) || '' })
export const openFolder = () => call<{ ok: boolean }>('/api/open-folder', post({}))
export const saveImage = (name: string, blob: Blob) =>
  call<{ name: string; path: string }>('/api/image?name=' + encodeURIComponent(name), { method: 'POST', body: blob })

export interface WorkSeason { kind: 'Отбор' | 'Закачка'; key: string; total: number[]; days: number[]; first: number[]; idle: number[]; start: number; end: number }
export interface WorkData { wells: number[]; seasons: WorkSeason[]; months: number[]; monthFlow: number[][]; monthDays: number[][]; monthWater: number[][] }
export const getWork = (gsp: string) => call<WorkData>('/api/work?name=' + encodeURIComponent(gsp))

export interface SummaryData { columns: string[]; rows: (string | number | null)[][] }
export const getSummary = (gsp: string, kind: string, season: string, mode: string) =>
  call<SummaryData>('/api/summary?gsp=' + encodeURIComponent(gsp) + '&kind=' + encodeURIComponent(kind) + '&season=' + encodeURIComponent(season) + '&mode=' + mode)
