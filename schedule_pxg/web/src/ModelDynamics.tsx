import { useMemo, useState } from 'react'
import { Dynamics, ModelEntry, compareVolume } from './api'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'

const fmt = (x: number | null | undefined, d = 0) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
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

  const rows = (d: Dynamics, unit: string) => (
    <table className="raw"><thead><tr><th>Модель</th><th>С</th><th>По</th><th>Было, {unit}</th><th>Стало, {unit}</th><th>Изменение</th><th>Изменение, %</th></tr></thead>
      <tbody>{d.models.map(m => { const s = d.series[m]; const p = s.points; const c = s.change
        return <tr key={m}><td>{m}</td><td>{c ? c.from : '—'}</td><td>{c ? c.to : '—'}</td>
          <td className="num">{p.length ? fmt(p[0].value, 1) : '—'}</td><td className="num">{p.length > 1 ? fmt(p[p.length - 1].value, 1) : '—'}</td>
          <td className="num">{c ? fmt(c.delta, 1) : '—'}</td><td className="num">{c ? fmt(c.percent, 1) : '—'}</td></tr> })}</tbody></table>
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
        <h3 style={{ marginTop: 12 }}>Газонасыщенный поровый объём, м³ пор.</h3>
        {rows(res.volume, 'м³ пор.')}
        <DynPlot d={res.volume} unit="м³ пор." title="Газонасыщенный поровый объём" />
        <h3 style={{ marginTop: 12 }}>ГВК, среднее по площади, м</h3>
        {rows(res.gwc, 'м')}
        <DynPlot d={res.gwc} unit="м, TVDSS" title="ГВК, среднее по площади" />
      </>}
    </section>
  )
}
