import { useEffect, useMemo, useState } from 'react'
import PageHead from './PageHead'
import { AppState, IndicatorRow, ResultsInfo, attachResults, getIndicators, getResultSeries, getResults, getState, pickFile } from './api'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))

interface Line { label: string; pts: [string, number][] }

/** Линии по датам на общем графике (как в Газовом Атласе): зум, подсказка, закрепление точек, PNG. */
function Plot({ lines, unit, title }: { lines: Line[]; unit: string; title: string; link?: string }) {
  const sig = lines.map(l => l.label + '|' + l.pts.length + '|' + (l.pts[0]?.join(',') ?? '') + '|' + (l.pts[l.pts.length - 1]?.join(',') ?? '')).join(';')
  // график пересобирается только при смене данных, иначе набор в соседних полях сбрасывал бы масштаб
  const chart = useMemo(() => mkChart('sched-res-' + title, title, mkAxis('Дата', '', 'time'), mkAxis(title, unit),
    lines.map((l, i) => mkSeries({ name: l.label, slot: i, x: l.pts.map(p => p[0]), y: l.pts.map(p => p[1]) }))), [sig, title, unit]) // eslint-disable-line
  if (!lines.some(l => l.pts.length)) return null
  return <ChartView chart={chart} excludeMode={false} onExclude={() => {}} />
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
      Object.entries(r.series).forEach(([w, s]) => lines.push({ label: n + ' · ' + w, pts: s.dates.map((d, i) => [d, s.values[i]] as [string, number]) }))
    }
    setPr(lines)
  })

  const shown = chosen.filter(n => ind[n])
  const line = (f: (r: IndicatorRow) => number | null): Line[] => shown.map(n => ({ label: n, pts: ind[n].filter(r => f(r) !== null).map(r => [r.date, f(r) as number] as [string, number]) }))
  const last = (n: string) => ind[n][ind[n].length - 1]
  const vecs = Array.from(new Set(chosen.flatMap(n => (infos[n]?.vectors || []).map(v => v.keyword))))
  const vec = chosen.flatMap(n => infos[n]?.vectors || []).find(v => v.keyword === kw)
  // единица из сводки модели; давление в BARSA/BARSG — абсолютное/избыточное
  const unit = ({ BARSA: 'бар (абс.)', BARSG: 'бар (изб.)', PSIA: 'psi (абс.)', PSIG: 'psi (изб.)' } as Record<string, string>)[(vec?.unit || '').toUpperCase()] ?? (vec?.unit || '')

  return (
    <main className="workspace">
      <PageHead title="Результаты расчёта" lede="Привяжите результаты модели к сценариям и сравните их по показателям." />
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
        <Plot lines={pr} unit={unit} title={kw + (vec?.label ? ' — ' + vec.label : '')} link="sched-results-p" />
      </section>}
    </main>
  )
}
