import { useMemo, useState } from 'react'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import { CompareResult, CompareRow, ModelEntry, comparePlanshet } from './api'

const fmt = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))

interface Stat { n: number; mean: number; median: number; std: number; mae: number; rmse: number; min: number; max: number; share: number }
/** Те же формулы, что на сервере (schedule_pxg/gwc_compare.stats): считаются здесь, чтобы исключение строки сразу меняло итог. */
function stat(d: number[]): Stat | null {
  const n = d.length
  if (!n) return null
  const mean = d.reduce((a, b) => a + b, 0) / n, s = [...d].sort((a, b) => a - b)
  return { n, mean, median: n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2, std: n > 1 ? Math.sqrt(d.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : 0,
    mae: d.reduce((a, b) => a + Math.abs(b), 0) / n, rmse: Math.sqrt(d.reduce((a, b) => a + b * b, 0) / n), min: s[0], max: s[n - 1], share: d.filter(x => Math.abs(x) < 1).length / n }
}

export default function GwcCompare({ models, thr, alts }: { models: ModelEntry[]; thr: string; alts: Record<string, string> }) {
  const [modelId, setModelId] = useState('')
  const [wells, setWells] = useState('')
  const [res, setRes] = useState<CompareResult | null>(null)
  const [slices, setSlices] = useState<Record<string, string>>({})
  const [off, setOff] = useState<string[]>([])           // исключено из статистики вручную
  const [by, setBy] = useState<'pack' | 'season' | 'group'>('pack')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const model = modelId || models[0]?.id || ''

  const run = async (sl: Record<string, string>) => {
    setBusy(true); setMsg('')
    try {
      setRes(await comparePlanshet({ model, wells: wells.split(/[;,|\s]+/).map(x => x.trim()).filter(Boolean), thr: Number(thr.replace(',', '.')) || 0.01, slices: sl, alts }))
    } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const setSlice = (r: CompareRow, v: string) => { const sl = { ...slices }; const k = r.well + '|' + r.date; if (v) sl[k] = v; else delete sl[k]; setSlices(sl); run(sl) }
  const toggle = (k: string) => setOff(off.includes(k) ? off.filter(x => x !== k) : [...off, k])

  const rows = res?.rows || []
  const used = rows.filter((r: CompareRow) => r.delta !== null && !off.includes(r.key))
  const groups = useMemo(() => Array.from(new Set(used.map(r => r[by]))).sort(), [used.length, by, off.join('|')]) // eslint-disable-line
  const all = stat(used.map(r => r.delta as number))

  const scatter = useMemo(() => {
    if (!used.length) return null
    const lo = Math.min(...used.flatMap(r => [r.fact, r.model as number])), hi = Math.max(...used.flatMap(r => [r.fact, r.model as number]))
    const pts = mkSeries({ name: 'Скважина · пачка', kind: 'points', slot: 0, x: used.map(r => r.fact), y: used.map(r => r.model as number) })
    pts.labels = used.map(r => r.well + ' · ' + r.pack + ' · ' + r.date)
    const one = mkSeries({ name: '1:1', slot: 3, dashed: true, x: [lo, hi], y: [lo, hi] })
    return mkChart('gdm-gwc-11', 'ГВК: модель против факта', mkAxis('Факт ГИС', 'м, а.о.', 'value'), mkAxis('Модель', 'м, а.о.', 'value'), [one, pts])
  }, [used.map(r => r.key).join('|')]) // eslint-disable-line
  const bars = useMemo(() => {
    if (!used.length) return null
    const names = Array.from(new Set(used.map(r => r.well)))
    const mean = names.map(w => { const d = used.filter(r => r.well === w).map(r => r.delta as number); return d.reduce((a, b) => a + b, 0) / d.length })
    return mkChart('gdm-gwc-delta', 'Δ ГВК по скважинам (модель − факт)', mkAxis('Скважина', '', 'category', { categories: names }), mkAxis('Δ', 'м'),
      [mkSeries({ name: 'Δ среднее по замерам', kind: 'bar', slot: 1, x: names, y: mean })])
  }, [used.map(r => r.key).join('|')]) // eslint-disable-line

  if (!models.length) return <section className="card"><h2>Сравнение факта ГИС с моделью</h2><p className="muted">Отметьте модель в разделе «Результаты расчёта».</p></section>
  return (
    <section className="card">
      <h2>Сравнение факта ГИС с моделью</h2>
      <p className="muted small">Все замеры выбранных скважин. Срез модели для замера подбирается сам (осень — начало паузы после закачки, весна — конец паузы после отбора, по эталонному суточному объёму),
        это подсказка: дату среза можно поменять в таблице. Строку можно исключить из статистики. Δ = модель − факт; пары «не достигнут» и «газа нет» считаются отдельно. Порог Sg и альтитуды — из полей планшета выше.</p>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <select value={model} onChange={e => { setModelId(e.target.value); setRes(null) }}>{models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
        <input style={{ width: 260 }} placeholder="скважины через запятую (пусто — все в базе ГИС)" value={wells} onChange={e => setWells(e.target.value)} />
        <button className="primary" disabled={busy || !model} onClick={() => run(slices)}>Сравнить</button>
        {busy && <span className="muted small">считаю…</span>}
      </div>
      {msg && <p className="note warn">{msg}</p>}
      {res?.notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
      {res && <>
        <p className="muted small">Пар в статистике: {used.length}; исключено вручную: {rows.filter(r => off.includes(r.key) && r.delta !== null).length};
          не достигнут: {res.skipped['не достигнут'] || 0}; газа нет: {res.skipped['газа нет'] || 0}; нет модели: {res.skipped['нет модели'] || 0}.</p>
        <div className="row"><span className="muted small">Статистика по:</span>
          {([['pack', 'пачкам'], ['season', 'сезонам'], ['group', 'группам']] as const).map(([k, l]) => <label key={k}><input type="radio" checked={by === k} onChange={() => setBy(k)} /> {l}</label>)}</div>
        <div style={{ overflowX: 'auto' }}><table className="raw"><thead><tr><th></th><th>n</th><th>Среднее, м</th><th>Медиана, м</th><th>СКО, м</th><th>MAE, м</th><th>RMSE, м</th><th>min, м</th><th>max, м</th><th>доля |Δ|&lt;1 м</th></tr></thead>
          <tbody>{[['Все', all] as [string, Stat | null], ...groups.map(g => [g || '—', stat(used.filter(r => r[by] === g).map(r => r.delta as number))] as [string, Stat | null])].map(([name, s]) =>
            s && <tr key={name}><td>{name}</td><td className="num">{s.n}</td><td className="num">{fmt(s.mean)}</td><td className="num">{fmt(s.median)}</td><td className="num">{fmt(s.std)}</td>
              <td className="num">{fmt(s.mae)}</td><td className="num">{fmt(s.rmse)}</td><td className="num">{fmt(s.min)}</td><td className="num">{fmt(s.max)}</td><td className="num">{fmt(s.share * 100, 0)}%</td></tr>)}</tbody></table></div>
        {scatter && <ChartView chart={scatter} excludeMode={false} onExclude={() => {}} />}
        {bars && <ChartView chart={bars} excludeMode={false} onExclude={() => {}} />}
        <div style={{ overflowX: 'auto' }}><table className="raw"><thead><tr><th>В статистике</th><th>Скважина</th><th>Группа</th><th>Замер</th><th>Сезон</th><th>Срез модели</th><th>Пачка</th><th>ГВК факт, м</th><th>ГВК модель, м</th><th>Δ, м</th><th>Статус</th></tr></thead>
          <tbody>{rows.map(r => <tr key={r.key} style={off.includes(r.key) ? { opacity: 0.5 } : undefined}>
            <td><input type="checkbox" disabled={r.delta === null} checked={r.delta !== null && !off.includes(r.key)} onChange={() => toggle(r.key)} aria-label="Учитывать в статистике" /></td>
            <td>{r.well}</td><td>{r.group || '—'}</td><td>{r.date}</td><td>{r.season || '—'}</td>
            <td title={r.slice_why}><input type="date" style={{ width: 140 }} value={r.slice} disabled={busy} onChange={e => setSlice(r, e.target.value)} />
              {slices[r.well + '|' + r.date] && <button disabled={busy} title="Вернуть подбор" onClick={() => setSlice(r, '')}>↺</button>}<span className="muted small"> {r.slice_why}</span></td>
            <td>{r.pack}{r.label && r.label !== 'ГВК' ? ' (' + r.label + ')' : ''}</td><td className="num">{fmt(r.fact)}</td><td className="num">{fmt(r.model)}</td><td className="num">{fmt(r.delta)}</td><td className="small">{r.status}</td></tr>)}</tbody></table></div>
      </>}
    </section>
  )
}
