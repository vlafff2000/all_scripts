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
export const theme = pref<Theme>('gsp.theme', 'system', raw => (raw === 'dark' || raw === 'light' ? raw : 'system'))
export const paintMode = pref<'flow' | 'entry' | 'depth' | 'wf' | 'atlas' | 'model' | 'gis'>('gsp.paint', 'flow', raw => (raw === 'wfall' ? 'wf' : ['entry', 'depth', 'wf', 'atlas', 'model', 'gis'].includes(String(raw)) ? (raw as 'entry') : 'flow'))
/** Выбранный параметр Атласа («таблица|колонка») и агрегация; запоминаются между сеансами. */
export const atlasParam = pref<string>('gsp.atlasParam', '', raw => String(raw || ''))
export const atlasAgg = pref<string>('gsp.atlasAgg', 'mean', raw => String(raw || 'mean'))
/** ГИС и ГВК на карте: пачка, показатель, сезон, сезон для сравнения («Δ») и закреплённые инженером замеры («скважина:дата,…»). */
export const gisPack = pref<string>('gsp.gisPack', '', raw => String(raw || ''))
export const gisMetric = pref<string>('gsp.gisMetric', 'gvk_abs_m', raw => String(raw || 'gvk_abs_m'))
export const gisSeason = pref<string>('gsp.gisSeason', '', raw => String(raw || ''))
export const gisAgainst = pref<string>('gsp.gisAgainst', '', raw => String(raw || ''))
export const gisPins = pref<string>('gsp.gisPins', '', raw => String(raw || ''))
/** Изолинии ГИС: включены ли, шаг по значению («» — подобрать), радиус доверия в средних расстояниях между скважинами. */
/** Что показывать в режиме «ГИС и ГВК»: факт ГИС, ГВК модели из ГДМ или отклонение «модель − факт». */
export const gisSource = pref<'fact' | 'model' | 'delta'>('gsp.gisSource', 'fact', raw => (raw === 'model' || raw === 'delta' ? raw : 'fact'))
/** Кровля пласта из модели под изолиниями ГВК: включена ли, файл модели, номер слоя ячеек (0 — верхний активный), шаг изолиний. */
export const gisRoof = pref<boolean>('gsp.gisRoof', false)
export const gisRoofModel = pref<string>('gsp.gisRoofModel', '', raw => String(raw || ''))
export const gisRoofLayer = pref<string>('gsp.gisRoofLayer', '1', raw => String(raw ?? '1'))
export const gisRoofStep = pref<string>('gsp.gisRoofStep', '', raw => String(raw || ''))
/** Показывать ли наблюдательные скважины (вне групп) в режиме «ГИС и ГВК». */
export const gisObservers = pref<boolean>('gsp.gisObservers', true)
/** Контур ГВК по кровле: включён ли и поверхность ГВК (плоскость по скважинам или по скважинам как есть). */
export const gisGwc = pref<boolean>('gsp.gisGwc', false)
export const gisGwcMode = pref<'plane' | 'idw'>('gsp.gisGwcMode', 'plane', raw => (raw === 'idw' ? 'idw' : 'plane'))
export const gisIso = pref<boolean>('gsp.gisIso', false)
export const gisIsoStep = pref<string>('gsp.gisIsoStep', '', raw => String(raw || ''))
export const gisIsoReach = pref<string>('gsp.gisIsoReach', '1.5', raw => String(raw || '1.5'))
export const modelKeyword = pref<string>('gsp.modelKeyword', 'WBHP', raw => String(raw || 'WBHP'))
export const modelAgg = pref<string>('gsp.modelAgg', 'mean', raw => String(raw || 'mean'))
export const sidebarCollapsed = pref<boolean>('gsp.sidebar.collapsed', false)

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

export type PosMode = 'auto' | 'grid' | 'xy'
export const posMode = pref<PosMode>('gsp.pos', 'auto', raw => (raw === 'grid' || raw === 'xy' ? raw : 'auto'))
export const lastGsp = pref<string>('gsp.gsp', '')
export const lastKind = pref<string>('gsp.kind', 'Отбор')
export const sectors = pref<'months' | 'plain'>('gsp.sectors', 'months', raw => (raw === 'plain' ? 'plain' : 'months'))
export const showWater = pref<boolean>('gsp.water', true)
export const legendOpen = pref<boolean>('gsp.legend', false)
export const showShare = pref<boolean>('gsp.share', true)
export const fixedScale = pref<boolean>('gsp.fixed', true)
export const inspectorOpen = pref<boolean>('gsp.inspector', true)
export const bubbleScale = pref<number>('gsp.bubble.scale', 1, raw => { const v = Number(raw); return v >= 0.4 && v <= 2.5 ? v : 1 })
export const labelMode = pref<'num' | 'val' | 'none'>('gsp.labels', 'num', raw => (raw === 'val' || raw === 'none' ? raw : 'num'))
export const syncMaps = pref<boolean>('gsp.cmp.sync', true)
export const hideIdle = pref<boolean>('gsp.hideidle', false)
export const minValue = pref<number>('gsp.minvalue', 0, raw => { const v = Number(raw); return v >= 0 && v < 1e6 ? v : 0 })

/** За какие сезоны красить ввод и обводнённость: один (выбранный сверху), несколько отмеченных или все (среднее). */
export type SeasonScope = 'one' | 'pick' | 'all'
export const seasonScope = pref<SeasonScope>('gsp.scope', 'one', raw => (raw === 'pick' || raw === 'all' ? raw : 'one'))
export const pickedSeasons = pref<string[]>('gsp.picked', [], raw => (Array.isArray(raw) ? raw.map(String) : []))
export const tipMode = pref<'float' | 'dock'>('gsp.tipmode', 'dock', raw => (raw === 'float' ? 'float' : 'dock'))
export const SIDE_MIN = 260, SIDE_MAX = 760
export const sideWidth = pref<number>('gsp.sidew', 340, raw => { const v = Number(raw); return v >= SIDE_MIN && v <= SIDE_MAX ? v : 340 })
const applySide = () => { document.documentElement.style.setProperty('--side-w', sideWidth.get() + 'px') }
sideWidth.subscribe(applySide)
applySide()
export const spreadWells = pref<boolean>('gsp.spread', false)
/** Близкие скважины склеиваются в один круг со счётчиком; при приближении карты распадаются. */
export const clusterWells = pref<boolean>('gsp.cluster', true)
/** Красить круги цветом группы, когда на карте несколько ГСП. */
export const groupColoring = pref<boolean>('gsp.groupcolor', true)
