import { useEffect, useMemo, useState } from 'react'
import { usePanelFilter } from './PanelFilter'
import { getGisLegend, saveGisLegend, type LegendRow } from './api'

const CHIP: Record<string, string> = { 'ок': 'done', 'проверить': 'warn', 'не распознан': 'failed' }
const swatch = (c: string) => (/^[0-9A-F]{6}$/i.test(c) ? '#' + c : c === 'нет' ? 'transparent' : '#ccc')

// Легенда пачек «цвет → пачка» по листам: подсказка с причиной, выбор за инженером; подтверждённое запоминается.
export default function LegendPanel({ file, onClose }: { file: string; onClose: () => void }) {
  const [rows, setRows] = useState<LegendRow[]>([])
  const [packs, setPacks] = useState<string[]>([])
  const [pick, setPick] = useState<Record<string, string>>({})
  const [onlyOpen, setOnlyOpen] = useState(true)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')

  const key = (r: LegendRow) => r.sheet + '|' + r.color
  const load = async () => {
    setBusy(true); setError('')
    try {
      const r = await getGisLegend(file)
      setRows(r.rows); setPacks(r.packs)
      setPick(Object.fromEntries(r.rows.map(x => [key(x), x.pack])))
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  useEffect(() => { load() }, [file])

  const needs = (r: LegendRow) => r.status !== 'ок' && !r.confirmed
  const wf = usePanelFilter('legend', useMemo(() => rows.map(r => r.well), [rows]))
  const shown = rows.filter(r => (!onlyOpen || needs(r) || pick[key(r)] !== r.pack) && wf.keep(r.well))
  const open = rows.filter(needs).length

  const confirm = async (which: LegendRow[]) => {
    setError(''); setSaved('')
    try {
      const r = await saveGisLegend(file, which.map(x => ({ sheet: x.sheet, color: x.color, pack: pick[key(x)] ?? '' })))
      setSaved(`Запомнено строк: ${r.saved}. Запуск и проверка подставят этот выбор.`)
      await load()
    } catch (e) { setError((e as Error).message) }
  }

  return (
    <section className="card result" aria-live="polite">
      <div className="result-head">
        <strong>Легенда пачек</strong>
        <span className="muted">{busy ? 'Читаю книгу…' : open ? `Требуют проверки: ${open} из ${rows.length}` : `Всё подтверждено или по умолчанию (${rows.length})`}</span>
        <span className="spacer" />
        <label className="check"><input type="checkbox" checked={onlyOpen} onChange={e => setOnlyOpen(e.target.checked)} /><span>только требующие проверки</span></label>
        <button type="button" className="quiet" onClick={onClose}>Закрыть</button>
      </div>
      <p className="muted out-dir">Пачка определяется по заливке столбца «от». Это подсказка: выберите пачку сами и подтвердите. Цвет без пачки в таблицы для Атласа не попадёт.</p>
      {wf.node}
      {error && <p className="note warning">{error}</p>}
      {saved && <p className="note info">{saved}</p>}
      {!busy && shown.length === 0 && <p className="note info">Нечего проверять: все цвета распознаны. Снимите фильтр, чтобы увидеть всю легенду.</p>}
      {shown.length > 0 && (
        <table className="files qc">
          <thead><tr><th>Лист</th><th>Цвет</th><th>Пачка</th><th className="number">Строк</th><th>Почему так</th><th /></tr></thead>
          <tbody>{shown.map(r => (
            <tr key={key(r)}>
              <td>скв. {r.well}</td>
              <td><span style={{ display: 'inline-block', width: 14, height: 14, border: '1px solid #888', verticalAlign: 'middle', marginRight: 6, background: swatch(r.color) }} />{r.color}</td>
              <td>
                <select value={pick[key(r)] ?? ''} aria-label={`Пачка для цвета ${r.color}, лист ${r.sheet}`}
                  onChange={e => setPick(o => ({ ...o, [key(r)]: e.target.value }))}>
                  <option value="">— не определена —</option>
                  {packs.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
                <div><span className={'chip small ' + (r.confirmed ? 'done' : CHIP[r.status])}>{r.confirmed ? 'подтверждено' : r.status}</span></div>
              </td>
              <td className="number">{r.rows}</td>
              <td className="muted">{r.reason}{r.labels && <div>Метки ГВК: {r.labels}</div>}{r.hints.length > 0 && <div>В заголовках справа: {r.hints.join(', ')}</div>}</td>
              <td><button type="button" className="quiet" onClick={() => confirm([r])}>Подтвердить</button></td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {shown.length > 1 && <div className="actions"><button type="button" className="primary" onClick={() => confirm(shown)}>Подтвердить все показанные ({shown.length})</button></div>}
    </section>
  )
}
