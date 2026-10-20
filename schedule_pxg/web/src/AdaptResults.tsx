import { useEffect, useMemo, useState } from 'react'
import { AdaptConfig, AdaptResultRow, AdaptRun, AdaptView, adaptFileUrl, adaptRecompute, adaptRun, adaptRuns, pickFile } from './api'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'

const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const sci = (x: number | null | undefined) => (x === null || x === undefined ? '—' : x === 0 ? '0' : x.toExponential(2))
const nn = (a: (number | null)[]) => a.map(v => v as number)

type Key = keyof AdaptResultRow
const COLS: [Key, string, (r: AdaptResultRow) => string][] = [
  ['well', 'Скв.', r => r.well], ['date', 'ГДИ', r => r.date], ['n_regimes', 'Режимов', r => String(r.n_regimes)],
  ['pi_mult', 'WPIMULT', r => fmt(r.pi_mult, 3)], ['pi_lo', 'Диапазон', r => r.pi_lo === null ? '—' : fmt(r.pi_lo, 3) + ' … ' + fmt(r.pi_hi, 3)],
  ['d', 'D-фактор', r => sci(r.d)], ['r2_old', 'R² до', r => fmt(r.r2_old, 3)], ['r2', 'R² после', r => fmt(r.r2, 3)],
  ['mape_old', 'Ошибка Q до, %', r => fmt(r.mape_old, 1)], ['mape', 'после, %', r => fmt(r.mape, 1)],
  ['dp2_err_before', 'Ошибка ΔP² до, %', r => fmt(r.dp2_err_before, 1)], ['dp2_err_after', 'после, %', r => fmt(r.dp2_err_after, 1)],
  ['a_gdi', 'A ГДИ', r => fmt(r.a_gdi, 4)], ['a_model', 'A модель', r => fmt(r.a_model, 4)],
  ['b_gdi', 'B ГДИ', r => fmt(r.b_gdi, 5)], ['b_model', 'B модель', r => fmt(r.b_model, 5)],
  ['q_ratio', 'Q модели / Q ГДИ', r => fmt(r.q_ratio, 2)],
]

