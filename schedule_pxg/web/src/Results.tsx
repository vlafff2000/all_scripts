import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, TitleComponent, ToolboxComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { AppState, IndicatorRow, ResultsInfo, attachResults, getIndicators, getResultSeries, getResults, getState, pickFile } from './api'

echarts.use([LineChart, DataZoomComponent, GridComponent, TitleComponent, ToolboxComponent, TooltipComponent, CanvasRenderer])

const COLORS = ['#2f6fb0', '#c4622d', '#3f9a6a', '#8a5bb0', '#b09a2f', '#2f9aa8', '#b0426b', '#6b7a8a']
const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))

interface Line { label: string; color: string; pts: [string, number][] }

/** Линии по датам: зум, подсказка, PNG; общая линия наведения у графиков с одним `link`. */
function Plot({ lines, unit, title, link }: { lines: Line[]; unit: string; title: string; link: string }) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  useEffect(() => {
    if (!el.current) return
    const c = echarts.init(el.current)
    c.group = link
    chart.current = c
    echarts.connect(link)
    const ro = new ResizeObserver(() => c.resize())
    ro.observe(el.current)
    return () => { ro.disconnect(); c.dispose(); chart.current = null }
  }, [link])
  const has = lines.some(l => l.pts.length)
  useEffect(() => {
    const c = chart.current
    if (!c || !has) return
    c.setOption({
      animation: false, color: lines.map(l => l.color),
      title: { text: title + ', ' + unit, left: 56, top: 0, textStyle: { fontSize: 12, fontWeight: 'normal', color: '#6b7a8a' } },
      grid: { left: 70, right: 16, top: 28, bottom: 62 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, valueFormatter: (v: number) => fmt(v, 3) },
      toolbox: { right: 8, top: 0, feature: { saveAsImage: { title: 'PNG', name: title, pixelRatio: 2 }, dataZoom: { yAxisIndex: 'none', title: { zoom: 'Область', back: 'Назад' } }, restore: { title: 'Сброс' } } },
      xAxis: { type: 'time', splitLine: { show: false } },
      yAxis: { type: 'value', scale: true },
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }, { type: 'slider', xAxisIndex: 0, height: 18, bottom: 8, filterMode: 'none' }],
      series: lines.map(l => ({ name: l.label, type: 'line', showSymbol: l.pts.length < 40, data: l.pts, lineStyle: { width: 2 } })),
    }, true)
  }, [lines, unit, title, has])
  return <div ref={el} style={{ width: '100%', maxWidth: 900, height: 280, display: has ? 'block' : 'none' }} role="img" aria-label={title} />
}

