import { openFilePicker } from '../../../pxg_core/web-ui/FilePicker'
export interface ParamOption { value: string; label: string }
export interface Param {
  id: string; label: string; kind: 'folder' | 'file' | 'paths' | 'lines' | 'choice' | 'bool' | 'text'
  default: string; required: boolean; hint: string; when: string; options: ParamOption[]
}
export interface ModuleInfo {
  id: string; group: string; title: string; description: string
  web: boolean; check: boolean; note: string; command: string; params: Param[]
}
export interface Job {
  id: string; module: string; status: 'running' | 'done' | 'failed'
  started: number; finished: number | null; out_dir: string
  files: string[]; sizes: Record<string, number>; values: Record<string, string>; log: string[]; log_len: number
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body.error || `Ошибка ${r.status}`)
  return body as T
}

export const getModules = () => call<{ modules: ModuleInfo[] }>('/api/modules').then(r => r.modules)
export const startJob = (module: string, params: Record<string, string>) =>
  call<Job>('/api/jobs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ module, params }),
  })
export const getJob = (id: string, since: number) => call<Job>(`/api/jobs/${id}?since=${since}`)
export const fileUrl = (id: string, name: string) =>
  `/api/jobs/${id}/files/${name.split('/').map(encodeURIComponent).join('/')}`
export const getJobs = () => call<{ jobs: Job[] }>('/api/jobs').then(r => r.jobs)
// Свой проводник вместо окна Tk; пустая строка — отмена.
export const pickPath = async (kind: 'folder' | 'file', start: string) => (await openFilePicker({ start, mode: kind })) || ''
export const openFolder = (id: string) => call<{ ok: boolean }>(`/api/jobs/${id}/open`, { method: 'POST' })

export interface QcIssue {
  level: 'ошибка' | 'предупреждение' | 'заметка'; code: string; message: string; file: string; sheet: string
  row: string; well: string; date: string; value: string; hint: string
}
export interface QcReport {
  id: string; title: string; summary: string; counts: Record<string, number>; checked: string[]
  issues: QcIssue[]; hidden: { level: string; code: string; count: number }[]; codes: Record<string, string>
}
export const runCheck = (module: string, params: Record<string, string>) =>
  call<QcReport>('/api/check', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ module, params }),
  })
export const checkUrl = (id: string, fmt: 'xlsx' | 'txt') => `/api/check/${id}.${fmt}`

export interface DateIssue {
  Файл: string; Лист: string; Ячейка: string; Значение: string; Ожидалось: string; 'Что сделано': string
  Предложение: string; fragment: (string | number)[][]
}
export const getDateIssues = (id: string) => call<{ issues: DateIssue[] }>(`/api/jobs/${id}/date-issues`).then(r => r.issues)
export const saveDateFixes = (id: string, fixes: { file: string; sheet: string; cell: string; decision: string }[]) =>
  call<{ path: string; count: number }>(`/api/jobs/${id}/date-fixes`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fixes }),
  })

export interface WorkspaceFolder { slot: 'ready' | 'exports'; label: string; path: string; chosen: boolean; found: boolean; files: string[] }
export interface WorkspaceState { project: string; folders: WorkspaceFolder[] }
export interface WorkspaceCopyResult { source: string; name: string; status: 'copied' | 'exists' | 'missing' | 'error'; message: string }
export const getWorkspace = () => call<WorkspaceState>('/api/workspace')
export const setWorkspaceProject = (project: string) =>
  call<WorkspaceState>('/api/workspace/project', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project }),
  })
export const addReadyFiles = (paths: string[]) =>
  call<WorkspaceState & { results: WorkspaceCopyResult[] }>('/api/workspace/ready', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths }),
  })

export interface LegendRow {
  sheet: string; well: string; color: string; pack: string; source: string; status: string; reason: string
  rows: number; labels: string; confirmed: boolean; hints: string[]
}
export const getGisLegend = (file: string) =>
  call<{ rows: LegendRow[]; packs: string[]; open: number }>('/api/gis/legend', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file }),
  })
export const saveGisLegend = (file: string, choices: { sheet: string; color: string; pack: string }[]) =>
  call<{ saved: number }>('/api/gis/legend/save', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file, choices }),
  })

export interface GdisLoc { table: string; label: string; method: string; text: string; unit: string }
export interface GdisOption { loc: GdisLoc; label: string; unit: string; method: string; kind: string; heading: string; sample: string }
export interface GdisRow {
  key: string; label: string; scope: string; dim: string; required: boolean; hint: string
  current: GdisLoc | null; auto: GdisLoc | null; source: string; found: boolean; sample: string; options: GdisOption[]
}
export interface GdisTemplate {
  id: string; files: number; program: string; example: string; names: string[]; rows: GdisRow[]; saved: boolean
}
export const getGdisTemplates = (folder: string, mapping: string, method: string) =>
  call<{ templates: GdisTemplate[]; files: number; errors: { file: string; error: string }[] }>('/api/gdis/templates', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ folder, mapping, method }),
  })
export const saveGdisMapping = (template: string, name: string, mapping: Record<string, GdisLoc | null>) =>
  call<{ saved: number }>('/api/gdis/save', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ template, name, mapping }),
  })
