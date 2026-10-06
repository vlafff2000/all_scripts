import { useEffect, useMemo, useState } from 'react'
import Chart from './Chart'
import { exportExcel, getSummary, openFolder, pickPath, saveConfig, scanFolder, type AppState, type GspData, type SummaryData } from './api'
import { SeasonCalc, WATER, fmt1, fmtDay, fmtInt, fmtMln, fmtPct, fmtTh, waterByWell } from './model'

type SortKey = string
function useSort<T>(rows: T[], init: SortKey, get: (r: T, k: SortKey) => number | string) {
  const [key, setKey] = useState(init), [desc, setDesc] = useState(true)
  const sorted = useMemo(() => [...rows].sort((p, q) => {
    const x = get(p, key), y = get(q, key)
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'ru')
    return desc ? -c : c
  }), [rows, key, desc, get])
  const th = (k: SortKey, label: string, num = true) => (
    <th className={num ? 'number sortable' : 'sortable'} aria-sort={key === k ? (desc ? 'descending' : 'ascending') : 'none'}>
      <button type="button" onClick={() => (key === k ? setDesc(!desc) : (setKey(k), setDesc(true)))}>{label}{key === k ? (desc ? ' ↓' : ' ↑') : ''}</button></th>)
  return { sorted, th }
}

export function TablePage({ g, calc, kind, season, a, b, mode }: { g: GspData; calc: SeasonCalc; kind: string; season: string; a: number; b: number; mode: string }) {
  const [view, setView] = useState<'window' | 'season' | 'all'>('window')
  const tabs = (
    <div className="segmented" role="radiogroup" aria-label="Что показывать">
      {([['window', 'Окно времени'], ['season', 'Сезон, все столбцы'], ['all', 'Все сезоны']] as const).map(([k, t]) => <button key={k} type="button" role="radio" aria-checked={view === k} onClick={() => setView(k)}>{t}</button>)}
    </div>)
  if (view !== 'window') return <SummaryTable g={g} kind={kind} season={view === 'all' ? '*' : season} mode={mode} tabs={tabs} />
  return <WindowTable g={g} calc={calc} kind={kind} season={season} a={a} b={b} tabs={tabs} />
}

const COL_LABEL: Record<string, string> = {
  Скважина: 'Скв.', Тип: 'Вид', Сезон: 'Сезон', Накопленный_расход_газа: 'Накоплено, м³', Накопленный_расход_газа_закачка: 'Накоплено, м³', Средний_суточный_расход: 'Средний, м³/сут',
  Средний_суточный_расход_закачка: 'Средний, м³/сут', Количество_дней: 'Дней с расходом', Количество_дней_закачка: 'Дней с расходом', Суммарное_время_работы: 'Время работы, ч',
  Суммарное_время_работы_закачка: 'Время работы, ч', Среднее_время_работы: 'Среднее время работы, ч/сут', Дней_с_простоем: 'Дней простоя (часы есть, расхода нет)',
  Сред_давл_ГСП_бар: 'Давление ГСП, бар', Сред_давл_Объект_бар: 'Давление объекта, бар', Направление: 'Направление',
}
const colLabel = (c: string) => COL_LABEL[c] || (c.startsWith('Водный_фактор_') ? 'ВФ ' + c.slice(14) : c.startsWith('Расход_воды_') ? 'Вода ' + c.slice(12).replace(/_лч$/, '') + ', л/ч' : c.replace(/_/g, ' '))

