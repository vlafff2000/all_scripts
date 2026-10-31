// Сборка общей таблицы из строк приложения: ГДМ, Карты и др. передают список столбцов и строки (строка = массив значений),
// а TableView/TableDock получают таблицу в контракте Атласа (значения по столбцам).
import type { Cell, Column, Table, TableStyle } from './tableTypes'

export type ColumnSpec = string | [label: string, kind?: Column['kind'], decimals?: number | null]

export function col(spec: ColumnSpec, i: number): Column {
  const [label, kind = 'text', decimals = null] = typeof spec === 'string' ? [spec] : spec
  const m = /^(.*?),\s*([^,]+)$/.exec(label)
  return { key: 'c' + i, label: m ? m[1] : label, unit: m ? m[2] : '', decimals, kind }
}

/** styles — заливка/цвет шрифта ячеек (как в XLSX): rows — индексы строк, columns — ключи 'c'+номер столбца, цвета без «#». */
/** Столбец «Скважина»: key='well' — номер становится ссылкой на карту, если приложение передало mapLink. */
export function tableOf(id: string, title: string, columns: ColumnSpec[], rows: Cell[][], note = '', styles?: TableStyle[]): Table {
  const cols = columns.map(col)
  return {
    id, title, columns: cols, count: rows.length, note, collapsed: false, action: null, styles,
    rows: cols.map((_, k) => rows.map(r => (r[k] === undefined ? null : r[k]))),
  }
}
