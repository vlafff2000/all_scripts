// Контракт таблицы (копия из gas_atlas web/src/api.ts). Нужен TableView/TableDock; те же поля отдаёт сервер Атласа.
export interface Column { key: string; label: string; unit: string; decimals: number | null; kind: 'text' | 'number' | 'date'; good?: number | null }
export type Cell = string | number | boolean | null
export interface TableAction {
  kind: 'exclude' | 'assign'; dataset: string | null; id_column: string; label: string; reason: string
  checked_column: string; reason_editable: boolean; ids: string[]; checked: boolean[] | null
  column?: string
  // assign: значения полей по строкам, какие из них правятся, что отправлять, запись журнала
  fields: string[]; editable: string[]; submit: 'changed' | 'all'; journal: string; values: Record<string, Cell[]>
  target: 'groups' | 'object-categories' | 'well-categories' | 'gis-comments' | 'wf-status'   // куда уходят назначения: группы скважин, категории объектов кроссплота или ручные категории скважин фонда
}
export type Assignments = Record<string, Record<string, string>>
export interface Table {
  id: string; title: string; columns: Column[]; rows: Cell[][]; count: number
  note: string; collapsed: boolean; action: TableAction | null
  header?: [string, number][][]   // объединённая шапка над подписями колонок: (подпись, пролёт)
  deferred?: boolean   // большая свёрнутая таблица: строки подгружаются при раскрытии (count — сколько их всего)
  styles?: TableStyle[]   // заливка и цвет шрифта строк или ячеек, как в XLSX
  merges?: TableMerge[]   // объединённые ячейки, как в XLSX (строки first..last, колонки подряд)
}
export interface TableStyle { rows: number[]; fill: string; font: string; columns: string[]; border: string }
export interface TableMerge { first: number; last: number; columns: string[] }
