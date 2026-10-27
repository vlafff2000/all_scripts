// Запросы к серверу «Поисковика» и общие типы.
export interface Item { name: string; dir: boolean; size: number; mtime: string; ext: string; locked: boolean; path?: string }
export interface Listing { path: string; parent: string; items: Item[]; total: number; truncated: boolean; error: string; network?: boolean; cached?: boolean; lazy?: boolean }
export interface Place { name: string; path: string; kind: string }
export interface Fav { path: string; name: string; network?: boolean; n?: number }
export interface Favs { favorites: Fav[]; frequent: Fav[] }
export interface Meta { color?: string; tags?: string[]; note?: string }
export interface JobSnap { id: string; kind: string; done: boolean; error: string; cancelled: boolean; items: any[]; next: number; info: Record<string, any>; elapsed: number }
export interface IndexRoot { root: string; built: string; builtTs: number; count: number; secs: number; network: boolean }
export interface TrashItem { id: string; orig: string; name: string; when: string; dir: boolean }
export interface Preview { kind: string; size?: number; ext?: string; text?: string; truncated?: boolean; rows?: string[][]; sheets?: string[]; sheet?: string; more?: boolean; note?: string; error?: string; count?: number; names?: string[] }

export async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  return (await r.json()) as T
}
export const post = <T = any>(url: string, body: unknown) =>
  getJson<T>(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const op = (body: Record<string, unknown>) => post<any>('/api/finder/op', body)

export const sepOf = (p: string) => (p.includes('\\') && !p.includes('/') ? '\\' : '/')
export const joinPath = (dir: string, name: string) => dir + (dir.endsWith('/') || dir.endsWith('\\') ? '' : sepOf(dir)) + name
export const baseName = (p: string) => p.split(/[\\/]/).filter(Boolean).pop() || p
export const dirName = (p: string) => {
  const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'))
  return i <= 0 ? p.slice(0, i + 1) || p : p.slice(0, i)
}
export const fmtSize = (n: number) => (n < 1024 ? n + ' Б' : n < 1048576 ? (n / 1024).toFixed(0) + ' КБ' : n < 1073741824 ? (n / 1048576).toFixed(1) + ' МБ' : (n / 1073741824).toFixed(2) + ' ГБ')

export function crumbs(path: string): { name: string; path: string }[] {
  const s = sepOf(path)
  const out: { name: string; path: string }[] = []
  let acc = ''
  path.split(/[\\/]/).forEach((part, i) => {
    if (i === 0 && part === '') { acc = ''; out.push({ name: '/', path: '/' }); return }
    if (!part) return
    acc = i === 0 ? part + (s === '\\' ? '\\' : '') : joinPath(acc || '/', part)
    if (acc.length === 2 && acc[1] === ':') acc += '\\'
    out.push({ name: part, path: acc })
  })
  return out
}

export const iconOf = (it: { dir: boolean; ext: string }) =>
  it.dir ? '📁' : /^(xlsx|xlsm|xlsb|xls|ods)$/.test(it.ext) ? '📗' : /^(docx|doc|odt|rtf)$/.test(it.ext) ? '📘' : it.ext === 'pdf' ? '📕'
    : /^(png|jpe?g|gif|bmp|webp|svg|tiff?)$/.test(it.ext) ? '🖼️' : /^(zip|rar|7z|tar|gz|tgz)$/.test(it.ext) ? '🗜️' : /^(csv|txt|dat|log|md|inc|data)$/.test(it.ext) ? '📄' : '▫️'

export const copyText = async (t: string) => {
  try { await navigator.clipboard.writeText(t); return true } catch {
    const a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select()
    try { return document.execCommand('copy') } finally { a.remove() }
  }
}

/** Ждать задание, отдавая новые элементы и состояние. Возвращает итоговый снимок. */
export async function watchJob(id: string, onSnap: (s: JobSnap) => void, every = 250): Promise<JobSnap> {
  let since = 0
  for (;;) {
    const s = await getJson<JobSnap>(`/api/finder/job?id=${id}&since=${since}`).catch(() => null)
    if (!s || (s as any).error === 'Задание не найдено.') return { id, kind: '', done: true, error: 'Связь с сервером потеряна', cancelled: false, items: [], next: since, info: {}, elapsed: 0 }
    since = s.next
    onSnap(s)
    if (s.done) return s
    await new Promise(r => setTimeout(r, every))
  }
}
