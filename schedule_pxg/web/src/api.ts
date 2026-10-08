export interface Template {
  name: string; sheet: string | number | null; header_row: number
  well: string; date: string; rate: string; hourly: string; hours: string; kind: string; kind_default: string; unit: string
}
export interface AppState { folder: string; project: string; templates: Template[]; units: string[]; kinds: string[] }
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