/** Шаг 5 вкладки «Адаптация по ГДИ»: результаты прогона. Снимки из тНавигатора → пересчёт без него → таблица, графики, группы. */
export default function AdaptResults({ kit, config }: { kit: string; config: Partial<AdaptConfig> }) {
  const [snap, setSnap] = useState('')
  const [runs, setRuns] = useState<AdaptRun[]>([])
  const [view, setView] = useState<AdaptView | null>(null)
  const [well, setWell] = useState('')
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState<{ k: Key; dir: 1 | -1 }>({ k: 'well', dir: 1 })
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const guard = async (f: () => Promise<void>) => { setBusy(true); setMsg(''); try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) } }
  const reload = () => kit ? adaptRuns(kit).then(r => setRuns(r.runs)).catch(() => setRuns([])) : Promise.resolve()
  useEffect(() => { reload() }, [kit])
  const id = (r: AdaptResultRow) => r.well + '|' + r.date
  const show = (v: AdaptView) => { setView(v); setWell(v.rows[0] ? id(v.rows[0]) : '') }

  const pick = () => guard(async () => { const r = await pickFile(snap || kit); if (r.path) setSnap(r.path) })
  const calc = () => guard(async () => { show(await adaptRecompute(kit, snap || kit, config)); await reload() })
  const open = (d: string) => guard(async () => show(await adaptRun(d)))

  const rows = useMemo(() => {
    const f = (view?.rows || []).filter(r => filter === 'all' ? true : filter === 'problems' ? !r.ok : filter === 'bound' ? r.at_bound : filter === 'unstable' ? r.problems.some(p => p.includes('неустойчив')) : filter === 'worse' ? (r.r2 ?? 0) < (r.r2_old ?? 0) : true)
    const cmp = (a: AdaptResultRow, b: AdaptResultRow) => { const x = a[sort.k] as unknown, y = b[sort.k] as unknown; return (x === null ? 1 : y === null ? -1 : x! < y! ? -1 : x! > y! ? 1 : 0) * sort.dir }
    return [...f].sort(cmp)
  }, [view, filter, sort])
  const cur = view?.rows.find(r => id(r) === well)
  const pos = rows.findIndex(r => id(r) === well)
  // Все исследования выбранной скважины по дате; список скважин — из текущего отфильтрованного списка.
  const wellDates = useMemo(() => cur ? (view?.rows || []).filter(r => r.well === cur.well).sort((a, b) => a.date < b.date ? -1 : 1) : [], [view, cur])
  const wellNames = useMemo(() => [...new Set(rows.map(r => r.well))].filter(w => w.toLowerCase().includes(q.trim().toLowerCase()))
    .sort((a, b) => a.localeCompare(b, 'ru', { numeric: true })), [rows, q])
  // Выбор скважины открывает её самое свежее исследование.
  const pickWell = (w: string) => { const last = (view?.rows || []).filter(r => r.well === w).sort((a, b) => a.date < b.date ? -1 : 1).pop(); if (last) setWell(id(last)) }
  const step = (d: 1 | -1) => {
    if (!rows.length) return
    const j = pos < 0 ? (d > 0 ? 0 : rows.length - 1) : Math.min(rows.length - 1, Math.max(0, pos + d))
    setWell(id(rows[j]))
  }
  const stepInfo = (() => {
    const ex = cur as (AdaptResultRow & { t_requested?: string; shift_days?: number | null }) | undefined
    if (!ex) return ''
    const parts = []
    if (ex.t_name) parts.push('шаг модели ' + ex.t_name + (ex.t_requested && ex.t_requested !== ex.t_name ? ' (на дату ГДИ стояла ' + ex.t_requested + ')' : ''))
    if (typeof ex.shift_days === 'number') parts.push('сдвиг ' + ex.shift_days + ' дн.')
    return parts.join(', ')
  })()

  const dyn = useMemo(() => {
    const pts = wellDates.filter(r => r.pi_mult !== null)
    return pts.length < 2 ? null : mkChart('adapt-dyn', 'Динамика WPIMULT по датам ГДИ, скв. ' + cur!.well, mkAxis('Дата ГДИ', '', 'time'), mkAxis('WPIMULT (итого от базовой модели)', '', 'value'), [
      mkSeries({ name: 'WPIMULT', kind: 'points', slot: 0, x: pts.map(r => Date.parse(r.date)), y: pts.map(r => r.pi_mult!) }),
      mkSeries({ name: 'линия', slot: 0, x: pts.map(r => Date.parse(r.date)), y: pts.map(r => r.pi_mult!) })])
  }, [wellDates, cur])

  const curve = useMemo(() => cur && mkChart('adapt-ip', 'Индикаторная кривая, скв. ' + cur.well + ' от ' + cur.date, mkAxis('Дебит', 'тыс. м³/сут'), mkAxis('ΔP² = Pпл² − Pз²', 'бар²', 'value', { from_zero: true }), [
    mkSeries({ name: 'ГДИ', kind: 'points', slot: 3, x: nn(cur.q_gdi), y: nn(cur.dp2_gdi) }),
    mkSeries({ name: 'модель до', slot: 5, dashed: true, x: nn(cur.curve_q), y: cur.curve_before as number[] }),
    mkSeries({ name: 'модель после', slot: 0, x: nn(cur.curve_q), y: cur.curve_after as number[] }),
  ]), [cur])
  const hist = useMemo(() => {
    const v = (view?.rows || []).map(r => r.pi_mult).filter((x): x is number => x !== null && x > 0).map(Math.log10)
    if (!v.length) return null
    const lo = Math.floor(Math.min(...v) * 2) / 2, hi = Math.max(Math.ceil(Math.max(...v) * 2) / 2, lo + 0.5)
    const n = Math.round((hi - lo) / 0.5), cnt = Array(n).fill(0)
    v.forEach(x => { cnt[Math.min(n - 1, Math.floor((x - lo) / 0.5))]++ })
    const cats = cnt.map((_, i) => fmt(Math.pow(10, lo + i * 0.5), 3) + '–' + fmt(Math.pow(10, lo + (i + 1) * 0.5), 3))
    return mkChart('adapt-hist', 'Распределение WPIMULT', mkAxis('WPIMULT', '', 'category', { categories: cats }), mkAxis('Скважин', '', 'value', { from_zero: true }),
      [mkSeries({ name: 'скважин', kind: 'bar', slot: 0, x: cats, y: cnt })])
  }, [view])
  const r2c = useMemo(() => {
    const p = (view?.rows || []).filter(r => r.r2 !== null && r.r2_old !== null)
    if (!p.length) return null
    const lo = Math.min(-0.2, ...p.map(r => Math.max(r.r2_old!, -1)))
    return mkChart('adapt-r2', 'R² до и после адаптации', mkAxis('R² до', ''), mkAxis('R² после', ''), [
      mkSeries({ name: 'скважины', kind: 'points', slot: 0, x: p.map(r => Math.max(r.r2_old!, -1)), y: p.map(r => r.r2!) }),
      mkSeries({ name: 'без изменений', slot: 6, dashed: true, width: 1, x: [lo, 1], y: [lo, 1] })])
  }, [view])
  const th = (k: Key, t: string) => <th key={k} onClick={() => setSort(s => ({ k, dir: s.k === k ? (-s.dir as 1 | -1) : 1 }))} style={{ cursor: 'pointer' }}>{t}{sort.k === k ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''}</th>
  const s = view?.summary

  return (
    <section className="card">
      <div className="step-head"><span className="step-n">6</span><h2>Результаты</h2></div>
      <p className="lead">Когда код отработал в тНавигаторе (шаг 5), укажите созданный им <code>snapshots.pkl</code> или папку <code>runs</code>; по умолчанию берётся самый свежий. Дальше настройки сверху можно менять и пересчитывать здесь, без тНавигатора.</p>
      <div className="row">
        <label className="grow">Снимки модели<input value={snap} onChange={e => setSnap(e.target.value)} placeholder={kit ? kit + ' (самый свежий snapshots.pkl)' : 'Сначала подготовьте комплект'} /></label>
        <button onClick={pick} disabled={busy || !kit}>Выбрать файл</button>
        <button className="primary" onClick={calc} disabled={busy || !kit}>Пересчитать</button>
        {runs.length > 0 && <label>Прошлые запуски<select value="" onChange={e => e.target.value && open(e.target.value)}>
          <option value="">— открыть —</option>{runs.filter(r => r.has_results).map(r => <option key={r.dir} value={r.dir}>{r.name}</option>)}</select></label>}
      </div>
      {msg && <p className="note warn">{msg}</p>}
      <p className="muted small">WPIMULT в тНавигаторе накопительный: множитель подобран относительно модели такой, какая она на дату ГДИ, поэтому вставляйте include на эту дату и учитывайте, что все более поздние WPIMULT скважины перемножатся с ним.</p>

      {view && s && <>
        <div className="row" style={{ gap: 18 }}>
          <span>Скважин: <b>{s.wells}</b></span><span>без замечаний: <b>{s.ok}</b></span><span>с замечаниями: <b>{s.with_problems}</b></span>
          <span>на границе: <b>{s.at_bound}</b></span><span>неустойчивых: <b>{s.unstable}</b></span><span>пропущено: <b>{s.skipped}</b></span>
          <span>R² (медиана): <b>{fmt(s.r2_old, 2)} → {fmt(s.r2, 3)}</b></span><span>ошибка Q: <b>{fmt(s.mape_old, 1)} → {fmt(s.mape, 1)} %</b></span>
          <span>WPIMULT (медиана): <b>{fmt(s.pi_mult, 3)}</b></span>
        </div>
        <div className="row">
          <a href={adaptFileUrl(view.run_dir, 'inc')} download><button>Скачать wpimult_wdfac.inc</button></a>
          <a href={adaptFileUrl(view.run_dir, 'xlsx')} download><button>Excel-отчёт</button></a>
          <a href={adaptFileUrl(view.run_dir, 'csv')} download><button>results.csv</button></a>
          <span className="muted small">Запуск: {view.run_dir}</span>
        </div>

        <div className="row">
          <label>Показать<select value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="all">все скважины</option><option value="problems">с замечаниями</option><option value="bound">WPIMULT на границе</option>
            <option value="unstable">неустойчивые</option><option value="worse">R² стало хуже</option></select></label>
          <span className="muted small">Нажмите на строку, чтобы посмотреть график скважины; на заголовок — сортировать.</span>
        </div>
        <div className="scroll" style={{ maxHeight: 460 }}><table className="raw"><thead><tr>{COLS.map(([k, t]) => th(k, t))}<th>Замечания</th></tr></thead>
          <tbody>{rows.map(r => <tr key={id(r)} className={(r.ok ? '' : 'warnrow ') + (id(r) === well ? 'sel' : '')} onClick={() => setWell(id(r))} style={id(r) === well ? { background: 'var(--accent-soft)' } : undefined}>
            {COLS.map(([k, , f]) => <td key={k}>{f(r)}</td>)}<td className="muted small">{[...r.problems, ...r.notes].join('; ')}</td></tr>)}</tbody></table></div>
        {view.failures.length > 0 && <details><summary className="muted small">Пропущено скважин: {view.failures.length}</summary>
          <ul className="issues">{view.failures.map(f => <li key={f.well}><b>{f.well}</b>: {f.reason}</li>)}</ul></details>}

        <h3>Графики выбранного исследования</h3>
        {cur && <div className="row adapt-pick">
          <label>Поиск скважины<input value={q} onChange={e => setQ(e.target.value)} placeholder="номер" style={{ width: 120 }} /></label>
          <label>Скважина<select value={wellNames.includes(cur.well) ? cur.well : ''} onChange={e => pickWell(e.target.value)}>
            {!wellNames.includes(cur.well) && <option value="">— нет в поиске —</option>}{wellNames.map(w => <option key={w} value={w}>{w}</option>)}</select></label>
          <label>Исследование ГДИ<select value={well} onChange={e => setWell(e.target.value)}>{wellDates.map(r => <option key={id(r)} value={id(r)}>{r.date}</option>)}</select></label>
          <button onClick={() => step(-1)} disabled={!rows.length || pos === 0}>◀ предыдущая</button>
          <button onClick={() => step(1)} disabled={!rows.length || pos === rows.length - 1}>следующая ▶</button>
          <span className="muted small">{pos >= 0 ? `${pos + 1} из ${rows.length} в текущем списке` : 'выбранного исследования нет в текущем списке'}</span>
        </div>}
        {stepInfo && <p className="muted small" style={{ margin: '4px 0 8px' }}>{stepInfo}</p>}
        <div className="adapt-charts">
          {curve && <div><ChartView chart={curve} excludeMode={false} onExclude={() => {}} /></div>}
          {dyn && <div><ChartView chart={dyn} excludeMode={false} onExclude={() => {}} /></div>}
        </div>
        {cur && !dyn && <p className="muted small">Динамика WPIMULT строится, когда у скважины не меньше двух исследований с расчётом.</p>}

        <h3>Общие графики по всем скважинам</h3>
        <div className="adapt-charts">
          {hist && <div><ChartView chart={hist} excludeMode={false} onExclude={() => {}} /></div>}
          {r2c && <div><ChartView chart={r2c} excludeMode={false} onExclude={() => {}} /></div>}
        </div>

        {view.groups.length > 0 && <>
          <h3>По группам: суммарный дебит при депрессиях ГДИ, тыс. м³/сут</h3>
          <div className="scroll" style={{ maxHeight: 260 }}><table className="raw"><thead><tr><th>Группа</th><th>Скважин</th><th>ГДИ</th><th>Модель до</th><th>Ошибка до, %</th><th>Модель после</th><th>Ошибка после, %</th></tr></thead>
            <tbody>{view.groups.map(g => <tr key={g.group}><td>{g.group}</td><td>{g.wells}</td><td>{fmt(g.q_gdi, 1)}</td><td>{fmt(g.q_before, 1)}</td><td>{fmt(g.err_before, 1)}</td><td>{fmt(g.q_after, 1)}</td><td>{fmt(g.err_after, 1)}</td></tr>)}</tbody></table></div>
        </>}
      </>}
    </section>
  )
}
