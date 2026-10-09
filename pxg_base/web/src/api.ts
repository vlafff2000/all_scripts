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
