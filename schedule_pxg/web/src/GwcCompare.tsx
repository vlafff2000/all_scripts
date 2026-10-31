import { useMemo, useState } from 'react'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import CriterionPicker from './CriterionPicker'
import { CompareResult, CompareRow, CriterionCfg, ModelEntry, comparePlanshet } from './api'
import { Tables } from '../../../pxg_core/web-ui/table/Tables'
import { tableOf } from '../../../pxg_core/web-ui/table/tableBuild'

const MAX_COMBOS = 12
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

export default function GwcCompare({ models, criterion, alts }: { models: ModelEntry[]; criterion: CriterionCfg; alts: Record<string, string> }) {
  const [picked, setPicked] = useState<string[]>([])
  const [variants, setVariants] = useState<CriterionCfg[]>([])
  const [wells, setWells] = useState('')
  const [res, setRes] = useState<CompareResult | null>(null)
  const [slices, setSlices] = useState<Record<string, string>>({})
  const [off, setOff] = useState<string[]>([])           // исключено из статистики вручную
  const [by, setBy] = useState<'pack' | 'season' | 'group' | 'series'>('pack')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const modelIds = picked.length ? picked : models.slice(0, 1).map(m => m.id)
  const variantList = variants.length ? variants : [criterion]
  const combos = modelIds.length * variantList.length

  const run = async (sl: Record<string, string>) => {
    setBusy(true); setMsg('')
    try {
      const thr = criterion.logic === 'sg' ? criterion.value : criterion.fallback
      setRes(await comparePlanshet({ models: modelIds, variants: variantList, wells: wells.split(/[;,|\s]+/).map(x => x.trim()).filter(Boolean), thr, slices: sl, alts, criterion }))
    } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const setSlice = (r: CompareRow, v: string) => { const sl = { ...slices }; const k = r.well + '|' + r.date; if (v) sl[k] = v; else delete sl[k]; setSlices(sl); run(sl) }
  const toggle = (k: string) => setOff(off.includes(k) ? off.filter(x => x !== k) : [...off, k])
  const toggleModel = (id: string, on: boolean) => setPicked(on ? [...modelIds.filter(x => x !== id), id] : modelIds.filter(x => x !== id))
  const setVariant = (i: number, c: CriterionCfg) => setVariants(variantList.map((x, j) => (j === i ? c : x)))

  const rows = res?.rows || []
  const used = rows.filter((r: CompareRow) => r.delta !== null && !off.includes(r.key))
  const groups = useMemo(() => Array.from(new Set(used.map(r => r[by] || ''))).sort(), [used.length, by, off.join('|')]) // eslint-disable-line
  const all = stat(used.map(r => r.delta as number))
  const seriesNames = Array.from(new Set(used.map(r => r.series || '')))
  const colour = (i: number) => `var(--chart-series-${(i % 6) + 1}, hsl(${(i * 67) % 360} 60% 45%))`

  const scatter = useMemo(() => {
    if (!used.length) return null
    const lo = Math.min(...used.flatMap(r => [r.fact, r.model as number])), hi = Math.max(...used.flatMap(r => [r.fact, r.model as number]))
    const one = mkSeries({ name: '1:1', slot: 3, dashed: true, x: [lo, hi], y: [lo, hi] })
    const pts = seriesNames.map((name, k) => {
      const part = used.filter(r => (r.series || '') === name)
      const p = mkSeries({ name: name ? name + ' · скважина' : 'Скважина · пачка', kind: 'points', slot: k % 3, x: part.map(r => r.fact), y: part.map(r => r.model as number) })
      p.labels = part.map(r => r.well + ' · ' + r.pack + ' · ' + r.date)
      return p
    })
    return mkChart('gdm-gwc-11', 'ГВК: модель против факта', mkAxis('Факт ГИС', 'м, а.о.', 'value'), mkAxis('Модель', 'м, а.о.', 'value'), [one, ...pts])
  }, [used.map(r => r.key).join('|')]) // eslint-disable-line
  const bars = useMemo(() => {
    if (!used.length) return null
    const names = Array.from(new Set(used.map(r => r.well)))
    const series = seriesNames.map((name, k) => mkSeries({ name: name || 'Δ среднее по замерам', kind: 'bar', slot: k % 3, x: names,
      y: names.map(w => { const d = used.filter(r => r.well === w && (r.series || '') === name).map(r => r.delta as number); return d.length ? d.reduce((a, b) => a + b, 0) / d.length : 0 }) }))
    return mkChart('gdm-gwc-delta', 'Δ ГВК по скважинам (модель − факт)', mkAxis('Скважина', '', 'category', { categories: names }), mkAxis('Δ', 'м'), series)
  }, [used.map(r => r.key).join('|')]) // eslint-disable-line

  if (!models.length) return <section className="card"><h2>Сравнение факта ГИС с моделью</h2><p className="muted">Отметьте модель в разделе «Результаты расчёта».</p></section>
  return (
    <section className="card">
      <h2>Сравнение факта ГИС с моделью</h2>
      <p className="muted small">Все замеры выбранных скважин. Срез модели для замера подбирается сам (осень — начало паузы после закачки, весна — конец паузы после отбора, по эталонному суточному объёму),
        это подсказка: дату среза можно поменять в таблице. Строку можно исключить из статистики. Δ = модель − факт; пары «не достигнут» и «газа нет» считаются отдельно. Альтитуды — из полей планшета выше.</p>
      <div className="row" style={{ flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <span className="muted small">Модели:</span>
        {models.map(m => <label key={m.id} className="check"><input type="checkbox" checked={modelIds.includes(m.id)} onChange={e => toggleModel(m.id, e.target.checked)} /> {m.name}</label>)}
      </div>
      <div style={{ display: 'grid', gap: 6, margin: '6px 0' }}>
        <span className="muted small">Варианты расчёта ГВК (сочетаний с моделями: {combos} из {MAX_COMBOS}):</span>
        {variantList.map((v, i) => (
          <div key={i} className="row" style={{ flexWrap: 'wrap' }}>
            <CriterionPicker value={v} onChange={c => setVariant(i, c)} />
            {variants.length > 1 && <button type="button" onClick={() => setVariants(variants.filter((_, j) => j !== i))}>Убрать</button>}
          </div>
        ))}
        <div className="row">
          <button type="button" disabled={variantList.length >= MAX_COMBOS} onClick={() => setVariants([...variantList, { ...criterion }])}>Добавить вариант</button>
          {combos > MAX_COMBOS && <span className="note warn">Сочетаний больше {MAX_COMBOS}: уберите модель или вариант</span>}
        </div>
      </div>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <input style={{ width: 260 }} placeholder="скважины через запятую (пусто — все в базе ГИС)" value={wells} onChange={e => setWells(e.target.value)} />
        <button className="primary" disabled={busy || !modelIds.length || combos > MAX_COMBOS} onClick={() => run(slices)}>Сравнить</button>
        {busy && <span className="muted small">считаю…</span>}
      </div>
      {msg && <p className="note warn">{msg}</p>}
      {res?.notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
      {res && <>
        {res.series.length > 0 && <div className="row" style={{ flexWrap: 'wrap', gap: 10 }}>
          {res.series.map((s, i) => <span key={s.key} className="small" title={s.formula}><span style={{ display: 'inline-block', width: 12, height: 12, background: colour(i), marginRight: 4 }} />{s.name}</span>)}
        </div>}
        <p className="muted small">Пар в статистике: {used.length}; исключено вручную: {rows.filter(r => off.includes(r.key) && r.delta !== null).length};
          не достигнут: {res.skipped['не достигнут'] || 0}; газа нет: {res.skipped['газа нет'] || 0}; нет модели: {res.skipped['нет модели'] || 0}.</p>
        <div className="row"><span className="muted small">Статистика по:</span>
          {([['pack', 'пачкам'], ['season', 'сезонам'], ['group', 'группам'], ['series', 'модели · критерию']] as const).map(([k, l]) => <label key={k}><input type="radio" checked={by === k} onChange={() => setBy(k)} /> {l}</label>)}</div>
        <Tables scope="sched-gwc-stat" tables={[tableOf('stat', 'Статистика Δ ГВК',
          [({ pack: 'Пачка', season: 'Сезон', group: 'Группа', series: 'Модель · критерий' })[by], ['n', 'number', 0], ['Среднее, м', 'number', 2], ['Медиана, м', 'number', 2], ['СКО, м', 'number', 2], ['MAE, м', 'number', 2], ['RMSE, м', 'number', 2], ['min, м', 'number', 2], ['max, м', 'number', 2], ['доля |Δ|<1 м, %', 'number', 0]],
          ([['Все', all] as [string, Stat | null], ...groups.map(g => [g || '—', stat(used.filter(r => (r[by] || '') === g).map(r => r.delta as number))] as [string, Stat | null])])
            .flatMap(([name, s]) => (s ? [[name, s.n, s.mean, s.median, s.std, s.mae, s.rmse, s.min, s.max, s.share * 100]] : [])))]} />
        {scatter && <ChartView chart={scatter} excludeMode={false} onExclude={() => {}} />}
        {bars && <ChartView chart={bars} excludeMode={false} onExclude={() => {}} />}
        <div style={{ overflowX: 'auto' }}><table className="raw"><thead><tr><th>В статистике</th><th>Модель · критерий</th><th>Скважина</th><th>Группа</th><th>Замер</th><th>Сезон</th><th>Срез модели</th><th>Пачка</th><th>ГВК факт, м</th><th>ГВК модель, м</th><th>Δ, м</th><th>Статус</th></tr></thead>
          <tbody>{rows.map(r => <tr key={r.key} style={off.includes(r.key) ? { opacity: 0.5 } : undefined}>
            <td><input type="checkbox" disabled={r.delta === null} checked={r.delta !== null && !off.includes(r.key)} onChange={() => toggle(r.key)} aria-label="Учитывать в статистике" /></td>
            <td className="small">{r.series || '—'}</td>
            <td>{r.well}</td><td>{r.group || '—'}</td><td>{r.date}</td><td>{r.season || '—'}</td>
            <td title={r.slice_why}><input type="date" style={{ width: 140 }} value={r.slice} disabled={busy} onChange={e => setSlice(r, e.target.value)} />
              {slices[r.well + '|' + r.date] && <button disabled={busy} title="Вернуть подбор" onClick={() => setSlice(r, '')}>↺</button>}<span className="muted small"> {r.slice_why}</span></td>
            <td>{r.pack}{r.label && r.label !== 'ГВК' ? ' (' + r.label + ')' : ''}</td><td className="num">{fmt(r.fact)}</td><td className="num">{fmt(r.model)}</td><td className="num">{fmt(r.delta)}</td><td className="small">{r.status}</td></tr>)}</tbody></table></div>
      </>}
    </section>
  )
}
