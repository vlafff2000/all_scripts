/**
 * Выгрузка таблицы (XLSX/CSV) через общий серверный маршрут /api/table/export (pxg_core/table_export.py)
 * и наш проводник «Сохранить как». Используется как `onDownload={tableDownload(table)}` в TableView.
 */
import { saveFileWithPicker } from '../desktopDownload'
import type { Table } from './tableTypes'

export function tableDownload(table: Table, name?: string) {
  return async (format: 'xlsx' | 'csv') => {
    const r = await fetch('/api/table/export', {
      method: 'POST', headers: { 'X-PXG': '1', 'Content-Type': 'application/json' },
      body: JSON.stringify({ table, format, name: name ?? table.title }),
    })
    if (!r.ok) {
      const e = (await r.json().catch(() => ({}))) as { error?: string }
      throw new Error(e.error || `ошибка ${r.status}`)
    }
    const blob = await r.blob()
    const file = (name ?? table.title ?? 'таблица').replace(/[\\/:*?"<>|]+/g, '_') + '.' + format
    await saveFileWithPicker(blob, file)
  }
}