function SummaryTable({ g, kind, season, mode, tabs }: { g: GspData; kind: string; season: string; mode: string; tabs: React.ReactNode }) {
  const [data, setData] = useState<SummaryData | null>(null), [err, setErr] = useState('')
  useEffect(() => {
    let live = true
    setData(null); setErr('')
    getSummary(g.gsp, kind, season, mode).then(d => live && setData(d)).catch(e => live && setErr(String(e.message || e)))
    return () => { live = false }
  }, [g.gsp, kind, season, mode])
  const [key, setKey] = useState<number>(-1), [desc, setDesc] = useState(true)
  const rows = useMemo(() => {
    if (!data) return []
    if (key < 0) return data.rows
    return [...data.rows].sort((p, q) => {
      const x = p[key], y = q[key], c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? ''), 'ru')
      return desc ? -c : c
    })
  }, [data, key, desc])
  const fmtCell = (v: string | number | null, c: string) => v === null || v === '' ? '—' : typeof v === 'number' ? (/дней|Дней|Скважина|Замеров/.test(c) ? fmtInt(v) : fmt1(v)) : v
  return (
    <section className="card table-card">
      {tabs}
      <p className="muted">{g.gsp} · {kind}{season === '*' ? ', все сезоны' : ' ' + season}. Столбцы те же, что на листах «{season === '*' ? 'Сводка все сезоны' : 'Отбор/Закачка <сезон>'}» старого Excel: время работы, давление, замеры воды.</p>
      {err && <div className="note warning">{err}</div>}
      {!data && !err && <p className="muted">Считаю…</p>}
      {data && !data.rows.length && <p className="muted">За выбранный сезон нет данных.</p>}
      {data && data.rows.length > 0 && <div className="scroll"><table className="data">
        <thead><tr>{data.columns.map((c, i) => (
          <th key={c} className={i > 1 ? 'number sortable' : 'sortable'} aria-sort={key === i ? (desc ? 'descending' : 'ascending') : 'none'}>
            <button type="button" onClick={() => (key === i ? setDesc(!desc) : (setKey(i), setDesc(true)))}>{colLabel(c)}{key === i ? (desc ? ' ↓' : ' ↑') : ''}</button></th>))}</tr></thead>
        <tbody>{rows.map((r, n) => <tr key={n}>{r.map((v, i) => <td key={i} className={typeof v === 'number' ? 'number' : ''}>{i === 0 ? <b>{fmtCell(v, data.columns[i])}</b> : fmtCell(v, data.columns[i])}</td>)}</tr>)}</tbody>
      </table></div>}
    </section>
  )
}

function WindowTable({ g, calc, kind, season, a, b, tabs }: { g: GspData; calc: SeasonCalc; kind: string; season: string; a: number; b: number; tabs: React.ReactNode }) {
  const water = useMemo(() => waterByWell(g.water, kind, season, calc.days[a], calc.days[b]), [g.water, kind, season, calc, a, b])
  const rows = useMemo(() => {
    const out = calc.wells.map((w, i) => ({ w, dir: g.layout.wells[String(w)]?.dir || '', ...calc.stat(i, a, b), wf: Math.max(0, ...(water.get(w) || []).map(x => x.factor ?? 0)), fl: Math.max(0, ...(water.get(w) || []).map(x => x.flow ?? 0)) }))
    const sum = out.reduce((s, r) => s + Math.max(0, r.total), 0)
    return out.map(r => ({ ...r, share: sum > 0 && r.total > 0 ? r.total / sum : 0 }))
  }, [calc, g, a, b, water])
  const get = useMemo(() => (r: (typeof rows)[number], k: string) => (r as unknown as Record<string, number | string>)[k], [])
  const { sorted, th } = useSort(rows, 'total', get)
  const mx = Math.max(1, ...rows.map(r => r.total))
  return (
    <section className="card table-card">
      {tabs}
      <p className="muted">{g.gsp} · {kind} {season} · {fmtDay(calc.days[a])} — {fmtDay(calc.days[b])}. Окно времени задаётся на странице «Карта».</p>
      <div className="scroll"><table className="data">
        <thead><tr>{th('w', 'Скв.')}{th('dir', 'Направление', false)}{th('total', 'Накоплено, млн м³')}{th('mean', 'Средний, м³/сут')}{th('days', 'Дней')}{th('share', 'Доля')}{th('fl', 'Вода, л/ч')}{th('wf', 'ВФ')}</tr></thead>
        <tbody>{sorted.map(r => (
          <tr key={r.w}><td className="number"><b>{r.w}</b></td><td>{r.dir}</td>
            <td className="number barcell"><i style={{ width: Math.max(0, r.total / mx) * 100 + '%' }} /><span>{fmtMln(r.total)}</span></td>
            <td className="number">{fmtTh(r.mean)}</td><td className="number">{r.days}</td><td className="number">{r.share ? fmtPct(r.share) : '—'}</td>
            <td className="number">{r.fl ? fmtInt(r.fl) : '—'}</td><td className="number" style={{ color: r.wf ? WATER : undefined }}>{r.wf ? fmt1(r.wf) : '—'}</td></tr>))}</tbody>
      </table></div>
    </section>
  )
}

