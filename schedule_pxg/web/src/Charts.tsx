import { useMemo, useState } from 'react'
import PageHead from './PageHead'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { dayNum, isoOfDay, mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import type { Chart } from '../../../pxg_core/web-ui/chart/chartTypes'
import { AppState, ChartSeries, ChartsView, getCharts } from './api'

const BY: [string, string][] = [['total', 'по объекту'], ['group', 'по группам'], ['well', 'по скважинам'], ['season', 'по сезонам (наложение)']]
const fmt = (x: number, d = 2) => x.toLocaleString('ru-RU', { maximumFractionDigits: d })

/** Ступенчатая линия: расход постоянен на шаге (точки в первые и последние сутки шага); накопленный — ломаная по концам шагов. */
function toPoints(s: ChartSeries, cum: boolean, seasonAxis: boolean): [number, number][] {
  const out: [number, number][] = []
  let end: number | null = null   // конец предыдущего шага
  s.steps.forEach(st => {
    const a = seasonAxis ? st[5] ?? 0 : dayNum(st[0])
    const b = a + (dayNum(st[1]) - dayNum(st[0])) + 1
    if (end !== null && !cum && a > end) out.push([end, 0], [a - 1, 0])   // между сезонами расход нулевой, а не плавный спуск
    if (cum) {
      if (!out.length) out.push([a, 0])
      else if (end !== null && a > end) out.push([a, out[out.length - 1][1]])   // пауза без закачки/отбора: накопленный объём стоит ровно
      out.push([b, st[4] / 1e6])
    } else { out.push([a, st[2] / 1e3]); if (b - 1 > a) out.push([b - 1, st[2] / 1e3]) }
    end = b
  })
  return out
}

/** Данные сценариев → график в формате Атласа (общий ChartView): один сценарий — ряды по группам/скважинам, несколько — ряды по сценариям. */
function build(data: ChartsView, by: string, cum: boolean, shown: string, multi: boolean): Chart {
  const season = by === 'season'
  const labels = Array.from(new Set(data.scenarios.flatMap(sc => sc.series.map(s => s.label))))
  const kinds = new Set(data.scenarios.flatMap(sc => sc.series.map(s => s.kind)))
  const series = data.scenarios.flatMap((sc, si) => sc.series.filter(s => !multi || s.label === shown).map(s => {
    const pts = toPoints(s, cum, season)
    return mkSeries({
      name: multi ? sc.name + (kinds.size > 1 ? ' · ' + s.kind : '') : s.label + (kinds.size > 1 ? ' · ' + s.kind : ''),
      slot: multi ? si : labels.indexOf(s.label), dashed: s.kind === 'отбор' && !season,
      x: pts.map(p => (season ? p[0] : isoOfDay(p[0]))), y: pts.map(p => p[1]),
    })
  }))
  const title = cum ? 'Накопленный объём' : 'Расход'
  return mkChart(cum ? 'sched-cum' : 'sched-rate', title + (multi ? ' · ' + shown : ''),
    season ? mkAxis('Сутки сезона', 'сут') : mkAxis('Дата', '', 'time'), mkAxis(cum ? 'Накопленный объём' : 'Расход', cum ? 'млн м³' : 'тыс. м³/сут', 'value', { from_zero: true }), series)
}

export default function Charts({ st }: { st: AppState }) {
  const [names, setNames] = useState<string[]>(st.scenarios.length ? [st.scenarios[0].name] : [])
  const [by, setBy] = useState('total')
  const [target, setTarget] = useState('')
  const [data, setData] = useState<ChartsView | null>(null)
  const [pick, setPick] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const toggle = (n: string) => { setData(null); setNames(c => (c.includes(n) ? c.filter(x => x !== n) : [...c, n])) }
  const go = async () => {
    setBusy(true); setMsg('')
    try { const d = await getCharts(names, by, target); setData(d); setPick('') } catch (e) { setMsg((e as Error).message); setData(null) } finally { setBusy(false) }
  }

  const multi = !!data && data.scenarios.length > 1
  const keys = data ? Array.from(new Set(data.scenarios.flatMap(s => s.series.map(x => x.label)))) : []
  const shown = multi ? (pick && keys.includes(pick) ? pick : keys[0]) : ''
  const chartR = useMemo(() => (data ? build(data, by, false, shown, multi) : null), [data, by, shown, multi])
  const chartC = useMemo(() => (data ? build(data, by, true, shown, multi) : null), [data, by, shown, multi])
  const totals = data ? data.totals.filter(t => !multi || t.label === shown) : []

  return (
    <main className="workspace">
      <PageHead title="Графики" lede="Расходы и накопленные объёмы по сценариям: проверьте, что сезоны стыкуются и объёмы похожи на ожидаемые." />
      <section className="card">
        <h2>Графики расходов и накопленных объёмов</h2>
        {st.scenarios.length === 0 ? <p className="muted">Сначала создайте сценарий с календарём сезонов (вкладка «Сценарии»).</p> : <>
          <div className="row">
            <span className="muted small">Сценарии (несколько — сравнение):</span>
            {st.scenarios.map(s => <label key={s.name}><input type="checkbox" checked={names.includes(s.name)} onChange={() => toggle(s.name)} /> {s.name}</label>)}
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <select value={by} onChange={e => { setBy(e.target.value); setData(null) }}>{BY.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
            <select value={target} onChange={e => { setTarget(e.target.value); setData(null) }}>
              <option value="">весь объект</option>
              {data && <><optgroup label="Группы">{data.targets.groups.map(g => <option key={g} value={g}>{g}</option>)}</optgroup>
                <optgroup label="Скважины">{data.targets.wells.map(w => <option key={w} value={w}>{w}</option>)}</optgroup></>}
              {data && target && !data.targets.groups.includes(target) && !data.targets.wells.includes(target) && <option>{target}</option>}
            </select>
            <button className="primary" disabled={busy || names.length === 0} onClick={go}>Построить</button>
          </div>
          {!data && <p className="muted small">Выбор группы или скважины доступен после первого построения. Закачка — сплошная линия, отбор — пунктир. Колесо мыши и ползунок — масштаб, наведение синхронно на обоих графиках, щелчок закрепляет подсказку.</p>}
        </>}
        {msg && <p className="note warn">{msg}</p>}
      </section>
      {data && <section className="card">
        {multi && <div className="row"><span className="muted small">Показатель для сравнения:</span>
          <select value={shown} onChange={e => setPick(e.target.value)}>{keys.map(k => <option key={k}>{k}</option>)}</select></div>}
        {chartR && chartC && (chartR.series.length ? <div className="chart-stack"><ChartView chart={chartR} excludeMode={false} onExclude={() => {}} /><ChartView chart={chartC} excludeMode={false} onExclude={() => {}} /></div>
          : <p className="note warn">Нет рядов для графика: в проекте нет скважин этой группы или не построен календарь. Проверьте «Импорт» и «Сценарии».</p>)}
        {data.scenarios.flatMap(s => s.notes.map(n => s.name + ': ' + n)).map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {totals.length > 0 && <table className="raw"><thead><tr><th>Сценарий</th><th>Ряд</th><th>Вид</th><th>Объём, млн м³</th></tr></thead>
          <tbody>{totals.map((t, i) => <tr key={i}><td>{t.scenario}</td><td>{t.label}</td><td>{t.kind}</td><td className="num">{fmt(t.total / 1e6, 3)}</td></tr>)}</tbody></table>}
      </section>}
    </main>
  )
}
