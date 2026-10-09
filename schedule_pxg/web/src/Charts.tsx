import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, TitleComponent, ToolboxComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { AppState, ChartSeries, ChartsView, getCharts } from './api'

echarts.use([LineChart, DataZoomComponent, GridComponent, TitleComponent, ToolboxComponent, TooltipComponent, CanvasRenderer])

const COLORS = ['#2f6fb0', '#c4622d', '#3f9a6a', '#8a5bb0', '#b09a2f', '#2f9aa8', '#b0426b', '#6b7a8a']
const BY: [string, string][] = [['total', 'по объекту'], ['group', 'по группам'], ['well', 'по скважинам'], ['season', 'по сезонам (наложение)']]
const fmt = (x: number, d = 2) => x.toLocaleString('ru-RU', { maximumFractionDigits: d })
const day = (iso: string) => new Date(iso + 'T00:00:00Z').getTime() / 864e5

interface Line { label: string; color: string; dash?: string; pts: [number, number][] }

/** Ступенчатая линия: расход постоянен на шаге; накопленный — ломаная по концам шагов. */
function toLine(s: ChartSeries, cum: boolean, seasonAxis: boolean): [number, number][] {
  const out: [number, number][] = []
  s.steps.forEach(st => {
    const a = seasonAxis ? st[5] ?? 0 : day(st[0])
    const b = a + (day(st[1]) - day(st[0])) + 1
    if (cum) { if (!out.length) out.push([a, 0]); out.push([b, st[4] / 1e6]) } else { out.push([a, st[2] / 1e3], [b, st[2] / 1e3]) }
  })
  return out
}

const isoDay = (v: number) => new Date(v * 864e5).toISOString().slice(0, 10)
const num = (s: string) => (s.trim() === '' || !Number.isFinite(Number(s.replace(',', '.'))) ? undefined : Number(s.replace(',', '.')))
type Lim = { min: string; max: string }

/** График ECharts: зум колесом и ползунком, подсказка со значением и датой, общая линия наведения у группы `link`. */
function Plot({ lines, cum, seasonAxis, xl, yl, link, title }: { lines: Line[]; cum: boolean; seasonAxis: boolean; xl: Lim; yl: Lim; link: string; title: string }) {
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
  useEffect(() => {
    const c = chart.current
    if (!c) return
    const xMin = seasonAxis ? num(xl.min) : xl.min ? Date.parse(xl.min) / 864e5 : undefined
    const xMax = seasonAxis ? num(xl.max) : xl.max ? Date.parse(xl.max) / 864e5 : undefined
    const xfmt = (v: number) => (seasonAxis ? fmt(v, 0) + ' сут' : isoDay(v))
    c.setOption({
      animation: false, color: lines.map(l => l.color),
      title: { text: title, left: 56, top: 0, textStyle: { fontSize: 12, fontWeight: 'normal', color: '#6b7a8a' } },
      grid: { left: 64, right: 16, top: 28, bottom: 62 },
      legend: { show: false },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'cross' },
        formatter: (ps: any) => {
          const arr = Array.isArray(ps) ? ps : [ps]
          if (!arr.length) return ''
          return xfmt(arr[0].value[0]) + '<br/>' + arr.map((p: any) => p.marker + p.seriesName + ': <b>' + fmt(p.value[1], cum ? 3 : 2) + '</b>').join('<br/>')
        },
      },
      toolbox: { right: 8, top: 0, feature: { saveAsImage: { title: 'PNG', name: title, pixelRatio: 2 }, dataZoom: { yAxisIndex: 'none', title: { zoom: 'Область', back: 'Назад' } }, restore: { title: 'Сброс' } } },
      xAxis: { type: 'value', min: xMin, max: xMax, scale: true, axisLabel: { formatter: xfmt, hideOverlap: true }, splitLine: { show: false } },
      yAxis: { type: 'value', min: num(yl.min), max: num(yl.max), name: cum ? 'млн м³' : 'тыс. м³/сут', nameTextStyle: { align: 'right' } },
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }, { type: 'slider', xAxisIndex: 0, height: 18, bottom: 8, filterMode: 'none' }],
      series: lines.map(l => ({ name: l.label, type: 'line', showSymbol: false, data: l.pts, lineStyle: { width: 2, type: l.dash ? 'dashed' : 'solid' } })),
    }, true)
  }, [lines, cum, seasonAxis, xl, yl, title])
  if (!lines.some(l => l.pts.length)) return <p className="muted">Нет данных для графика.</p>
  return <div ref={el} className="chart" style={{ width: '100%', maxWidth: 900, height: 300 }} role="img" aria-label={title} />
}

