// Готовые таблицы-результаты приложения в общей области: TableDock + TableView + выгрузка XLSX/CSV.
// Приложение собирает таблицы через tableOf (tableBuild.ts) и передаёт сюда — вид, режимы «Одна/Рядом/Друг под другом»
// и выгрузка везде одинаковые.
import { TableDock } from './TableDock'
import { TableView } from './TableView'
import { tableDownload } from './tableExport'
import type { Table } from './tableTypes'

interface Props {
  tables: Table[]
  scope: string                                   // страница: запоминание выбранных таблиц и раскладки
  mapLink?: (well: string) => string | null
  onRow?: (table: Table, index: number) => void
}

export function Tables({ tables, scope, mapLink, onRow }: Props) {
  return (
    <TableDock tables={tables} scope={scope} render={t => (
      <TableView key={t.id} table={t} docked mapLink={mapLink} onDownload={tableDownload(t)}
        onRow={onRow ? i => onRow(t, i) : undefined} />
    )} />
  )
}