export default function Results({ st, setSt }: { st: AppState; setSt: (s: AppState) => void }) {
  const [infos, setInfos] = useState<Record<string, ResultsInfo>>({})
  const [sel, setSel] = useState<string[]>([])
  const [sg, setSg] = useState('0.01')
  const [date, setDate] = useState('')
  const [ind, setInd] = useState<Record<string, IndicatorRow[]>>({})
  const [notes, setNotes] = useState<string[]>([])
  const [kw, setKw] = useState('WBHP')
  const [wells, setWells] = useState('')
  const [pr, setPr] = useState<Line[]>([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const names = st.scenarios.filter(s => s.results).map(s => s.name)
  const key = names.join('|')
  useEffect(() => {
    let live = true
    names.forEach(n => getResults(n).then(r => live && setInfos(c => ({ ...c, [n]: r }))).catch(e => live && setMsg(n + ': ' + (e as Error).message)))
    return () => { live = false }
  }, [key])

  const guard = async (f: () => Promise<void>) => { setBusy(true); setMsg(''); try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) } }
  const attach = (n: string, path: string) => guard(async () => { await attachResults(n, path); setSt(await getState()); setInd({}); setPr([]) })
  const choose = (n: string) => guard(async () => { const r = await pickFile(st.scenarios.find(s => s.name === n)?.results || ''); if (r.path) await attach(n, r.path) })
  const toggle = (n: string) => setSel(c => (c.includes(n) ? c.filter(x => x !== n) : [...c, n]))

  const chosen = sel.filter(n => names.includes(n))
  const calc = () => guard(async () => {
    const out: Record<string, IndicatorRow[]> = {}
    const all: string[] = []
    for (const n of chosen) { const r = await getIndicators(n, sg, date ? [date] : []); out[n] = r.rows; r.notes.forEach(x => all.push(n + ': ' + x)) }
    setInd(out); setNotes(all)
  })
  const press = () => guard(async () => {
    const lines: Line[] = []
    for (const n of chosen) {
      const r = await getResultSeries(n, kw, wells.split(/[;,|]/).map(x => x.trim()).filter(Boolean))
      Object.entries(r.series).forEach(([w, s]) => lines.push({ label: n + ' · ' + w, color: COLORS[lines.length % COLORS.length], pts: s.dates.map((d, i) => [d, s.values[i]] as [string, number]) }))
    }
    setPr(lines)
  })

  const shown = chosen.filter(n => ind[n])
  const line = (f: (r: IndicatorRow) => number | null): Line[] => shown.map((n, i) => ({ label: n, color: COLORS[i % COLORS.length], pts: ind[n].filter(r => f(r) !== null).map(r => [r.date, f(r) as number] as [string, number]) }))
  const last = (n: string) => ind[n][ind[n].length - 1]
  const vecs = Array.from(new Set(chosen.flatMap(n => (infos[n]?.vectors || []).map(v => v.keyword))))

  return (
    <main className="work">
      <section className="card">
        <h2>Результаты расчёта по сценариям</h2>
        {st.scenarios.length === 0 ? <p className="muted">Сначала создайте сценарий (вкладка «Сценарии»).</p> : <>
          <p className="muted small">Укажите любой файл расчёта модели (например, .SMSPEC или .EGRID): остальные файлы с тем же именем найдутся рядом. Для показателей нужны EGRID, INIT и UNRST с SGAS, для давлений — SMSPEC и UNSMRY.</p>
          <div style={{ overflowX: 'auto' }}><table className="raw"><thead><tr><th></th><th>Сценарий</th><th>Модель</th><th>Период расчёта</th><th>Файлы</th><th></th></tr></thead>
            <tbody>{st.scenarios.map(s => { const r = infos[s.name]; return <tr key={s.name}>
              <td>{s.results && <input type="checkbox" checked={sel.includes(s.name)} onChange={() => toggle(s.name)} aria-label={'Выбрать ' + s.name} />}</td>
              <td>{s.name}</td>
              <td className="small" title={s.results}>{s.results ? '…/' + s.results.split(/[\\/]/).filter(Boolean).slice(-2).join('/') : <span className="muted">не привязана</span>}</td>
              <td>{r && r.start ? r.start + ' — ' + r.end + ' (' + r.steps + ' шагов)' : '—'}</td>
              <td className="small">{r ? Object.keys(r.files).join(', ') + (r.missing.length ? ' · нет: ' + r.missing.join(', ') : '') : ''}</td>
              <td className="row"><button disabled={busy} onClick={() => choose(s.name)}>{s.results ? 'Сменить' : 'Привязать'}</button>
                {s.results && <button disabled={busy} onClick={() => attach(s.name, '')}>Отвязать</button>}</td></tr> })}</tbody></table></div>
        </>}
        {msg && <p className="note warn">{msg}</p>}
      </section>
      {chosen.length > 0 && <section className="card">
        <h3>Показатели «сценарий × показатель»</h3>
        <div className="row">
          <span className="muted small">Порог Sg:</span><input style={{ width: 70 }} value={sg} onChange={e => setSg(e.target.value)} />
          <span className="muted small">Дата (пусто — все шаги):</span><input type="date" value={date} onChange={e => setDate(e.target.value)} />
          <button className="primary" disabled={busy} onClick={calc}>Посчитать</button>
        </div>
        {notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {shown.length > 0 && <>
          <table className="raw"><thead><tr><th>Сценарий</th><th>Дата</th><th>Газонас. объём, м³ пор.</th><th>ГВК мин, м</th><th>ГВК среднее, м</th><th>ГВК по площади, м</th><th>ГВК макс, м</th></tr></thead>
            <tbody>{shown.map(n => { const r = last(n); return r ? <tr key={n}><td>{n}</td><td>{r.date}</td><td className="num">{fmt(r.gas_pore_volume, 0)}</td>
              <td className="num">{fmt(r.gwc_min, 1)}</td><td className="num">{fmt(r.gwc_mean, 1)}</td><td className="num">{fmt(r.gwc_mean_area, 1)}</td><td className="num">{fmt(r.gwc_max, 1)}</td></tr> : <tr key={n}><td>{n}</td><td colSpan={6} className="muted">нет данных</td></tr> })}</tbody></table>
          <p className="muted small">В таблице последний из посчитанных шагов; с выбранной датой — ближайший к ней шаг рестарта.</p>
          <Plot lines={line(r => r.gas_pore_volume)} unit="м³ пор." title="Газонасыщенный поровый объём" link="sched-results" />
          <Plot lines={line(r => r.gwc_mean_area)} unit="м" title="ГВК, среднее по площади" link="sched-results" />
        </>}
        <h3 style={{ marginTop: 16 }}>Давления и другие вектора сводки</h3>
        <div className="row">
          <select value={kw} onChange={e => setKw(e.target.value)}>{(vecs.length ? vecs : ['WBHP', 'WBP', 'FPR']).map(k => <option key={k}>{k}</option>)}</select>
          <input style={{ width: 260 }} placeholder="скважины через запятую (пусто — все)" value={wells} onChange={e => setWells(e.target.value)} />
          <button disabled={busy} onClick={press}>Построить</button>
        </div>
        <Plot lines={pr} unit={kw} title={kw} link="sched-results-p" />
      </section>}
    </main>
  )
}
