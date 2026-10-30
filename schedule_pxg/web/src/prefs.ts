export { pref, usePref, type Pref } from '../../../pxg_core/web-ui/pref'
import { pref } from '../../../pxg_core/web-ui/pref'

export type Theme = 'light' | 'dark' | 'system'
export const theme = pref<Theme>('sched.theme', 'system', raw => (raw === 'dark' || raw === 'light' ? raw : 'system'))
export const sidebarCollapsed = pref<boolean>('sched.sidebar.collapsed', false)
/** Запуск результатов адаптации, открытый на шаге 6: та же папка открывается на вкладке «Экспорт графиков». */
export const lastAdaptRun = pref<string>('sched.adapt.run', '')

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
