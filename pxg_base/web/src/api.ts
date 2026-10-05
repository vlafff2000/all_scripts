export interface ParamOption { value: string; label: string }
export interface Param {
  id: string; label: string; kind: 'folder' | 'file' | 'paths' | 'lines' | 'choice' | 'bool' | 'text'
  default: string; required: boolean; hint: string; when: string; options: ParamOption[]
}
export interface ModuleInfo {
  id: string; group: string; title: string; description: string
  web: boolean; note: string; params: Param[]
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
export const pickPath = (kind: 'folder' | 'file', start: string) =>
  call<{ path: string }>(`/api/pick?kind=${kind}&start=${encodeURIComponent(start)}`).then(r => r.path)
export const openFolder = (id: string) => call<{ ok: boolean }>(`/api/jobs/${id}/open`, { method: 'POST' })
