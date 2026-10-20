import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import PageHead from './PageHead'
import {
  adaptExportAll, adaptExportChart, adaptExportDocx, adaptExportOptions, adaptExportPreview, adaptExportZip, adaptRun, adaptRuns, getAdapt,
  type AdaptChartDefaults, type AdaptChartStyle, type AdaptExportBody, type AdaptExportError, type AdaptExportOptions, type AdaptLayout,
  type AdaptResultRow, type AdaptRun, type AdaptView,
} from './api'
import { lastAdaptRun, pref, usePref } from './prefs'

type Style = AdaptChartStyle
/** Всё, что задаёт выгрузку: вид графика, макет листа, подпись. Шаблон хранит именно это, список исследований - нет. */
interface Settings { style: Style; layout: AdaptLayout; caption: string; start: number; object: string }
type Filter = 'all' | 'problems' | 'bound'
const FILTERS: [Filter, string][] = [['all', 'все'], ['problems', 'с замечаниями'], ['bound', 'на границе']]
const presetStore = pref<Record<string, Settings>>('sched.export.presets', {})

/** Названия значений, которые приходят с сервера без подписей. Сами значения и их набор - из /api/adapt/export/options. */
const LABEL: Record<string, string> = {
  portrait: 'Книжная', landscape: 'Альбомная', fill: 'На всю ширину колонки', mm: 'Задать в мм',
  below: 'Под графиком', above: 'Над графиком', field: 'Подпись Word (поле «Рисунок», ссылки)', text: 'Обычный текст',
  center: 'По центру', left: 'Влево', right: 'Вправо', justify: 'По ширине', none: 'Нет', thin: 'Тонкая сетка',
  dp2: 'ΔP²', dp2q: 'ΔP²/Q', both: 'до и после адаптации', before: 'только до', after: 'только после',
  default: 'обычное', excel: 'как в Excel',
}
const lbl = (v: string) => LABEL[v] ?? v
const FIELD_HINT: Record<string, string> = {
  n: 'номер рисунка (поле Word, сквозной)', 'номер': 'то же, что {n}', 'скважина': 'номер скважины', 'дата': 'дата ГДИ, ДД.ММ.ГГГГ',
  'объект': 'поле «Объект» ниже', 'группа': 'группа скважины', 'режимов': 'число режимов', pi_mult: 'WPIMULT', r2: 'R² после адаптации', r2_old: 'R² до адаптации',
}

