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
  pressure: { gsp?: Series; obj?: Series }; seasonPressure: { gsp: Record<string, number>; obj: Record<string, number> }
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
export const getGsp = (name: string, mode: string) => call<GspData>('/api/gsp?name=' + encodeURIComponent(name) + '&mode=' + mode)
export const getSeason = (gsp: string, kind: string, season: string) =>
  call<SeasonData>('/api/season?gsp=' + encodeURIComponent(gsp) + '&kind=' + encodeURIComponent(kind) + '&season=' + encodeURIComponent(season))
export const exportExcel = (gsp: string, mode: string) => call<{ name: string; path: string }>('/api/export', post({ gsp, mode }))
export const pickPath = (kind: 'file' | 'folder' | 'files', start: string) =>
  call<{ path: string }>('/api/pick?kind=' + kind + '&start=' + encodeURIComponent(start))
export const openFolder = () => call<{ ok: boolean }>('/api/open-folder', post({}))
export const saveImage = (name: string, blob: Blob) =>
  call<{ name: string; path: string }>('/api/image?name=' + encodeURIComponent(name), { method: 'POST', body: blob })

export interface WorkSeason { kind: 'Отбор' | 'Закачка'; key: string; total: number[]; days: number[]; first: number[]; idle: number[]; start: number; end: number }
export interface WorkData { wells: number[]; seasons: WorkSeason[]; months: number[]; monthFlow: number[][]; monthDays: number[][]; monthWater: number[][] }
export const getWork = (gsp: string) => call<WorkData>('/api/work?name=' + encodeURIComponent(gsp))
