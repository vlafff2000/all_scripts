import { useSyncExternalStore } from 'react'

/** Настройка, которая помнится между запусками (localStorage, если он доступен). */
export interface Pref<T> { get: () => T; set: (v: T) => void; subscribe: (cb: () => void) => () => void }

/** Настройки, которые у каждого окна свои (размеры, свёрнутость): между окнами не синхронизируются. */
const PER_WINDOW = /\.(sidebar\.collapsed|layersBox|inspector)$/

export function pref<T>(key: string, initial: T, parse?: (raw: unknown) => T): Pref<T> {
  const listeners = new Set<() => void>()
  let value = initial
  try {
    const raw = key ? localStorage.getItem(key) : null
    if (raw !== null) value = parse ? parse(JSON.parse(raw)) : (JSON.parse(raw) as T)
  } catch { /* хранилище недоступно или значение повреждено */ }
  // второе окно программы меняет ту же настройку: подхватываем из события хранилища
  if (key && !PER_WINDOW.test(key)) {
    try {
      window.addEventListener('storage', e => {
        if (e.key !== key || e.storageArea !== localStorage || e.newValue === null) return
        try {
          const next = parse ? parse(JSON.parse(e.newValue)) : (JSON.parse(e.newValue) as T)
          if (JSON.stringify(next) === JSON.stringify(value)) return
          value = next
          listeners.forEach(l => l())
        } catch { /* повреждённое значение */ }
      })
    } catch { /* нет window */ }
  }
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

