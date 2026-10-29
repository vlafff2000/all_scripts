import { useSyncExternalStore } from 'react'
import { emptyAlign, parseAlign } from './polygons'
import { pref } from './prefs'

/** Фото или растр под скважинами: показывать ли, прозрачность и три точки привязки (пиксели картинки ↔ скважины). */
export const bgShow = pref<boolean>('gsp.bgShow', true)
export const bgOpacity = pref<number>('gsp.bgOpacity', 0.7, raw => { const v = Number(raw); return v >= 0 && v <= 1 ? v : 0.7 })
export const bgAlign = pref('gsp.bgAlign', emptyAlign(), parseAlign)

/** Адрес картинки меняется при смене файла, чтобы браузер не взял старую из кэша. */
let version = 0
const subs = new Set<() => void>()
const bgStore = { get: () => version, subscribe: (cb: () => void) => { subs.add(cb); return () => { subs.delete(cb) } } }
export const useBgUrl = () => '/api/background?v=' + useSyncExternalStore(bgStore.subscribe, bgStore.get)

export function refreshBackground() {
  version = Date.now()
  subs.forEach(f => f())
}
