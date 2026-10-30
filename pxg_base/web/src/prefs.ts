export { pref, usePref, type Pref } from '../../../pxg_core/web-ui/pref'
import { pref } from '../../../pxg_core/web-ui/pref'

export type Theme = 'light' | 'dark' | 'system'
export const theme = pref<Theme>('pxg.theme', 'system', raw => (raw === 'dark' || raw === 'light' ? raw : 'system'))
export const sidebarCollapsed = pref<boolean>('pxg.sidebar.collapsed', false)

const media = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
function apply() {
  const t = theme.get()
  const resolved = t === 'system' ? (media?.matches ? 'dark' : 'light') : t
  document.documentElement.dataset.theme = resolved
  document.documentElement.style.colorScheme = resolved
}
theme.subscribe(apply)
media?.addEventListener?.('change', apply)
apply()

/** Последние значения формы каждого модуля. */
const formKey = (module: string) => 'pxg.form.' + module
export function loadForm(module: string): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(formKey(module)) || '{}') } catch { return {} }
}
export function saveForm(module: string, values: Record<string, string>) {
  try { localStorage.setItem(formKey(module), JSON.stringify(values)) } catch { /* ignore */ }
}
