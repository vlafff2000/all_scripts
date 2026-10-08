import { useState } from 'react'
import { AppState, ChartSeries, ChartsView, getCharts } from './api'

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

function Plot({ lines, cum, seasonAxis }: { lines: Line[]; cum: boolean; seasonAxis: boolean }) {
  const W = 760, H = 300, L = 56, R = 12, T = 10, B = 28
  const xs = lines.flatMap(l => l.pts.map(p => p[0])), ys = lines.flatMap(l => l.pts.map(p => p[1]))
  if (!xs.length) return <p className="muted">Нет данных для графика.</p>
  const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1), y1 = Math.max(...ys, 1e-9) * 1.08
  const X = (v: number) => L + ((v - x0) / (x1 - x0)) * (W - L - R)
  const Y = (v: number) => T + (H - T - B) * (1 - v / y1)
  const xt = Array.from({ length: 6 }, (_, i) => x0 + ((x1 - x0) * i) / 5)
  const lab = (v: number) => (seasonAxis ? fmt(v, 0) + ' сут' : new Date(v * 864e5).toISOString().slice(0, 10))
  return (
    <svg viewBox={'0 0 ' + W + ' ' + H} className="chart" style={{ maxWidth: 820 }} role="img" aria-label={cum ? 'Накопленный объём' : 'Расход'}>
      {[0, .25, .5, .75, 1].map(t => <g key={t}><line x1={L} x2={W - R} y1={Y(y1 * t)} y2={Y(y1 * t)} stroke="var(--line)" />
        <text x={L - 6} y={Y(y1 * t) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">{fmt(y1 * t, y1 < 10 ? 2 : 0)}</text></g>)}
      {xt.map((v, i) => <text key={i} x={X(v)} y={H - 8} textAnchor={i === 0 ? 'start' : i === 5 ? 'end' : 'middle'} fontSize="11" fill="var(--muted)">{lab(v)}</text>)}
      {lines.map((l, i) => <path key={i} d={l.pts.map((p, k) => (k ? 'L' : 'M') + X(p[0]).toFixed(1) + ',' + Y(p[1]).toFixed(1)).join('')}
        fill="none" stroke={l.color} strokeWidth="2" strokeDasharray={l.dash} strokeLinejoin="round"><title>{l.label}</title></path>)}
    </svg>
  )
}

export default function Charts({ st }: { st: AppState }) {
  const [names, setNames] = useState<string[]>(st.scenarios.length ? [st.scenarios[0].name] : [])
  const [by, setBy] = useState('total')
  const [target, setTarget] = useState('')
  const [cum, setCum] = useState(false)
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
  const lines: Line[] = []
  if (data) data.scenarios.forEach((sc, si) => sc.series.forEach((s, k) => {
    if (multi && s.label !== shown) return
    lines.push({
      label: (multi ? sc.name + ' · ' : '') + s.label, color: COLORS[(multi ? si : lines.length) % COLORS.length],
      dash: s.kind === 'отбор' && by !== 'season' ? '6 3' : undefined, pts: toLine(s, cum, by === 'season'),
    })
    void k
  }))
  const totals = data ? data.totals.filter(t => !multi || t.label === shown) : []

  return (
    <main className="work">
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
            <label><input type="radio" checked={!cum} onChange={() => setCum(false)} /> расход, тыс. м³/сут</label>
            <label><input type="radio" checked={cum} onChange={() => setCum(true)} /> накопленный, млн м³</label>
          </div>
          {!data && <p className="muted small">Выбор группы или скважины доступен после первого построения. Закачка — сплошная линия, отбор — пунктир.</p>}
        </>}
        {msg && <p className="note warn">{msg}</p>}
      </section>
      {data && <section className="card">
        {multi && <div className="row"><span className="muted small">Показатель для сравнения:</span>
          <select value={shown} onChange={e => setPick(e.target.value)}>{keys.map(k => <option key={k}>{k}</option>)}</select></div>}
        <Plot lines={lines} cum={cum} seasonAxis={by === 'season'} />
        <div className="legend small">{lines.map((l, i) => <span key={i}><i style={{ background: l.color }} />{l.label}</span>)}</div>
        {data.scenarios.flatMap(s => s.notes.map(n => s.name + ': ' + n)).map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {totals.length > 0 && <table className="raw"><thead><tr><th>Сценарий</th><th>Ряд</th><th>Вид</th><th>Объём, млн м³</th></tr></thead>
          <tbody>{totals.map((t, i) => <tr key={i}><td>{t.scenario}</td><td>{t.label}</td><td>{t.kind}</td><td className="num">{fmt(t.total / 1e6, 3)}</td></tr>)}</tbody></table>}
      </section>}
    </main>
  )
}