const id = (r: AdaptResultRow) => r.well + '|' + r.date
const hasCurves = (r: AdaptResultRow) => r.curve_q.some(v => v !== null)
const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
/** Порядок как в таблице шага 6: по скважинам (по номеру), внутри скважины - по дате. */
const sortRows = (rows: AdaptResultRow[]) => [...rows].sort((a, b) => a.well.localeCompare(b.well, 'ru', { numeric: true }) || (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
const matches = (r: AdaptResultRow, q: string) => !q || r.well.toLowerCase().includes(q) || r.date.includes(q)
const safe = (s: string) => s.replace(/[\\/:*?"<>|\s]+/g, '_')

/** Вкладка «Экспорт графиков»: индикаторные диаграммы адаптации по ГДИ в Word (таблица по макету), ZIP и файлы по одному. */
export default function AdaptExport() {
  const [opts, setOpts] = useState<AdaptExportOptions | null>(null)
  const [cfg, setCfg] = useState<Settings | null>(null)
  const [kit, setKit] = useState('')
  const [runs, setRuns] = useState<AdaptRun[]>([])
  const [view, setView] = useState<AdaptView | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [cur, setCur] = useState('')
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [oneFmt, setOneFmt] = useState('png')
  const [zipFmts, setZipFmts] = useState<string[]>(['png'])
  const [page, setPage] = useState(1)
  const [shot, setShot] = useState<{ url: string; pages: number; page: number } | null>(null)
  const [shotBusy, setShotBusy] = useState(false)
  const [shotErr, setShotErr] = useState('')
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [note, setNote] = useState('')
  const [reasons, setReasons] = useState<AdaptExportError[]>([])
  const [presetName, setPresetName] = useState('')
  const [presetPick, setPresetPick] = useState('')
  const presets = usePref(presetStore)
  const shotSeq = useRef(0)
  const urlRef = useRef('')

  /** Открывает запуск: по умолчанию отмечены все исследования с кривыми. */
  const openRun = async (dir: string) => {
    setBusy('open'); setMsg(''); setNote('')
    try {
      const v = await adaptRun(dir)
      const list = sortRows(v.rows)
      setView(v)
      setChecked(new Set(list.filter(hasCurves).map(id)))
      setCur(list.find(hasCurves) ? id(list.find(hasCurves)!) : '')
      setPage(1); setQ(''); setFilter('all')
      lastAdaptRun.set(dir)
    } catch (e) { setMsg((e as Error).message) } finally { setBusy('') }
  }

  // Старт: значения по умолчанию с сервера, комплект и запуск (тот же, что открыт на шаге 6).
  useEffect(() => {
    let alive = true
    adaptExportOptions().then(o => {
      if (!alive) return
      setOpts(o)
      setCfg({ style: styleFrom(o.chart.defaults), layout: { ...o.layout.defaults }, caption: o.caption.default, start: 1, object: '' })
    }).catch(e => alive && setMsg((e as Error).message))
    getAdapt().then(async st => {
      if (!alive) return
      setKit(st.kit)
      const list = st.kit ? (await adaptRuns(st.kit)).runs : []
      if (!alive) return
      setRuns(list)
      const last = lastAdaptRun.get()
      const pick = list.find(r => r.dir === last && r.has_results) ?? list.find(r => r.has_results)
      if (pick) await openRun(pick.dir)
    }).catch(() => undefined)
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current) }, [])

  const rows = useMemo(() => sortRows(view?.rows ?? []), [view])
  const shownRows = useMemo(() => {
    const t = q.trim().toLowerCase()
    return rows.filter(r => (filter === 'all' || (filter === 'problems' ? !r.ok : r.at_bound)) && matches(r, t))
  }, [rows, filter, q])
  const chosen = useMemo(() => rows.filter(r => checked.has(id(r)) && hasCurves(r)).map(id), [rows, checked])
  const curRow = rows.find(r => id(r) === cur)
  const body: AdaptExportBody | null = view && cfg ? { run_dir: view.run_dir, ids: chosen, style: cfg.style, layout: cfg.layout, caption: cfg.caption, start: cfg.start, object: cfg.object } : null
  const bodyKey = JSON.stringify([body, page])

  // Предпросмотр листа: обновляется с задержкой после каждого изменения; устаревшие ответы отбрасываются.
  useEffect(() => {
    if (!body || !body.ids?.length) { setShot(null); setShotErr(''); setShotBusy(false); return }
    let alive = true
    const seq = ++shotSeq.current
    const timer = setTimeout(() => {
      setShotBusy(true)
      adaptExportPreview({ ...body, page }).then(r => {
        if (!alive || seq !== shotSeq.current) return
        if (urlRef.current) URL.revokeObjectURL(urlRef.current)
        urlRef.current = URL.createObjectURL(r.blob)
        setShot({ url: urlRef.current, pages: r.pages, page: r.page })
        setShotErr('')
        if (r.page !== page) setPage(r.page)
      }).catch(e => { if (alive && seq === shotSeq.current) { setShot(null); setShotErr((e as Error).message) } })
        .finally(() => { if (alive && seq === shotSeq.current) setShotBusy(false) })
    }, 450)
    return () => { alive = false; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bodyKey])

  if (!opts || !cfg) {
    return (
      <main className="workspace">
        <PageHead title="Экспорт графиков" lede="Индикаторные диаграммы адаптации по ГДИ: Word с макетом листа, ZIP и отдельные файлы." />
        {msg ? <p className="note warn">{msg}</p> : <p className="muted">Загрузка…</p>}
      </main>
    )
  }
  const L = cfg.layout
  const lim = (k: string) => opts.layout.limits[k]
  const bounds = (k: string) => ({ min: lim(k).min, max: lim(k).max })
  const F = opts.chart.format
  const fbounds = (k: string) => ({ min: F.limits[k][0], max: F.limits[k][1] })
  const resetFormat = () => setCfg(c => c && { ...c, style: { ...c.style, ...formatFrom(opts.chart.defaults) } })
  const setL = (k: string, v: string | number | boolean) => setCfg(c => c && { ...c, layout: { ...c.layout, [k]: v } })
  const setS = (p: Partial<Style>) => setCfg(c => c && { ...c, style: { ...c.style, ...p } })
  const setAll = (ids: string[]) => setChecked(new Set(ids))
  const toggle = (k: string, on: boolean) => setChecked(s => { const n = new Set(s); if (on) n.add(k); else n.delete(k); return n })
  const toggleShown = (on: boolean) => setChecked(s => { const n = new Set(s); shownRows.filter(hasCurves).forEach(r => (on ? n.add(id(r)) : n.delete(id(r)))); return n })
  const [pw, ph] = opts.layout.papers[String(L.paper)] ?? [210, 297]
  const sheet = L.orientation === 'landscape' ? [ph, pw] : [pw, ph]
  const shownWithCurves = shownRows.filter(hasCurves)

  const guard = async (k: string, f: () => Promise<void>) => { setBusy(k); setMsg(''); setNote(''); setReasons([]); try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy('') } }
  /** Итог выгрузки: число графиков и, если что-то не построилось, таблица «исследование - причина». */
  const report = (what: string, r: { count: number; errors: number; reasons: AdaptExportError[] }) => {
    setNote(`${what} готов: графиков ${r.count}` + (r.errors ? `. Не построено исследований: ${r.errors}; их нет в файлах, причины ниже.` : '.'))
    setReasons(r.reasons)
  }
  const makeWord = () => body && guard('word', async () => report('Word', await adaptExportDocx(body)))
  const makeAll = () => body && guard('all', async () => report('Пакет', await adaptExportAll({ ...body, formats: zipFmts })))
  const makeZip = () => body && guard('zip', async () => { await adaptExportZip({ ...body.style, run_dir: body.run_dir, ids: chosen, formats: zipFmts }) })
  const makeOne = () => view && curRow && guard('one', async () => {
    await adaptExportChart({ ...cfg.style, run_dir: view.run_dir, id: cur, format: oneFmt }, 'Скв_' + safe(curRow.well + '_' + curRow.date + '_' + cfg.style.y) + '.' + oneFmt)
  })

  /** Шаблон: только известные поля макета, чтобы старые шаблоны не ломали запрос. */
  const loadPreset = () => {
    const p = presets[presetPick]
    if (!p) return
    const known = Object.fromEntries(Object.entries(p.layout ?? {}).filter(([k]) => k in opts.layout.defaults))
    setCfg({ style: { ...cfg.style, ...p.style }, layout: { ...opts.layout.defaults, ...known }, caption: p.caption ?? opts.caption.default, start: p.start ?? 1, object: p.object ?? '' })
    setNote(`Шаблон «${presetPick}» загружен.`)
  }
  const savePreset = () => {
    const name = presetName.trim()
    if (!name) return
    presetStore.set({ ...presetStore.get(), [name]: cfg })
    setPresetPick(name); setPresetName('')
    setNote(`Шаблон «${name}» сохранен в этом браузере.`)
  }
  const deletePreset = () => {
    const next = { ...presetStore.get() }
    delete next[presetPick]
    presetStore.set(next)
    setPresetPick('')
  }

  const runsReady = runs.filter(r => r.has_results)
  return (
    <main className="workspace">
      <PageHead title="Экспорт графиков" lede="Индикаторные диаграммы адаптации по ГДИ: таблица в Word с макетом листа, как в Газовом атласе, картинки ZIP и отдельные файлы." />

      <section className="card">
        <div className="row">
          <label className="grow">Запуск результатов
            <select value={view?.run_dir ?? ''} disabled={busy !== ''} onChange={e => e.target.value && openRun(e.target.value)}>
              {!view && <option value="">— выберите запуск —</option>}
              {runsReady.map(r => <option key={r.dir} value={r.dir}>{r.name}</option>)}
            </select></label>
          <a className="btn" href="#/adapt">К результатам адаптации</a>
        </div>
        {kit ? <p className="muted small">Комплект: {kit}. Запуски создаются расчётом на шаге 6 «Результаты».</p> : <p className="note warn">Комплект ещё не подготовлен: сначала подготовьте его на вкладке «Адаптация по ГДИ».</p>}
        {kit && runsReady.length === 0 && <p className="note warn">В комплекте нет результатов. Выполните расчёт на шаге 6 «Результаты».</p>}
        {msg && <p className="note warn">{msg}</p>}
      </section>

      <section className="card">
        <div className="row">
          <label>Шаблон настроек<select value={presetPick} onChange={e => setPresetPick(e.target.value)}>
            <option value="">— не выбран —</option>{Object.keys(presets).map(n => <option key={n} value={n}>{n}</option>)}</select></label>
          <button onClick={loadPreset} disabled={!presetPick}>Загрузить</button>
          <button onClick={deletePreset} disabled={!presetPick}>Удалить</button>
          <label>Сохранить как<input value={presetName} maxLength={60} placeholder="название" onChange={e => setPresetName(e.target.value)} /></label>
          <button onClick={savePreset} disabled={!presetName.trim()}>Сохранить шаблон</button>
        </div>
        <p className="muted small">Шаблон хранит вид графика, макет листа и подписи. Хранится в этом браузере.</p>
      </section>

      {view && <section className="card">
        <h2>Что выгружать</h2>
        <p className="muted small">Исследования запуска. Без кривых выгрузить нельзя, такие строки отмечены недоступными. Щёлкните по строке, чтобы выбрать график для отдельного файла.</p>
        <div className="row">
          <label>Поиск<input value={q} placeholder="скважина или дата" onChange={e => setQ(e.target.value)} style={{ width: 170 }} /></label>
          <label>Показать<select value={filter} onChange={e => setFilter(e.target.value as Filter)}>
            {FILTERS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
          <span className="muted small">Выбрано: <b>{chosen.length}</b> из {rows.length}</span>
        </div>
        <div className="row">
          <button onClick={() => setAll(rows.filter(hasCurves).map(id))}>Выбрать все</button>
          <button onClick={() => setAll([])}>Ничего</button>
          <button onClick={() => setAll(shownWithCurves.map(id))} disabled={!shownWithCurves.length}>По фильтру ({shownWithCurves.length})</button>
        </div>
        <div className="scroll exp-list"><table className="raw"><thead><tr>
          <th><input type="checkbox" aria-label="Отметить все в списке" checked={shownWithCurves.length > 0 && shownWithCurves.every(r => checked.has(id(r)))}
            onChange={e => toggleShown(e.target.checked)} /></th>
          <th>Скв.</th><th>ГДИ</th><th>R² после</th><th>WPIMULT</th><th>Замечания</th></tr></thead>
          <tbody>{shownRows.map(r => {
            const k = id(r), has = hasCurves(r)
            return <tr key={k} className={(k === cur ? 'sel ' : '') + (r.ok ? '' : 'warnrow')} onClick={() => setCur(k)}
              style={k === cur ? { background: 'var(--accent-soft)' } : undefined}>
              <td onClick={e => e.stopPropagation()}><input type="checkbox" checked={checked.has(k) && has} disabled={!has}
                title={has ? '' : 'Нет кривых для графика'} aria-label={'Исследование ' + r.well + ' ' + r.date} onChange={e => toggle(k, e.target.checked)} /></td>
              <td>{r.well}</td><td>{r.date}</td><td>{fmt(r.r2, 3)}</td><td>{fmt(r.pi_mult, 3)}</td>
              <td className="muted small">{[r.at_bound ? 'WPIMULT на границе' : '', ...r.problems, ...r.notes].filter(Boolean).join('; ') || '—'}</td></tr>
          })}</tbody></table></div>
        {shownRows.length === 0 && <p className="muted small">По этому фильтру исследований нет.</p>}
      </section>}

      <div className="exp-layout">
        <div className="exp-col">
          <div className="exp-bar">
            <Sec title="Вид графика">
              <Sel label="Ось Y индикаторной" value={cfg.style.y} options={pairs(opts.chart.y, lbl)} onCommit={v => setS({ y: String(v) as Style['y'] })} />
              <Sel label="Кривые" value={cfg.style.variant} options={pairs(opts.chart.variant, lbl)} onCommit={v => setS({ variant: String(v) as Style['variant'] })} />
              <Sel label="Оформление" value={cfg.style.look} options={pairs(opts.chart.look, lbl)} onCommit={v => setS({ look: String(v) as Style['look'] })} />
              <Num label="Ширина, мм" value={cfg.style.width} min={opts.chart.width[0]} max={opts.chart.width[1]} onCommit={v => v !== null && setS({ width: v })} />
              <Num label="Высота, мм" value={cfg.style.height ?? null} min={opts.chart.height[0]} max={opts.chart.height[1]} empty onCommit={v => setS({ height: v })} />
              <Sel label="DPI (PNG)" value={cfg.style.dpi} options={pairs(opts.chart.dpi_png, String)} onCommit={v => setS({ dpi: Number(v) })} />
            </Sec>
            <p className="muted small exp-hint">Размер и кривые действуют на Word, ZIP и файл одного графика. Высота пустая - по пропорциям ширины. В Word пропорции берутся отсюда, если высота в макете 0.</p>
          </div>

          <div className="exp-bar">
            <Sec title="Оформление графика">
              <Sel label="Шрифт" value={cfg.style.font} options={F.fonts} onCommit={v => setS({ font: String(v) })} />
              <Num label="Размер шрифта, пт" value={cfg.style.font_size} {...fbounds('font_size')} empty onCommit={v => setS({ font_size: v })} />
              <Txt label="Подпись оси X" value={cfg.style.x_label ?? F.labels.x} wide max={200} onCommit={v => setS({ x_label: v })} />
              <Txt label="Подпись оси Y" value={cfg.style.y_label ?? F.labels.y[cfg.style.y] ?? ''} wide max={200} onCommit={v => setS({ y_label: v })} />
              <Chk label="Заголовок графика" checked={cfg.style.title_on} onChange={v => setS({ title_on: v })} />
              {cfg.style.title_on && <Txt label="Текст заголовка" value={cfg.style.title ?? F.labels.title} wide max={200} onCommit={v => setS({ title: v })} />}
              <Chk label="Легенда" checked={cfg.style.legend} onChange={v => setS({ legend: v })} />
              {cfg.style.legend && <Sel label="Положение легенды" value={cfg.style.legend_pos} options={F.legend_pos} onCommit={v => setS({ legend_pos: String(v) })} />}
              <Num label="Толщина линии, пт" value={cfg.style.line_width} {...fbounds('line_width')} empty onCommit={v => setS({ line_width: v })} />
              <Sel label="Точки ГДИ: форма" value={cfg.style.marker} options={F.markers} onCommit={v => setS({ marker: String(v) })} />
              <Num label="Размер точек, пт" value={cfg.style.marker_size} {...fbounds('marker_size')} empty onCommit={v => setS({ marker_size: v })} />
              <Chk label="Сетка" checked={cfg.style.grid} onChange={v => setS({ grid: v })} />
              <Num label="Ось X: от" value={cfg.style.x_min} empty onCommit={v => setS({ x_min: v })} />
              <Num label="Ось X: до" value={cfg.style.x_max} empty onCommit={v => setS({ x_max: v })} />
              <Num label="Ось Y: от" value={cfg.style.y_min} empty onCommit={v => setS({ y_min: v })} />
              <Num label="Ось Y: до" value={cfg.style.y_max} empty onCommit={v => setS({ y_max: v })} />
              <div className="exp-field wide"><button type="button" className="quiet" onClick={resetFormat}>Вернуть оформление по умолчанию</button></div>
            </Sec>
            <div className="exp-hint muted small">
              <p>Пустое поле - авто. Пустая подпись оси - без подписи. Заголовок - шаблон: <code>{'{скважина}'}</code>, <code>{'{дата}'}</code>.</p>
              <p>Шрифт берётся из системы: Times New Roman, Arial Narrow, Calibri. Если его нет, подставляется аналог.</p>
            </div>
          </div>

          <div className="exp-bar">
            <Sec title="Лист">
              <Sel label="Ориентация" value={String(L.orientation)} options={pairs(opts.layout.orientations, lbl)} onCommit={v => setL('orientation', String(v))} />
              <Sel label="Формат" value={String(L.paper)} options={Object.entries(opts.layout.papers).map(([p, [w, h]]): [string, string] => [p, `${p} (${w} × ${h} мм)`])} onCommit={v => setL('paper', String(v))} />
              <Num label={lim('margin_top').label} value={Number(L.margin_top)} {...bounds('margin_top')} onCommit={v => v !== null && setL('margin_top', v)} />
              <Num label={lim('margin_bottom').label} value={Number(L.margin_bottom)} {...bounds('margin_bottom')} onCommit={v => v !== null && setL('margin_bottom', v)} />
              <Num label={lim('margin_left').label} value={Number(L.margin_left)} {...bounds('margin_left')} onCommit={v => v !== null && setL('margin_left', v)} />
              <Num label={lim('margin_right').label} value={Number(L.margin_right)} {...bounds('margin_right')} onCommit={v => v !== null && setL('margin_right', v)} />
              <Chk label="Номера страниц" checked={Boolean(L.page_numbers)} onChange={v => setL('page_numbers', v)} />
            </Sec>
            <Sec title="Графики на листе">
              <Num label={lim('columns').label} value={Number(L.columns)} {...bounds('columns')} onCommit={v => v !== null && setL('columns', v)} />
              <Num label={lim('per_page').label + ' (0 — сколько влезет)'} value={Number(L.per_page)} {...bounds('per_page')} onCommit={v => v !== null && setL('per_page', v)} />
              <Sel label="Ширина графика" value={String(L.width_mode)} options={pairs(opts.layout.width_modes, lbl)} onCommit={v => setL('width_mode', String(v))} />
              {L.width_mode === 'mm' && <Num label={lim('width_mm').label} value={Number(L.width_mm)} {...bounds('width_mm')} onCommit={v => v !== null && setL('width_mm', v)} />}
              <Num label={lim('height_mm').label + ' (0 — по пропорциям)'} value={Number(L.height_mm)} {...bounds('height_mm')} onCommit={v => v !== null && setL('height_mm', v)} />
              <Num label={lim('gap').label} value={Number(L.gap)} {...bounds('gap')} onCommit={v => v !== null && setL('gap', v)} />
              <Num label={lim('row_gap').label} value={Number(L.row_gap)} {...bounds('row_gap')} onCommit={v => v !== null && setL('row_gap', v)} />
              <Sel label="Линии между графиками" value={String(L.borders)} options={pairs(opts.layout.borders, lbl)} onCommit={v => setL('borders', String(v))} />
              <Chk label="Рамка вокруг графика" checked={Boolean(L.frame)} onChange={v => setL('frame', v)} />
              <Sel label="Качество (DPI)" value={Number(L.dpi)} options={pairs(opts.layout.dpis, String)} onCommit={v => setL('dpi', Number(v))} />
              <Chk label="Сжать картинки (легче файл)" checked={Boolean(L.compress)} onChange={v => setL('compress', v)} />
            </Sec>
            <Sec title="Подпись">
              <Sel label="Вид подписи" value={String(L.caption_mode)} options={pairs(opts.layout.caption_modes, lbl)} onCommit={v => setL('caption_mode', String(v))} />
              <Sel label="Положение" value={String(L.caption_pos)} options={pairs(opts.layout.caption_pos, lbl)} onCommit={v => setL('caption_pos', String(v))} />
              <Sel label="Шрифт" value={String(L.caption_font)} options={pairs(opts.layout.fonts)} onCommit={v => setL('caption_font', String(v))} />
              <Num label={lim('caption_size').label} value={Number(L.caption_size)} {...bounds('caption_size')} onCommit={v => v !== null && setL('caption_size', v)} />
              <Sel label="Выравнивание" value={String(L.caption_align)} options={pairs(opts.layout.aligns, lbl)} onCommit={v => setL('caption_align', String(v))} />
              <Num label={lim('caption_gap').label} value={Number(L.caption_gap)} {...bounds('caption_gap')} onCommit={v => v !== null && setL('caption_gap', v)} />
              <Chk label="Жирная" checked={Boolean(L.caption_bold)} onChange={v => setL('caption_bold', v)} />
              <Chk label="Курсив" checked={Boolean(L.caption_italic)} onChange={v => setL('caption_italic', v)} />
            </Sec>
            <Sec title="Документ">
              <Chk label="Заголовок в начале" checked={Boolean(L.title)} onChange={v => setL('title', v)} />
              {Boolean(L.title) && <Txt label="Текст заголовка" value={String(L.title_text)} wide onCommit={v => setL('title_text', v)} />}
              <Chk label="Список рисунков с гиперссылками" checked={Boolean(L.list_of_figures)} onChange={v => setL('list_of_figures', v)} />
              {Boolean(L.list_of_figures) && <Txt label="Заголовок списка" value={String(L.list_title)} onCommit={v => setL('list_title', v)} />}
            </Sec>
          </div>

          <div className="exp-bar">
            <Sec title="Подписи">
              <Txt label="Шаблон подписи" value={cfg.caption} wide max={500} onCommit={v => setCfg(c => c && { ...c, caption: v })} />
              <Num label="Первый номер рисунка" value={cfg.start} min={1} max={9999} onCommit={v => v !== null && setCfg(c => c && { ...c, start: v })} />
              <Txt label="Объект" value={cfg.object} max={200} onCommit={v => setCfg(c => c && { ...c, object: v })} />
              <div className="exp-field wide"><button type="button" className="quiet" onClick={() => setCfg(c => c && { ...c, caption: opts.caption.default })}>Вернуть шаблон по умолчанию</button></div>
            </Sec>
            <div className="exp-hint muted small">
              <p>Подстановки в шаблоне подписи:</p>
              <ul className="exp-hints">{opts.caption.fields.map(f => <li key={f}><code>{'{' + f + '}'}</code> - {FIELD_HINT[f] ?? ''}</li>)}</ul>
              <p>Подпись с {'{n}'} - настоящая подпись Word: на неё можно сослаться и она попадает в список рисунков.</p>
            </div>
          </div>
        </div>

        <div className="exp-shot">
          <div className="row">
            <button className="quiet" disabled={!shot || shot.page <= 1 || shotBusy} onClick={() => shot && setPage(shot.page - 1)}>← Лист</button>
            <span>{shot ? `Лист ${shot.page} из ${shot.pages}` : '…'}</span>
            <button className="quiet" disabled={!shot || shot.page >= shot.pages || shotBusy} onClick={() => shot && setPage(shot.page + 1)}>Лист →</button>
            {shotBusy && <span className="pulse">Строим лист…</span>}
          </div>
          {shotErr && <p className="note warn">{shotErr}</p>}
          {!view ? <p className="muted">Выберите запуск, и здесь появится лист Word.</p>
            : chosen.length === 0 ? <p className="note">Отметьте хотя бы одно исследование с кривыми: лист строится по выбранным.</p>
            : shot && <img className="exp-sheet" src={shot.url} alt={`Предпросмотр листа ${shot.page}`} />}
          <p className="muted small">Лист {Math.round(sheet[0])} × {Math.round(sheet[1])} мм. Предпросмотр рисует лист так, как его уложит Word; точное число листов - в документе.</p>
        </div>
      </div>

      <section className="card exp-actions">
        <div className="row">
          <button className="primary" onClick={makeWord} disabled={!body || !chosen.length || busy !== ''}>Скачать Word (.docx)</button>
          <span className="exp-zip">
            {['png', 'svg', 'pdf'].map(f => <Chk key={f} label={f.toUpperCase()} checked={zipFmts.includes(f)}
              onChange={on => setZipFmts(v => (on ? [...v, f] : v.filter(x => x !== f)))} />)}
          </span>
          <button onClick={makeZip} disabled={!body || !chosen.length || !zipFmts.length || busy !== ''}>Скачать картинки (ZIP)</button>
        </div>
        <div className="row">
          <button className="primary" onClick={makeAll} disabled={!body || !chosen.length || busy !== ''}>Скачать всё одним архивом (ZIP)</button>
          <span className="muted small">Word, картинки по отмеченным форматам, XLSX с точками графиков, настройки (json) и errors.txt.</span>
        </div>
        <div className="row">
          <span className="muted small">Один график: {curRow ? `скв. ${curRow.well}, ГДИ ${curRow.date}` : 'не выбран'}</span>
          <Sel label="Формат" value={oneFmt} options={[['png', 'PNG'], ['svg', 'SVG'], ['pdf', 'PDF'], ['xlsx', 'XLSX (график и данные)']] as [string, string][]} onCommit={v => setOneFmt(String(v))} />
          <button onClick={makeOne} disabled={!curRow || !hasCurves(curRow) || busy !== ''}>Скачать выбранный график</button>
        </div>
        {busy && <span className="pulse">{{ word: 'Создание Word…', zip: 'Создание архива…', all: 'Сборка пакета…', one: 'Создание графика…', open: 'Открываем запуск…' }[busy] ?? 'Выполняется…'}</span>}
        {!chosen.length && view && <p className="note">Нет исследований с кривыми для выгрузки.</p>}
        {note && <p className="note">{note}</p>}
        {reasons.length > 0 && <div className="exp-reasons">
          <table className="raw"><thead><tr><th>Исследование (скважина, дата)</th><th>Причина</th></tr></thead>
            <tbody>{reasons.map((e, i) => <tr key={i}><td>{e['График']}</td><td>{e['Ошибка']}</td></tr>)}</tbody></table>
        </div>}
        {msg && view && <p className="note warn">{msg}</p>}
      </section>
    </main>
  )
}

/** Значения по умолчанию с сервера → состояние вкладки: размеры макета называются width/height, как в запросе. */
function styleFrom(d: AdaptChartDefaults): Style {
  const { width_mm, height_mm, ...rest } = d
  return { ...rest, width: width_mm, height: height_mm } as Style
}
/** Только поля оформления (без вида графика и размера) - для кнопки «по умолчанию». */
function formatFrom(d: AdaptChartDefaults): Partial<Style> {
  return { font: d.font, font_size: d.font_size, x_label: d.x_label, y_label: d.y_label, title_on: d.title_on, title: d.title,
    legend: d.legend, legend_pos: d.legend_pos, line_width: d.line_width, marker: d.marker, marker_size: d.marker_size, grid: d.grid,
    x_min: d.x_min, x_max: d.x_max, y_min: d.y_min, y_max: d.y_max }
}

/** Пары «значение, подпись» для выпадающих списков. */
const pairs = <T extends string | number>(vals: readonly T[], label: (v: T) => string = v => String(v)): [T, string][] =>
  vals.map(v => [v, label(v)] as [T, string])

/** Блок настроек: заголовок слева, поля справа (как в «Параметрах» Атласа). */
function Sec({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="exp-sec" aria-label={title}>
      <span className="exp-title">{title}</span>
      <div className="exp-fields">{children}</div>
    </section>
  )
}

function Sel({ label, value, options, onCommit }: { label: string; value: string | number; options: [string | number, string][]; onCommit: (v: string | number) => void }) {
  return (
    <label className="exp-field">
      <span className="exp-label">{label}</span>
      <select value={String(value)} onChange={e => { const o = options.find(([v]) => String(v) === e.target.value); if (o) onCommit(o[0]) }}>
        {options.map(([v, l]) => <option key={String(v)} value={String(v)}>{l}</option>)}
      </select>
    </label>
  )
}

/** Число: в состояние уходит только значение в пределах; пустое - null, если поле может быть пустым (авто). */
function Num({ label, value, min, max, empty, onCommit }: { label: string; value: number | null; min?: number; max?: number; empty?: boolean; onCommit: (v: number | null) => void }) {
  const text0 = value === null ? '' : String(value)
  const [text, setText] = useState(text0)
  useEffect(() => setText(text0), [text0])
  const t = text.trim()
  const n = Number(t.replace(',', '.'))
  const inside = t !== '' && Number.isFinite(n) && (min === undefined || n >= min) && (max === undefined || n <= max)
  const ok = inside || (t === '' && !!empty)
  return (
    <label className={'exp-field' + (ok ? '' : ' invalid')}>
      <span className="exp-label">{label}</span>
      <input type="number" min={min} max={max} step="any" value={text} placeholder={empty ? 'авто' : undefined}
        onChange={e => {
          const s = e.target.value
          setText(s)
          const tt = s.trim(), v = Number(tt.replace(',', '.'))
          if (tt === '' && empty) onCommit(null)
          else if (tt !== '' && Number.isFinite(v) && (min === undefined || v >= min) && (max === undefined || v <= max)) onCommit(v)
        }} />
      {!ok && <span className="field-error">от {min} до {max}</span>}
    </label>
  )
}

function Chk({ label, checked, onChange, disabled, title }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; title?: string }) {
  return (
    <label className="exp-check" title={title}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={e => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  )
}

function Txt({ label, value, onCommit, wide, max = 500 }: { label: string; value: string; onCommit: (v: string) => void; wide?: boolean; max?: number }) {
  return (
    <label className={'exp-field' + (wide ? ' wide' : '')}>
      <span className="exp-label">{label}</span>
      <input value={value} maxLength={max} onChange={e => onCommit(e.target.value)} />
    </label>
  )
}
