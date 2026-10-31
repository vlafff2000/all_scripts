import { useEffect, useMemo, useState } from 'react'
import PageHead from './PageHead'
import HistModel from './HistModel'
import ModelCompare from './ModelCompare'
import ModelDynamics from './ModelDynamics'
import { IndicatorRow, ModelsView, ResultsInfo, getIndicators, getModels, getResultSeries, getWellGwc, WellGwcRow, getResults, getResultsReport, pickFile, pickFolder, setModelFolders, setModelSelection } from './api'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import { Tables } from '../../../pxg_core/web-ui/table/Tables'
import { tableOf } from '../../../pxg_core/web-ui/table/tableBuild'

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

/** Последние две части пути папки: полный путь — во всплывающей подсказке. */
const tail = (path: string) => path.split(/[\\/]/).filter(Boolean).slice(-2).join('/')

export default function Results() {
  const [view, setView] = useState<ModelsView>({ folders: [], models: [] })
  const [infos, setInfos] = useState<Record<string, ResultsInfo>>({})
  const [sg, setSg] = useState('0.01')
  const [date, setDate] = useState('')
  const [ind, setInd] = useState<Record<string, IndicatorRow[]>>({})
  const [notes, setNotes] = useState<string[]>([])
  const [kw, setKw] = useState('WBHP')
  const [wells, setWells] = useState('')
  const [pr, setPr] = useState<Line[]>([])
  const [sgr, setSgr] = useState('0.01')
  const [gw, setGw] = useState('')
  const [gwDate, setGwDate] = useState('')
  const [gwRows, setGwRows] = useState<Record<string, WellGwcRow[]>>({})
  const [gwNotes, setGwNotes] = useState<string[]>([])
  const [rpPath, setRpPath] = useState('')
  const [rpText, setRpText] = useState('')
  const [rpName, setRpName] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const models = view.models
  const chosen = models.filter(m => m.selected).map(m => m.id)
  const chosenKey = chosen.join('|')
  // подпись модели: имя и хвост папки (одинаковые имена в разных папках различимы)
  const label = (id: string) => { const m = models.find(x => x.id === id); return m ? m.name + ' (' + tail(m.folder) + ')' : id }

  useEffect(() => {
    getModels().then(setView).catch(e => setMsg((e as Error).message))
  }, [])
  useEffect(() => {
    let live = true
    chosen.forEach(id => { if (!infos[id]) getResults(id).then(r => live && setInfos(c => ({ ...c, [id]: r }))).catch(e => live && setMsg(id + ': ' + (e as Error).message)) })
    return () => { live = false }
  }, [chosenKey]) // eslint-disable-line

  const guard = async (f: () => Promise<void>) => { setBusy(true); setMsg(''); try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) } }
  const addFolder = () => guard(async () => {
    const f = await pickFolder(view.folders[view.folders.length - 1] || '')
    if (f) setView(await setModelFolders([...view.folders.filter(x => x !== f), f]))
  })
  const dropFolder = (f: string) => guard(async () => setView(await setModelFolders(view.folders.filter(x => x !== f))))
  const toggle = (id: string) => guard(async () => setView(await setModelSelection(chosen.includes(id) ? chosen.filter(x => x !== id) : [...chosen, id])))

  const calc = () => guard(async () => {
    const out: Record<string, IndicatorRow[]> = {}
    const all: string[] = []
    for (const n of chosen) { const r = await getIndicators(n, sg, date ? [date] : []); out[n] = r.rows; r.notes.forEach(x => all.push(label(n) + ': ' + x)) }
    setInd(out); setNotes(all)
  })
  const press = () => guard(async () => {
    const lines: Line[] = []
    for (const n of chosen) {
      const r = await getResultSeries(n, kw, wells.split(/[;,|]/).map(x => x.trim()).filter(Boolean))
      Object.entries(r.series).forEach(([w, s]) => lines.push({ label: label(n) + ' · ' + w, pts: s.dates.map((d, i) => [d, s.values[i]] as [string, number]) }))
    }
    setPr(lines)
  })

  const gwcWells = () => guard(async () => {
    const out: Record<string, WellGwcRow[]> = {}
    const all: string[] = []
    for (const n of chosen) {
      const r = await getWellGwc(n, sgr, gwDate ? [gwDate] : [], gw.split(/[;,|]/).map(x => x.trim()).filter(Boolean))
      out[n] = r.rows; r.notes.forEach(x => all.push(label(n) + ': ' + x))
    }
    setGwRows(out); setGwNotes(all)
  })
  const gwShown = chosen.filter(n => gwRows[n])
  const gwLines: Line[] = gwShown.flatMap(n => {
    const by: Record<string, WellGwcRow[]> = {}
    gwRows[n].forEach(r => { if (r.interp_top_down !== null) (by[r.well] = by[r.well] || []).push(r) })
    return Object.entries(by).slice(0, 20).map(([w, rs]) => ({ label: label(n) + ' · ' + w, pts: rs.map(r => [r.date, r.interp_top_down as number] as [string, number]) }))
  })

  const rpPick = () => guard(async () => { const r = await pickFile(rpPath); if (r.path) setRpPath(r.path) })
  const rpPickFolder = () => guard(async () => { const f = await pickFolder(rpPath); if (f) setRpPath(f) })
  const rpRun = (kind: 'model' | 'restart') => guard(async () => {
    const r = await getResultsReport(rpPath, kind)
    setRpText(r.text); setRpName((rpPath.split(/[\\/]/).pop() || 'расчёт').replace(/\.[^.]*$/, '') + (kind === 'model' ? '_model.txt' : '_keywords.txt'))
  })
  const rpSave = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([rpText + '\n'], { type: 'text/plain;charset=utf-8' })); a.download = rpName; a.click(); URL.revokeObjectURL(a.href)
  }

  const shown = chosen.filter(n => ind[n])
  const line = (f: (r: IndicatorRow) => number | null): Line[] => shown.map(n => ({ label: label(n), pts: ind[n].filter(r => f(r) !== null).map(r => [r.date, f(r) as number] as [string, number]) }))
  const last = (n: string) => ind[n][ind[n].length - 1]
  const vecs = Array.from(new Set(chosen.flatMap(n => (infos[n]?.vectors || []).map(v => v.keyword))))
  const vec = chosen.flatMap(n => infos[n]?.vectors || []).find(v => v.keyword === kw)
  // единица из сводки модели; давление в BARSA/BARSG — абсолютное/избыточное
  const unit = ({ BARSA: 'бар (абс.)', BARSG: 'бар (изб.)', PSIA: 'psi (абс.)', PSIG: 'psi (изб.)' } as Record<string, string>)[(vec?.unit || '').toUpperCase()] ?? (vec?.unit || '')

  return (
    <main className="workspace">
      <PageHead title="Результаты расчёта" lede="Привяжите результаты модели к сценариям и сравните их по показателям." />
      <section className="card">
        <h2>Модели с результатами</h2>
        <p className="muted small">Добавьте одну или несколько папок: программа найдёт модели во всех их подпапках (файлы EGRID, INIT, SMSPEC, UNSMRY, UNRST с одним именем).
          Отметьте модели, которые показывать в таблицах и графиках. Для показателей нужны EGRID, INIT и UNRST с SGAS, для давлений — SMSPEC и UNSMRY.</p>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {view.folders.map(f => <span key={f} className="small" title={f} style={{ marginRight: 12 }}>{tail(f)}{' '}
            <button disabled={busy} onClick={() => dropFolder(f)} aria-label={'Убрать папку ' + f}>×</button></span>)}
          <button disabled={busy} onClick={addFolder}>Добавить папку…</button>
        </div>
        {models.length === 0
          ? <p className="muted">{view.folders.length ? 'В выбранных папках моделей не найдено.' : 'Папки не добавлены.'}</p>
          : <div style={{ overflowX: 'auto' }}><table className="data-grid dense pick"><thead><tr><th></th><th>Модель</th><th>Папка</th><th>Период расчёта</th><th>Файлы</th></tr></thead>
            <tbody>{models.map(m => { const r = infos[m.id]; return <tr key={m.id}>
              <td><input type="checkbox" checked={m.selected} disabled={busy} onChange={() => toggle(m.id)} aria-label={'Показывать ' + m.name} /></td>
              <td>{m.name}</td>
              <td className="small" title={m.folder}>{tail(m.folder)}</td>
              <td>{r && r.start ? r.start + ' — ' + r.end + ' (' + r.steps + ' шагов)' : m.selected ? '—' : <span className="muted">отметьте модель</span>}</td>
              <td className="small">{m.files.join(', ')}{m.missing.length ? ' · нет: ' + m.missing.join(', ') : ''}{!m.summary ? ' · без сводки' : ''}</td></tr> })}</tbody></table></div>}
        {msg && <p className="note warn">{msg}</p>}
      </section>
      <section className="card">
        <h2>Описание расчёта</h2>
        <p className="muted small">Те же отчёты, что делали Opisat_model и Perechislit_UNRST: размеры сетки, свойства, вектора и даты сводки, шаги и ключевые слова рестарта.
          Укажите любой файл расчёта (.EGRID, .INIT, .SMSPEC, .UNSMRY, .UNRST) или папку: остальные файлы с тем же именем находятся сами.</p>
        <div className="row">
          <input style={{ width: 380 }} placeholder="путь к результатам расчёта" value={rpPath} onChange={e => setRpPath(e.target.value)} />
          <button disabled={busy} onClick={rpPick}>Выбрать файл…</button>
          <button disabled={busy} onClick={rpPickFolder}>Выбрать папку…</button>
          <button disabled={busy || !rpPath} onClick={() => rpRun('model')}>Описать расчёт</button>
          <button disabled={busy || !rpPath} onClick={() => rpRun('restart')}>Перечислить UNRST</button>
          {rpText && <button onClick={rpSave}>Сохранить отчёт .txt</button>}
        </div>
        {rpText && <pre className="small" style={{ maxHeight: 420, overflow: 'auto', whiteSpace: 'pre' }}>{rpText}</pre>}
      </section>
      <HistModel models={models.filter(m => m.selected)} />
      <ModelCompare models={models.filter(m => m.selected)} />
      <ModelDynamics models={models.filter(m => m.selected)} />
      {chosen.length > 0 && <section className="card">
        <h3>Показатели по выбранным моделям</h3>
        <div className="row">
          <span className="muted small">Порог Sg:</span><input style={{ width: 70 }} value={sg} onChange={e => setSg(e.target.value)} />
          <span className="muted small">Дата (пусто — все шаги):</span><input type="date" value={date} onChange={e => setDate(e.target.value)} />
          <button className="primary" disabled={busy} onClick={calc}>Посчитать</button>
        </div>
        {notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {shown.length > 0 && <>
          <Tables scope="sched-results-idx" tables={[tableOf('idx', 'Показатели по выбранным моделям',
            ['Модель', ['Дата', 'date'], ['Газонас. объём, м³ пор.', 'number', 0], ['ГВК мин, м', 'number', 1], ['ГВК среднее, м', 'number', 1], ['ГВК по площади, м', 'number', 1], ['ГВК макс, м', 'number', 1]],
            shown.map(n => { const r = last(n); return [label(n), r?.date ?? null, r?.gas_pore_volume ?? null, r?.gwc_min ?? null, r?.gwc_mean ?? null, r?.gwc_mean_area ?? null, r?.gwc_max ?? null] }))]} />
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
        <h3 style={{ marginTop: 16 }}>ГВК по скважинам</h3>
        <p className="muted small">Колонка ячеек (i, j) вскрытия скважины целиком; газ — Sg выше критической Sgr (SGCR из INIT, иначе число ниже).
          Два способа: «сверху вниз» (первый переход газ → вода от кровли газа) и «нижний газ» (под самой глубокой газовой ячейкой).
          Две глубины: по границе ячейки и по интерполяции Sg. Глубина — TVDSS, м (со знаком минус).</p>
        <div className="row">
          <span className="muted small">Sgr, если нет SGCR:</span><input style={{ width: 70 }} value={sgr} onChange={e => setSgr(e.target.value)} />
          <span className="muted small">Дата (пусто — все шаги):</span><input type="date" value={gwDate} onChange={e => setGwDate(e.target.value)} />
          <input style={{ width: 260 }} placeholder="скважины через запятую (пусто — все)" value={gw} onChange={e => setGw(e.target.value)} />
          <button className="primary" disabled={busy} onClick={gwcWells}>Посчитать ГВК</button>
        </div>
        {gwNotes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {gwShown.map(n => { const rs = gwRows[n]; const lastD = rs.reduce((m, r) => (r.date > m ? r.date : m), ''); const cur = rs.filter(r => r.date === lastD)
          return <div key={n} style={{ overflowX: 'auto' }}>
            <p className="muted small">{label(n)}: на {lastD}{rs.some(r => r.date !== lastD) ? ' (график — по всем шагам)' : ''}</p>
            <Tables scope="sched-results-gwc" tables={[tableOf('gwc-' + n, 'ГВК по скважинам: ' + label(n),
              ['Скважина', ['Колонн с газом', 'number', 0], ['Сверху вниз: граница, м', 'number', 1], ['Сверху вниз: интерполяция, м', 'number', 1], ['Нижний газ: граница, м', 'number', 1], ['Нижний газ: интерполяция, м', 'number', 1], 'Пометка'],
              cur.map(r => [r.well, r.columns, r.cell_top_down, r.interp_top_down, r.cell_lowest, r.interp_lowest,
                r.columns === 0 ? 'газа нет' : [r.torn ? 'разорванный контакт' : '', r.at_grid_edge ? 'газ до низа сетки' : ''].filter(Boolean).join(', ')]))]} />
          </div> })}
        <Plot lines={gwLines} unit="м, TVDSS" title="ГВК по скважинам (сверху вниз, интерполяция)" link="sched-results-g" />
      </section>}
    </main>
  )
}
