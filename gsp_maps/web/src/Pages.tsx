import { useEffect, useMemo, useState } from 'react'
import Chart from './Chart'
import { exportExcel, getSummary, openFolder, pickPath, saveConfig, type AppState, type GspData, type SummaryData } from './api'
import { Tables } from '../../../pxg_core/web-ui/table/Tables'
import { tableOf, type ColumnSpec } from '../../../pxg_core/web-ui/table/tableBuild'
import { SeasonCalc, WATER, fmt1, fmtDay, fmtTh, waterByWell } from './model'

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
  return (
    <section className="card table-card">
      {tabs}
      <p className="muted">{g.gsp} · {kind}{season === '*' ? ', все сезоны' : ' ' + season}. Столбцы те же, что на листах «{season === '*' ? 'Сводка все сезоны' : 'Отбор/Закачка <сезон>'}» старого Excel: время работы, давление, замеры воды.</p>
      {err && <div className="note warning">{err}</div>}
      {!data && !err && <p className="muted">Считаю…</p>}
      {data && !data.rows.length && <p className="muted">За выбранный сезон нет данных.</p>}
      {data && data.rows.length > 0 && <Tables scope="gsp-summary" tables={[tableOf('summary', 'Сводка', data.columns.map((c, i) => {
          const num = data.rows.some(r => typeof r[i] === 'number')
          return [colLabel(c), num ? 'number' : 'text', num ? (/дней|Дней|Скважина|Замеров/.test(c) ? 0 : 1) : null] as ColumnSpec
        }), data.rows)]} />}
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
  const sorted = useMemo(() => [...rows].sort((p, q) => q.total - p.total), [rows])
  return (
    <section className="card table-card">
      {tabs}
      <p className="muted">{g.gsp} · {kind} {season} · {fmtDay(calc.days[a])} — {fmtDay(calc.days[b])}. Окно времени задаётся на странице «Карта».</p>
      <Tables scope="gsp-window" tables={[tableOf('window', 'Скважины окна времени',
        [['Скв.', 'text'], 'Направление', ['Накоплено, млн м³', 'number', 2], ['Средний, тыс. м³/сут', 'number', 1], ['Дней', 'number', 0], ['Доля, %', 'number', 1], ['Вода, л/ч', 'number', 0], ['ВФ', 'number', 1]],
        sorted.map(r => [String(r.w), r.dir, r.total / 1e6, r.mean / 1e3, r.days, r.share ? r.share * 100 : null, r.fl || null, r.wf || null]), '',
        [{ rows: sorted.flatMap((r, k) => (r.wf ? [k] : [])), columns: ['c7'], fill: '', font: WATER.slice(1), border: '' }])]} />
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
  const sorted = useMemo(() => [...g.trends].sort((p, q) => q.Тренд_расхода - p.Тренд_расхода), [g.trends])
  if (!g.trends.length) return <section className="card"><p className="muted">Тренды считаются по скважинам, у которых есть минимум два сезона отбора.</p></section>
  const ordered = [...g.trends].sort((p, q) => q.Тренд_расхода - p.Тренд_расхода)
  return (
    <section className="card table-card">
      <h3>Тренд расхода по скважинам, тыс. м³/сут за сезон</h3>
      <Chart mode="bars" labels={ordered.map(r => String(r.Скважина))} fmt={v => fmtTh(v)} unit="тыс. м³/сут за сезон" height={220} label="Тренд расхода по скважинам"
        barColor={j => (ordered[j].Тренд_расхода < 0 ? '#d55e00' : '#149ba5')}
        series={[{ key: 't', label: 'Тренд расхода', color: '#149ba5', y: ordered.map(r => r.Тренд_расхода) }]} />
      <p className="muted">Наклон прямой по среднему суточному расходу в сезонах отбора: сколько тыс. м³/сут скважина добавляет (или теряет) за сезон. Водный фактор — по среднему за сезон.</p>
      <Tables scope="gsp-trends" tables={[tableOf('trends', 'Тренды по скважинам',
        [['Скв.', 'text'], 'Направление', ['Средний расход, тыс. м³/сут', 'number', 1], ['Тренд расхода, тыс. м³/сут за сезон', 'number', 1], ['Тренд воды (ВФ за сезон)', 'number', 1]],
        sorted.map(r => [String(r.Скважина), r.Направление, r.Средний_расход / 1e3, r.Тренд_расхода / 1e3, r.Тренд_воды || null]))]} />
    </section>
  )
}

export function DataPage({ app, setApp, mode, setMode, gsp, onReload }: { app: AppState; setApp: (s: AppState) => void; mode: string; setMode: (m: 'auto' | 'grid' | 'xy') => void; gsp: string; onReload: () => void }) {
  const [paths, setPaths] = useState<Record<string, string>>(app.paths)
  const [results, setResults] = useState(app.resultsDir)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setMsg(null); try { await fn() } catch (e) { setMsg({ ok: false, text: String((e as Error).message || e) }) } finally { setBusy(false) } }
  const pick = (id: string, kind: 'file' | 'folder') => run(async () => {
    const r = await pickPath(kind, paths[id] || '')
    if (r.path) setPaths(p => ({ ...p, [id]: r.path }))
  })
  const { atlas } = app
  const project = paths.atlas_project || atlas.project
  const missing = app.checks.filter(c => !c.ok).length
  const load = (next: Record<string, string>) => run(async () => { const s = await saveConfig(next, results); setApp(s); setPaths(s.paths); onReload(); setMsg({ ok: true, text: 'Данные читаются из проекта Атласа.' }) })
  return (
    <>
      <section className="card param-card">
        <h2>Данные из Газового Атласа</h2>
        <p className="muted">Расходы, периоды работы объекта, давления по группам и объекту, вынос воды по скважинам, координаты, альтитуды и перфорации берутся из проекта Атласа. Здесь ничего не загружается: недостающее добавьте в Атласе («Источники» или «Импорт данных»), потом нажмите «Обновить».</p>
        <div className="fields">
          <div className="field wide"><span className="field-label">Проект Атласа</span>
            <div className="path-row">
              <select value={project} onChange={e => setPaths(p => ({ ...p, atlas_project: e.target.value }))} aria-label="Проект Атласа" disabled={!atlas.projects.length}>
                {!atlas.projects.length && <option value="">проектов не найдено</option>}
                {atlas.projects.map(p => <option key={p.id} value={p.id}>{p.name}{p.demo ? ' (демонстрация)' : ''} · {p.updated.slice(0, 10)} · расходов: {p.tables.production ?? 0}</option>)}
              </select>
              <button type="button" className="primary" disabled={busy || !project} onClick={() => load({ ...paths, atlas_project: project })}>Обновить из Атласа</button>
              {atlas.url && <a className="quiet" href={atlas.url} target="_blank" rel="noreferrer">Открыть Атлас</a>}
            </div>
            <span className="hint">{atlas.chosen ? 'Проект выбран вами.' : 'Предложен самый свежий проект с расходами: подтвердите или выберите другой.'}</span></div>
          <div className="field wide"><span className="field-label">Хранилище Атласа (папка storage)</span>
            <div className="path-row"><input value={paths.atlas_storage ?? ''} onChange={e => setPaths(p => ({ ...p, atlas_storage: e.target.value }))} placeholder={atlas.fromEnv ? atlas.storage + ' (задано запуском)' : 'не задано'} />
              <button type="button" className="quiet" disabled={busy} onClick={() => pick('atlas_storage', 'folder')}>Папка…</button></div>
            <span className="hint">Обычно задаётся единым запуском (GAS_ATLAS_STORAGE); вручную нужно только при отдельном запуске Карт.</span></div>
        </div>
      </section>
      <section className="card">
        <h2>Что загружено в проекте Атласа</h2>
        {app.state !== 'ready' && app.log.length > 0 && <pre className="log">{app.log.join('\n')}</pre>}
        <ul className="checklist">{app.checks.map(c => (
          <li key={c.id} className={c.ok ? 'ok' : 'bad'}><span aria-hidden="true">{c.ok ? '✓' : '✗'}</span> <b>{c.label}</b> <span className="muted">· {c.info}</span></li>))}</ul>
        {missing > 0 && app.atlas.projects.length > 0 && <p className="muted">Не хватает {missing}: загрузите в Атласе, в «Источниках» файл получит роль автоматически (расходы, давления «Пересчёт_давлений», «БД замеров воды», «Глубины_перфораций», файл координат XY).</p>}
        <p className="muted">Периоды работы объекта выводятся из суточных объёмов («БД по учету газа» или расходы по скважинам) и показаны как подсказка.</p>
      </section>
      <section className="card param-card">
        <h2>Папка для результатов и запасная карта-сетка</h2>
        <div className="fields">
          <div className="field wide"><span className="field-label">Карта-сетка скважин (Excel), необязательно</span>
            <div className="path-row"><input value={paths.map || ''} onChange={e => setPaths(p => ({ ...p, map: e.target.value }))} placeholder="не задан" />
              <button type="button" className="quiet" disabled={busy} onClick={() => pick('map', 'file')}>Файл…</button></div>
            <span className="hint">Нужна только скважинам без координат в Атласе: лист с названием ГСП, номера скважин в ячейках.</span></div>
          <div className="field wide"><span className="field-label">Многоугольники (файл X Y), необязательно</span>
            <div className="path-row"><input value={paths.polygons || ''} onChange={e => setPaths(p => ({ ...p, polygons: e.target.value }))} placeholder="не заданы" />
              <button type="button" className="quiet" disabled={busy} onClick={() => pick('polygons', 'file')}>Файл…</button></div>
            <span className="hint">Строки «имя X Y» или «X Y»; пустая строка отделяет контуры. Оформление задаётся в «Вид карты».</span></div>
          <div className="field wide"><span className="field-label">Фото или растр на фон, необязательно</span>
            <div className="path-row"><input value={paths.background || ''} onChange={e => setPaths(p => ({ ...p, background: e.target.value }))} placeholder="не задан" />
              <button type="button" className="quiet" disabled={busy} onClick={() => pick('background', 'file')}>Файл…</button></div>
            <span className="hint">Картинка (png, jpg, gif, bmp, webp) под скважинами; привязка по трём точкам — в «Вид карты → Фон».</span></div>
          <div className="field wide"><span className="field-label">Папка для результатов (Excel, картинки)</span>
            <div className="path-row"><input value={results} onChange={e => setResults(e.target.value)} />
              <button type="button" className="quiet" disabled={busy} onClick={() => run(async () => { const r = await pickPath('folder', results); if (r.path) setResults(r.path) })}>Выбрать…</button></div></div>
        </div>
        <div className="actions">
          <button type="button" className="primary" disabled={busy} onClick={() => load({ ...paths, atlas_project: paths.atlas_project || '' })}>Сохранить и загрузить</button>
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
