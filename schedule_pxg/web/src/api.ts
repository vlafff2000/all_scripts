export interface Template {
  name: string; sheet: string | number | null; header_row: number
  well: string; date: string; rate: string; hourly: string; hours: string; kind: string; kind_default: string; unit: string
}
export interface AppState { folder: string; project: string; templates: Template[]; units: string[]; kinds: string[]; techmaps: TechMapInfo[]; scenarios: ScenarioInfo[] }
export interface ScenarioInfo { name: string; parent: string | null; note: string; percent: number; seasons: number }
export interface Season { year: number; techmap: string; percent: number; label: string }
export interface ScenarioValues {
  calendar: Season[]; grid: { step: string; periods: [string, string][]; cuts: string[] }; control: { mode?: string; level?: string; limits?: unknown[] }
  outages: unknown[]; percent: number; tolerance: number; decimals: number; note: string
}
export interface ScenarioView {
  name: string; parent: string | null; values: ScenarioValues; origin: Record<string, string>; children: string[]; notes: string[]
  diff: { field: string; label: string; parent: unknown; own: unknown }[]; fields: Record<string, string>
}
export interface BuildView {
  seasons: { techmap: string; year: number; percent: number; from: string; to: string; steps: number; over: number }[]
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
  suggest: Record<'well' | 'date' | 'rate' | 'hourly' | 'hours' | 'kind', string>; unit: string; total: number; format: string | null
}
export interface Trial {
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
export const pickFile = (start: string) => call<{ path: string }>('/api/pick?start=' + encodeURIComponent(start))
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
