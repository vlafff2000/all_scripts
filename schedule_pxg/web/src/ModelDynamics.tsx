import { useMemo, useState } from 'react'
import { Dynamics, ModelEntry, compareVolume } from './api'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import { Tables } from '../../../pxg_core/web-ui/table/Tables'
import { tableOf } from '../../../pxg_core/web-ui/table/tableBuild'

const tail = (path: string) => path.split(/[\\/]/).filter(Boolean).slice(-2).join('/')

/** Линии по датам у каждой модели на общем графике (как в Газовом Атласе: зум, подсказка, закрепление точек). */
function DynPlot({ d, unit, title }: { d: Dynamics; unit: string; title: string }) {
  const chart = useMemo(() => mkChart('sched-dyn-' + d.key, title, mkAxis('Дата', '', 'time'), mkAxis(title, unit),
    d.models.map((m, i) => mkSeries({ name: m, slot: i, x: d.series[m].points.map(p => p.date), y: d.series[m].points.map(p => p.value) }))), [d, title, unit])
  if (!d.models.some(m => d.series[m].points.length)) return null
  return <ChartView chart={chart} excludeMode={false} onExclude={() => {}} />
}

/** Динамика газонасыщенного порового объёма и ГВК по моделям: изменение за период и график (второй этап плана «Сравнение моделей»). */
export default function ModelDynamics({ models }: { models: ModelEntry[] }) {
  const [sg, setSg] = useState('0.01')
  const [dates, setDates] = useState('')
  const [base, setBase] = useState('')
  const [res, setRes] = useState<{ volume: Dynamics; gwc: Dynamics; notes: string[] } | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const names = models.map(m => m.name + ' (' + tail(m.folder) + ')')

  const run = async () => {
    setBusy(true); setMsg('')
    try {
      setRes(await compareVolume({
        models: models.map((m, i) => ({ name: names[i], path: m.id })),
        sg, dates: dates.split(/[;,|\s]+/).map(x => x.trim()).filter(Boolean),
        base: names.includes(base) ? base : undefined,
      }))
    } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }

  const rows = (d: Dynamics, unit: string, title: string) => (
    <Tables scope={'sched-dyn-' + title} tables={[tableOf('dyn', title,
      ['Модель', ['С', 'date'], ['По', 'date'], ['Было, ' + unit, 'number', 1], ['Стало, ' + unit, 'number', 1], ['Изменение', 'number', 1], ['Изменение, %', 'number', 1]],
      d.models.map(m => { const s = d.series[m]; const p = s.points; const c = s.change
        return [m, c ? c.from : null, c ? c.to : null, p.length ? p[0].value : null, p.length > 1 ? p[p.length - 1].value : null, c ? c.delta : null, c ? c.percent : null] }))]} />
  )

  return (
    <section className="card">
      <h3>Сравнение моделей: динамика газонасыщенного объёма и ГВК</h3>
      <p className="muted small">Показатели считаются по шагам рестарта тем же способом, что в «Показателях» выше. Изменение — от первой до последней даты у каждой модели.
        Разница с базовой моделью — по общим датам. Порог Sg и даты задаются здесь же; пусто — все шаги.</p>
      <div className="row">
        <span className="muted small">Порог Sg:</span><input style={{ width: 70 }} value={sg} onChange={e => setSg(e.target.value)} />
        <span className="muted small">Даты (ГГГГ-ММ-ДД, через запятую; пусто — все):</span><input style={{ width: 260 }} value={dates} onChange={e => setDates(e.target.value)} />
        <span className="muted small">База:</span>
        <select value={base} onChange={e => setBase(e.target.value)}>
          <option value="">первая модель</option>{names.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        <button className="primary" disabled={busy || !models.length} onClick={run}>Посчитать динамику</button>
      </div>
      {!models.length && <p className="muted small">Отметьте модели с результатами в таблице выше.</p>}
      {msg && <p className="note warn">{msg}</p>}
      {res && <>
        {res.notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {rows(res.volume, 'м³ пор.', 'Газонасыщенный поровый объём')}
        <DynPlot d={res.volume} unit="м³ пор." title="Газонасыщенный поровый объём" />
        {rows(res.gwc, 'м', 'ГВК, среднее по площади')}
        <DynPlot d={res.gwc} unit="м, TVDSS" title="ГВК, среднее по площади" />
      </>}
    </section>
  )
}
