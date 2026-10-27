import type { Item, Meta } from './api'

export interface SearchSpec {
  query: string; root: string; regex: boolean; case: boolean; types: string[]; sizeMin: string; sizeMax: string
  dateFrom: string; dateTo: string; want: 'all' | 'files' | 'folders'; hidden: boolean; useIndex: boolean
}
export const emptySearch = (root: string): SearchSpec => ({ query: '', root, regex: false, case: false, types: [], sizeMin: '', sizeMax: '', dateFrom: '', dateTo: '', want: 'all', hidden: false, useIndex: true })

export interface Tab {
  id: string; path: string; back: string[]; fwd: string[]; sort: 'name' | 'mtime' | 'size'; desc: boolean
  search?: SearchSpec; runId?: number
}
export interface PaneState { tabs: Tab[]; active: number }
export interface AppState { panes: PaneState[]; dual: boolean; activePane: number; preview: boolean; hidden: boolean; sideW: number; previewW: number; theme: 'system' | 'light' | 'dark'; recent: string[] }

export type Row = Item & { path: string; where?: string }

export interface PaneApi {
  selection: () => Row[]
  focusedFolder: () => string
  refresh: () => void
  selectAll: () => void
  focus: () => void
}

export type MetaMap = Record<string, Meta>
export const uid = () => Math.random().toString(36).slice(2, 9)
export const newTab = (path: string): Tab => ({ id: uid(), path, back: [], fwd: [], sort: 'name', desc: false })
export const COLOR_HEX: Record<string, string> = { red: '#e5484d', orange: '#f76808', yellow: '#e5b800', green: '#30a46c', teal: '#12a594', blue: '#3e63dd', purple: '#8e4ec6', gray: '#8b8d98' }
export const COLOR_NAME: Record<string, string> = { red: 'Красный', orange: 'Оранжевый', yellow: 'Жёлтый', green: 'Зелёный', teal: 'Бирюзовый', blue: 'Синий', purple: 'Фиолетовый', gray: 'Серый' }
