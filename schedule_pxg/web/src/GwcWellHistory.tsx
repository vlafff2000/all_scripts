import { useMemo, useState } from 'react'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import { tableOf } from '../../../pxg_core/web-ui/table/tableBuild'
import { tableDownload } from '../../../pxg_core/web-ui/table/tableExport'
import type { CompareRow, CompareSeries } from './api'

const ordered = (values: string[]) => [...new Set(values)].sort((a, b) => a.localeCompare(b, 'ru', { numeric: true }))

export default function GwcWellHistory({ rows, series, excluded }: { rows: CompareRow[]; series: CompareSeries[]; excluded: Set<string> }) {
  const [well, setWell] = useState('')
  const [pack, setPack] = useState('')
  const [error, setError] = useState('')
  const wells = useMemo(() => ordered(rows.map(row => row.well)), [rows])
  const selectedWell = wells.includes(well) ? well : wells[0]
  const wellRows = useMemo(() => rows.filter(row => row.well === selectedWell).sort((a, b) => a.date.localeCompare(b.date)), [rows, selectedWell])
  const packs = ordered(wellRows.map(row => row.pack))
  const selectedPack = packs.includes(pack) ? pack : packs[0]
  const part = wellRows.filter(row => row.pack === selectedPack)
  const charts = useMemo(() => {
    const history = wellRows.filter(row => row.pack === selectedPack)
    if (!history.length) return null
    const facts = new Map(history.map(row => [row.date, row.fact]))
    const shown = (row: CompareRow) => row.status === 'ok' && !row.excluded && !excluded.has(row.key)
    const bySeries = series.map(s => ({
      name: s.name,
      key: s.key,
      rows: history.filter(row => row.key.startsWith(s.key + '|')),
    }))
    const points = (name: string, slot: number, modelRows: CompareRow[], kind: 'model' | 'delta') => ({
      ...mkSeries({ name, slot, x: modelRows.map(r => r.date), y: modelRows.map(r => shown(r) ? r[kind] : null) }),
      markers: true,
      labels: modelRows.map(r => r.step_date ? 'Шаг модели ' + r.step_date : 'Дата среза ' + r.slice),
    })
    const title = 'скв. ' + selectedWell + ', пачка ' + selectedPack
    const axis = mkAxis('Дата замера ГИС', '', 'time')
    const model = bySeries.map(s => points(s.name, s.key + 1, s.rows, 'model')).filter(s => s.y.some(y => y !== null))
    const delta = bySeries.map(s => points(s.name, s.key + 1, s.rows, 'delta')).filter(s => s.y.some(y => y !== null))
    return {
      history: mkChart('gwc-well-history', 'ГВК по датам · ' + title, axis, mkAxis('ГВК', 'м, а.о.'), [
        { ...mkSeries({ name: 'Факт ГИС', x: [...facts.keys()], y: [...facts.values()] }), markers: true }, ...model,
      ]),
      delta: delta.length ? mkChart('gwc-well-delta', 'Δ ГВК (модель − факт) · ' + title, axis, mkAxis('Δ ГВК', 'м', 'value', { from_zero: true }), delta) : null,
    }
  }, [wellRows, selectedWell, selectedPack, series, excluded])

  const download = async (format: 'xlsx' | 'csv') => {
    setError('')
    const table = tableOf('gwc-history', 'ГВК · скв. ' + selectedWell,
      ['Скважина', 'Пачка', 'Группа', ['Дата замера ГИС', 'date'], 'Сезон', 'Модель · критерий',
        ['Запрошенный срез', 'date'], ['Шаг рестарта', 'date'], 'Подбор среза', ['Факт, м а.о.', 'number', 2],
        ['Модель, м а.о.', 'number', 2], ['Δ, м', 'number', 2], 'Статус', 'В статистике'],
      wellRows.map(r => [r.well, r.pack, r.group, r.date, r.season, r.series ?? '', r.slice, r.step_date ?? null,
        r.slice_why, r.fact, r.model, r.delta, r.status, r.delta !== null && !r.excluded && !excluded.has(r.key) ? 'да' : 'нет']))
    try {
      await tableDownload(table)(format)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (!charts) return null
  return <>
    <h3>История ГВК по скважине</h3>
    <div className="row" style={{ flexWrap: 'wrap' }}>
      <label>Скважина <select value={selectedWell} onChange={e => setWell(e.target.value)}>
        {wells.map(w => <option key={w}>{w}</option>)}
      </select></label>
      <label>Пачка <select value={selectedPack} onChange={e => setPack(e.target.value)}>
        {packs.map(p => <option key={p}>{p}</option>)}
      </select></label>
      <button type="button" onClick={() => void download('xlsx')}>Все пачки скважины · XLSX</button>
      <button type="button" onClick={() => void download('csv')}>Все пачки скважины · CSV</button>
    </div>
    {error && <p className="note warn" role="alert">{error}</p>}
    <p className="muted small">Замеры с {part[0].date} по {part[part.length - 1].date}. На оси X — даты ГИС. Дата шага модели указана в подсказке.</p>
    <ChartView chart={charts.history} excludeMode={false} onExclude={() => {}} />
    {charts.delta ? <ChartView chart={charts.delta} excludeMode={false} onExclude={() => {}} />
      : <p className="muted small">По выбранной пачке нет пар для расчёта Δ ГВК.</p>}
  </>
}