export function PressurePage({ g, kind, season, range }: { g: GspData; kind: string; season: string; range: [number, number] }) {
  const sers = (['gsp', 'obj'] as const).map(k => ({ k, s: g.pressure[k] })).filter(x => x.s)
  const fl = g.gspFlow
  if (!sers.length && !fl.days.length) return <section className="card"><p className="muted">Файлы давления не заданы. Добавьте их в разделе «Данные»: «Давление по ГСП» и «Давление по объекту».</p></section>
  const allDays = [...sers.flatMap(x => x.s!.days), ...fl.days]
  const xRange: [number, number] = [Math.min(...allDays), Math.max(...allDays)]
  const colors = { gsp: '#149ba5', obj: '#d55e00' }
  const labels = { gsp: 'Давление по ГСП', obj: 'Давление по объекту' }
  return (
    <section className="card">
      <div className="p-legend">{sers.length === 0 && <span className="muted">Файлы давления не заданы — показан только расход ГСП.</span>}{sers.map(sr => <span key={sr.k}><i style={{ background: colors[sr.k] }} />{labels[sr.k]}</span>)}
        <span><i className="win" />выбранный сезон</span></div>
      {sers.length > 0 && <Chart mode="lines" group="gsp-pressure" yScale xRange={xRange} win={range} fmt={v => fmt1(v)} unit="бар" height={300} label="Давление по ГСП и по объекту"
        series={sers.map(sr => ({ key: sr.k, label: labels[sr.k], color: colors[sr.k], x: sr.s!.days, y: sr.s!.bar }))} />}
      {fl.days.length > 0 && <>
        <h3>Суточный расход ГСП (отбор и закачка вместе), тыс. м³/сут</h3>
        <Chart mode="lines" group="gsp-pressure" xRange={xRange} win={range} gapDays={0} fmt={v => fmt1(v)} unit="тыс. м³/сут" height={190} label="Суточный расход ГСП"
          series={[{ key: 'flow', label: 'Расход ГСП', color: '#e63946', area: true, x: fl.days, y: fl.bar.map(v => v / 1000) }]} />
      </>}
      <h3>Средние давления по сезонам · {kind} {season}</h3>
      <p>{(['gsp', 'obj'] as const).map(k => g.seasonPressure[k][kind + '|' + season] !== undefined && <span key={k} className="pill"><i style={{ background: colors[k] }} />{labels[k]}: <b>{fmt1(g.seasonPressure[k][kind + '|' + season])} бар</b></span>)}
        {!g.seasonPressure.gsp[kind + '|' + season] && !g.seasonPressure.obj[kind + '|' + season] && <span className="muted">за выбранный сезон замеров нет</span>}</p>
    </section>
  )
}

