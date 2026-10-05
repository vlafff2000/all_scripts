import { useSyncExternalStore } from 'react'

/** Настройка, которая помнится между запусками (localStorage, если он доступен). */
export interface Pref<T> { get: () => T; set: (v: T) => void; subscribe: (cb: () => void) => () => void }

export function pref<T>(key: string, initial: T, parse?: (raw: unknown) => T): Pref<T> {
  const listeners = new Set<() => void>()
  let value = initial
  try {
    const raw = key ? localStorage.getItem(key) : null
    if (raw !== null) value = parse ? parse(JSON.parse(raw)) : (JSON.parse(raw) as T)
  } catch { /* хранилище недоступно или значение повреждено */ }
  return {
    get: () => value,
    set: v => {
      value = v
      try { if (key) localStorage.setItem(key, JSON.stringify(v)) } catch { /* ignore */ }
      listeners.forEach(l => l())
    },
    subscribe: cb => { listeners.add(cb); return () => listeners.delete(cb) },
  }
}

export const usePref = <T,>(p: Pref<T>): T => useSyncExternalStore(p.subscribe, p.get)

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
