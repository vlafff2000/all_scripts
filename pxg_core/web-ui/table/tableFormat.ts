import type { Cell, Column } from './tableTypes'
import { formatDate, formatNumber } from '../chart/format'

// Как в gas_atlas web/src/format.ts: пустое — пусто, число с заданными знаками, дата ДД.ММ.ГГГГ.
export function formatCell(value: Cell, column: Column) {
  if (value === null || value === '') return ''
  if (column.kind === 'number' && typeof value === 'number') return formatNumber(value, column.decimals)
  if (column.kind === 'date' && typeof value === 'string') return formatDate(value)
  return String(value)
}