export function TrendsPage({ g }: { g: GspData }) {
  const get = useMemo(() => (r: GspData['trends'][number], k: string) => (r as unknown as Record<string, number | string>)[k], [])
  const { sorted, th } = useSort(g.trends, 'Тренд_расхода', get)
  if (!g.trends.length) return <section className="card"><p className="muted">Тренды считаются по скважинам, у которых есть минимум два сезона отбора.</p></section>
  const mx = Math.max(1, ...g.trends.map(r => Math.abs(r.Тренд_расхода)))
  return (
    <section className="card table-card">
      <p className="muted">Наклон прямой по среднему суточному расходу в сезонах отбора: сколько тыс. м³/сут скважина добавляет (или теряет) за сезон. Водный фактор — по среднему за сезон.</p>
      <div className="scroll"><table className="data">
        <thead><tr>{th('Скважина', 'Скв.')}{th('Направление', 'Направление', false)}{th('Средний_расход', 'Средний расход, тыс. м³/сут')}{th('Тренд_расхода', 'Тренд расхода, тыс. м³/сут за сезон')}{th('Тренд_воды', 'Тренд воды (ВФ за сезон)')}</tr></thead>
        <tbody>{sorted.map(r => (
          <tr key={r.Скважина}><td className="number"><b>{r.Скважина}</b></td><td>{r.Направление}</td><td className="number">{fmtTh(r.Средний_расход)}</td>
            <td className={'number barcell ' + (r.Тренд_расхода < 0 ? 'neg' : '')}><i style={{ width: Math.abs(r.Тренд_расхода) / mx * 100 + '%' }} /><span>{r.Тренд_расхода > 0 ? '+' : ''}{fmtTh(r.Тренд_расхода)}</span></td>
            <td className="number">{r.Тренд_воды ? (r.Тренд_воды > 0 ? '+' : '') + fmt1(r.Тренд_воды) : '—'}</td></tr>))}</tbody>
      </table></div>
    </section>
  )
}

const FIELDS: { id: string; label: string; hint: string; kind: 'file' | 'folder' | 'files'; area?: boolean }[] = [
  { id: 'db', label: 'База расходов', hint: 'БД_расходы.xlsx: листы «Отборы» и «Закачка»', kind: 'file' },
  { id: 'map', label: 'Карта-сетка скважин (Excel)', hint: 'лист с названием ГСП, номера скважин в ячейках', kind: 'file' },
  { id: 'xy', label: 'Координаты X, Y из tNavigator', hint: 'текст или Excel: скважина, X, Y (также траектории WELLTRACK)', kind: 'file' },
  { id: 'periods', label: 'Периоды работы объекта', hint: 'строки «08.04.2012 inj» (inj, prod, none)', kind: 'file' },
  { id: 'water', label: 'Замеры выноса воды', hint: 'папка с файлами «… март 2016.xlsx» или список файлов', kind: 'folder', area: true },
  { id: 'press_gsp', label: 'Давление по ГСП', hint: 'строки «520 22.11.2024 95,42»', kind: 'file' },
  { id: 'press_obj', label: 'Давление по объекту', hint: 'строки «02.08.2006 94,7»', kind: 'file' },
  { id: 'depths', label: 'Глубины перфораций и альтитуды', hint: 'Глубины_перфораций.xlsx', kind: 'file' },
]