function Limits({ label, v, set, kind }: { label: string; v: Lim; set: (l: Lim) => void; kind: 'number' | 'date' }) {
  return <span className="row small"><span className="muted">{label}:</span>
    <input type={kind} style={{ width: kind === 'date' ? 140 : 80 }} placeholder="авто" value={v.min} onChange={e => set({ ...v, min: e.target.value })} />
    <span>—</span>
    <input type={kind} style={{ width: kind === 'date' ? 140 : 80 }} placeholder="авто" value={v.max} onChange={e => set({ ...v, max: e.target.value })} /></span>
}

function lineSet(data: ChartsView, by: string, cum: boolean, shown: string, multi: boolean): Line[] {
  const lines: Line[] = []
  data.scenarios.forEach((sc, si) => sc.series.forEach(s => {
    if (multi && s.label !== shown) return
    lines.push({
      label: (multi ? sc.name + ' · ' : '') + s.label, color: COLORS[(multi ? si : lines.length) % COLORS.length],
      dash: s.kind === 'отбор' && by !== 'season' ? 'dashed' : undefined, pts: toLine(s, cum, by === 'season'),
    })
  }))
  return lines
}

export default function Charts({ st }: { st: AppState }) {
  const [names, setNames] = useState<string[]>(st.scenarios.length ? [st.scenarios[0].name] : [])
  const [by, setBy] = useState('total')
  const [target, setTarget] = useState('')
  const [xl, setXl] = useState<Lim>({ min: '', max: '' })
  const [yr, setYr] = useState<Lim>({ min: '', max: '' })
  const [yc, setYc] = useState<Lim>({ min: '', max: '' })
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
  const linesR = data ? lineSet(data, by, false, shown, multi) : []
  const linesC = data ? lineSet(data, by, true, shown, multi) : []
  const lines = linesR
  const totals = data ? data.totals.filter(t => !multi || t.label === shown) : []

  return (
    <main className="workspace">
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
          <div className="row" style={{ marginTop: 8 }}>
            <Limits label={by === 'season' ? 'Ось X, сут' : 'Ось X'} v={xl} set={setXl} kind={by === 'season' ? 'number' : 'date'} />
            <Limits label="Расход, тыс. м³/сут" v={yr} set={setYr} kind="number" />
            <Limits label="Накопленный, млн м³" v={yc} set={setYc} kind="number" />
            <button onClick={() => { const z = { min: '', max: '' }; setXl(z); setYr(z); setYc(z) }}>Сбросить пределы</button>
          </div>
          {!data && <p className="muted small">Выбор группы или скважины доступен после первого построения. Закачка — сплошная линия, отбор — пунктир. Колесо мыши и ползунок — масштаб, наведение синхронно на обоих графиках, PNG — кнопка справа вверху.</p>}
        </>}
        {msg && <p className="note warn">{msg}</p>}
      </section>
      {data && <section className="card">
        {multi && <div className="row"><span className="muted small">Показатель для сравнения:</span>
          <select value={shown} onChange={e => setPick(e.target.value)}>{keys.map(k => <option key={k}>{k}</option>)}</select></div>}
        <Plot lines={linesR} cum={false} seasonAxis={by === 'season'} xl={xl} yl={yr} link="sched-charts" title="Расход, тыс. м³/сут" />
        <Plot lines={linesC} cum seasonAxis={by === 'season'} xl={xl} yl={yc} link="sched-charts" title="Накопленный объём, млн м³" />
        <div className="legend small">{lines.map((l, i) => <span key={i}><i style={{ background: l.color }} />{l.label}</span>)}</div>
        {data.scenarios.flatMap(s => s.notes.map(n => s.name + ': ' + n)).map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {totals.length > 0 && <table className="raw"><thead><tr><th>Сценарий</th><th>Ряд</th><th>Вид</th><th>Объём, млн м³</th></tr></thead>
          <tbody>{totals.map((t, i) => <tr key={i}><td>{t.scenario}</td><td>{t.label}</td><td>{t.kind}</td><td className="num">{fmt(t.total / 1e6, 3)}</td></tr>)}</tbody></table>}
      </section>}
    </main>
  )
}