export function DataPage({ app, setApp, mode, setMode, gsp, onReload }: { app: AppState; setApp: (s: AppState) => void; mode: string; setMode: (m: 'auto' | 'grid' | 'xy') => void; gsp: string; onReload: () => void }) {
  const [paths, setPaths] = useState<Record<string, string>>(app.paths)
  const [folder, setFolder] = useState('')
  const [results, setResults] = useState(app.resultsDir)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setMsg(null); try { await fn() } catch (e) { setMsg({ ok: false, text: String((e as Error).message || e) }) } finally { setBusy(false) } }
  const pick = (id: string, kind: 'file' | 'folder' | 'files') => run(async () => {
    const r = await pickPath(kind, paths[id] || '')
    if (r.path) setPaths(p => ({ ...p, [id]: r.path }))
  })
  const status = (id: string) => app.checks.find(c => c.id === id)
  return (
    <>
      <section className="card">
        <h2>Папка с данными</h2>
        <p className="muted">Укажите папку: приложение само найдёт БД_расходы.xlsx, карту, периоды, давление, глубины, папку с замерами воды и файл координат (в имени «xy», «координаты» или «tnav»).</p>
        <div className="path-row">
          <input value={folder} onChange={e => setFolder(e.target.value)} placeholder="Путь к папке" aria-label="Папка с данными" />
          <button type="button" className="quiet" disabled={busy} onClick={() => run(async () => { const r = await pickPath('folder', folder); if (r.path) setFolder(r.path) })}>Выбрать…</button>
          <button type="button" className="primary" disabled={busy || !folder} onClick={() => run(async () => { const s = await scanFolder(folder); setApp(s); setPaths(s.paths); setMsg({ ok: true, text: 'Файлы найдены и подключены.' }) })}>Найти файлы</button>
        </div>
      </section>
      <section className="card param-card">
        <h2>Файлы</h2>
        <div className="fields">{FIELDS.map(f => {
          const st = status(f.id)
          return (
            <div key={f.id} className={'field wide' + (st && paths[f.id] && !st.ok ? ' invalid' : '')}>
              <span className="field-label">{f.label}</span>
              <div className="path-row">
                {f.area ? <textarea rows={1} value={paths[f.id] || ''} onChange={e => setPaths(p => ({ ...p, [f.id]: e.target.value }))} placeholder="папка или несколько файлов, по одному в строке" />
                  : <input value={paths[f.id] || ''} onChange={e => setPaths(p => ({ ...p, [f.id]: e.target.value }))} placeholder="не задан" />}
                <button type="button" className="quiet" disabled={busy} onClick={() => pick(f.id, f.kind)}>{f.kind === 'folder' ? 'Папка…' : 'Файл…'}</button>
                {f.area && <button type="button" className="quiet" disabled={busy} onClick={() => pick(f.id, 'files')}>Файлы…</button>}
              </div>
              <span className="hint">{f.hint}{st ? ' · ' : ''}{st && <span className={st.ok ? 'ok' : 'bad'}>{st.ok ? '✓ ' : paths[f.id] ? '✗ ' : ''}{st.info}</span>}</span>
            </div>)
        })}</div>
        <div className="field wide"><span className="field-label">Папка для результатов (Excel, картинки)</span>
          <div className="path-row"><input value={results} onChange={e => setResults(e.target.value)} />
            <button type="button" className="quiet" disabled={busy} onClick={() => run(async () => { const r = await pickPath('folder', results); if (r.path) setResults(r.path) })}>Выбрать…</button></div></div>
        <div className="actions">
          <button type="button" className="primary" disabled={busy} onClick={() => run(async () => { const s = await saveConfig(paths, results); setApp(s); onReload(); setMsg({ ok: true, text: 'Сохранено.' }) })}>Сохранить и загрузить</button>
          {msg && <span className={msg.ok ? 'ok' : 'bad'} role="status">{msg.text}</span>}
        </div>
      </section>
      <section className="card">
        <h2>Положение скважин</h2>
        <p className="muted">«Авто» берёт координаты из tNavigator там, где они есть, а остальные скважины ставит по карте-сетке, пересчитав её в те же координаты по общим скважинам. Направления (С, СВ, В…) считаются от центра карты.</p>
        <div className="segmented wide-seg" role="radiogroup" aria-label="Положение скважин">
          {([['auto', 'Авто (XY + сетка)'], ['xy', 'Только XY'], ['grid', 'Только сетка']] as const).map(([k, l]) => <button key={k} type="button" role="radio" aria-checked={mode === k} onClick={() => setMode(k)}>{l}</button>)}
        </div>
      </section>
      <section className="card">
        <h2>Выгрузка</h2>
        <div className="actions">
          <button type="button" className="quiet" disabled={busy || !gsp} onClick={() => run(async () => { const r = await exportExcel(gsp, mode); setMsg({ ok: true, text: 'Сохранено: ' + r.path }) })}>Excel по {gsp || 'ГСП'}</button>
          <button type="button" className="quiet" onClick={() => run(async () => { await openFolder() })}>Открыть папку результатов</button>
        </div>
        <p className="muted">В Excel: итоги сезонов отбора и закачки по скважинам, тренды, вода, давление, положения и глубины. PNG карты сохраняется кнопкой на странице «Карта».</p>
      </section>
    </>
  )
}
