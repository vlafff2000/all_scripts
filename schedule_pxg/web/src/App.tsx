import { useEffect, useState } from 'react'
import Averaging from './Averaging'
import Charts from './Charts'
import History from './History'
import Scenarios from './Scenarios'
import Strategies from './Strategies'
import TechMaps from './TechMaps'
import { AppState, CheckResult, Preview, Template, Trial, deleteTemplate, getPreview, getState, pickFile, runCheck, runTrial, saveTemplate } from './api'

type Field = 'well' | 'date' | 'rate' | 'hourly' | 'hours' | 'kind'
const FIELDS: { key: Field; label: string; help: string; need?: boolean }[] = [
  { key: 'well', label: 'Номер скважины', help: 'Столбец, где записан номер или название скважины. Если файл — один объект целиком (дата и объём), оставьте пустым.', need: true },
  { key: 'date', label: 'Дата', help: 'Столбец с датой работы скважины (одна строка = одни сутки).', need: true },
  { key: 'rate', label: 'Суточный расход', help: 'Объём газа за сутки. Если такого столбца нет, оставьте пустым: возьмём часовой расход × часы работы.' },
  { key: 'hourly', label: 'Часовой расход', help: 'Нужен только если нет суточного расхода (м³/ч).' },
  { key: 'hours', label: 'Часы работы за сутки', help: 'Сколько часов скважина работала в эти сутки. Можно не указывать.' },
  { key: 'kind', label: 'Закачка или отбор', help: 'Столбец, где написано, что делала скважина. Если такого столбца нет, выберите вид ниже.' },
]
const empty = (): Template => ({ name: '', sheet: null, header_row: 0, well: '', date: '', rate: '', hourly: '', hours: '', kind: '', kind_default: '', unit: 'м3/сут', layout: 'table' })

function Step({ n, title, lead, children }: { n: number; title: string; lead?: string; children: React.ReactNode }) {
  return (
    <section className="card step">
      <div className="step-head"><span className="step-n">{n}</span><h2>{title}</h2></div>
      {lead && <p className="lead">{lead}</p>}
      {children}
    </section>
  )
}

function FileSlot({ title, help, example, value, onChange, onPick, busy }:
  { title: string; help: string; example?: string; value: string; onChange: (v: string) => void; onPick: () => void; busy: boolean }) {
  return (
    <div className={'slot' + (value.trim() ? ' filled' : '')}>
      <div className="slot-title">{title}</div>
      <p className="muted small">{help}</p>
      {example && <p className="example">Пример: {example}</p>}
      <div className="row">
        <input className="grow" value={value} placeholder="Нажмите «Выбрать файл» или вставьте путь к файлу" onChange={e => onChange(e.target.value)} />
        <button onClick={onPick} disabled={busy}>Выбрать файл…</button>
      </div>
    </div>
  )
}

type Wiz = 'history' | 'volumes'

export default function App() {
  const [wiz, setWiz] = useState<Wiz>('history')
  const [tab, setTab] = useState<'import' | 'techmaps' | 'averaging' | 'scenarios' | 'strategies' | 'charts' | 'history'>('import')
  const [st, setSt] = useState<AppState | null>(null)
  const [path, setPath] = useState('')
  const [pv, setPv] = useState<Preview | null>(null)
  const [tpl, setTpl] = useState<Template>(empty())
  const [trial, setTrial] = useState<Trial | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { getState().then(setSt).catch(e => setMsg(e.message)) }, [])

  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const open = (sheet?: string, headerRow?: number, keepFields = false) => guard(async () => {
    const p = await getPreview(path.trim(), sheet, headerRow)
    setPv(p); setTrial(null)
    setTpl(t => ({ ...(keepFields ? t : empty()), name: t.name, sheet: p.sheet, header_row: p.headerRow,
      ...(keepFields ? {} : { ...p.suggest, unit: p.unit }) }))
  })
  const pick = () => guard(async () => {
    const r = await pickFile(path)
    if (r.path) setPath(r.path)
  })
  const set = (k: keyof Template, v: string | number) => { setTpl(t => ({ ...t, [k]: v })); setTrial(null) }
  const test = () => guard(async () => { setTrial(await runTrial(path.trim(), tpl)) })
  const save = () => guard(async () => { setSt(await saveTemplate(tpl)); setMsg('Шаблон «' + tpl.name + '» сохранён в проекте. В следующий раз выберите его слева.') })
  const remove = (name: string) => guard(async () => { setSt(await deleteTemplate(name)) })
  const [ck, setCk] = useState({ totals: '', approved: '', groups: [] as string[], addPath: '', mode: 'закачка', year: String(new Date().getFullYear()), folder: '' })
  const [res, setRes] = useState<CheckResult | null>(null)
  const setC = (k: string, v: string) => { setCk(c => ({ ...c, [k]: v })); setRes(null) }
  const pickC = (k: 'totals' | 'approved') => guard(async () => { const r = await pickFile(ck[k]); if (r.path) setC(k, r.path) })
  const addGroupFile = (p: string) => {
    const v = p.trim().replace(/^"|"$/g, '')
    if (v) setCk(c => ({ ...c, groups: c.groups.includes(v) ? c.groups : [...c.groups, v], addPath: '' }))
    setRes(null)
  }
  const pickGroup = () => guard(async () => { const r = await pickFile(''); if (r.path) addGroupFile(r.path) })
  const dropGroup = (p: string) => { setCk(c => ({ ...c, groups: c.groups.filter(x => x !== p) })); setRes(null) }
  const check = () => guard(async () => {
    setRes(await runCheck({ totals: ck.totals.trim(), approved: ck.approved.trim(), gsp: ck.groups, mode: ck.mode, year: Number(ck.year), folder: ck.folder.trim() }))
  })
  const cols = pv ? pv.columns.filter(c => c) : []
  const sample = (col: string) => {
    if (!pv || !col) return ''
    const j = pv.columns.indexOf(col)
    const r = pv.rows[pv.headerRow + 1]
    return j >= 0 && r && r[j] ? r[j] : ''
  }
  const layout = tpl.layout || 'table'
  const needMore = !!pv && (layout === 'matrix' ? !tpl.date : layout === 'matrix_t' ? !tpl.well : !tpl.date || !(tpl.rate || tpl.hourly))

  return (
    <div className="shell">
      <aside className="side">
        <h1>Скедул ПХГ</h1>
        <div className="tabs">
          <button className={tab === 'import' ? 'on' : ''} onClick={() => setTab('import')}>Импорт истории</button>
          <button className={tab === 'techmaps' ? 'on' : ''} onClick={() => setTab('techmaps')}>Тех.карты</button>
          <button className={tab === 'averaging' ? 'on' : ''} onClick={() => setTab('averaging')}>Осреднение</button>
          <button className={tab === 'scenarios' ? 'on' : ''} onClick={() => setTab('scenarios')}>Сценарии</button>
          <button className={tab === 'strategies' ? 'on' : ''} onClick={() => setTab('strategies')}>Стратегии</button>
          <button className={tab === 'charts' ? 'on' : ''} onClick={() => setTab('charts')}>Графики</button>
          <button className={tab === 'history' ? 'on' : ''} onClick={() => setTab('history')}>История</button>
        </div>
        {tab === 'import' && <>
        <p className="muted">Загрузка данных</p>
        <h2>Что загружаем</h2>
        <button className={'nav' + (wiz === 'history' ? ' on' : '')} onClick={() => setWiz('history')}>
          <b>История работы скважин</b><span>таблица с датой, скважиной и расходом</span></button>
        <button className={'nav' + (wiz === 'volumes' ? ' on' : '')} onClick={() => setWiz('volumes')}>
          <b>Объёмы по группам скважин</b><span>проверочный Excel из общих объёмов</span></button>
        {wiz === 'history' && <>
          <h2>Сохранённые шаблоны</h2>
          {st && st.templates.length === 0 && <p className="muted small">Пока нет. Шаблон запоминает, в каких столбцах что лежит, чтобы не настраивать такой же файл заново.</p>}
          {st?.templates.map(t => (
            <div key={t.name} className="tpl-item">
              <button className="link" onClick={() => { setTpl(t); setTrial(null) }}>{t.name}</button>
              <button className="x" title="Удалить шаблон" onClick={() => remove(t.name)}>×</button>
            </div>
          ))}
        </>}
        </>}
        {st && <p className="muted small">Проект: {st.folder}</p>}
      </aside>
      {tab === 'history' && st ? <History st={st} /> : tab === 'charts' && st ? <Charts st={st} /> : tab === 'averaging' && st ? <Averaging st={st} /> : tab === 'scenarios' && st ? <Scenarios st={st} setSt={setSt} /> : tab === 'strategies' && st ? <Strategies st={st} setSt={setSt} /> : tab === 'techmaps' && st ? <TechMaps st={st} setSt={setSt} /> : <main className="work">
        {msg && <p className="note warn">{msg}</p>}
        {wiz === 'history' && <>
          <div className="intro">
            <h1>Загрузка истории работы скважин</h1>
            <p>Покажите программе Excel-файл с историей, и она переложит его в свою таблицу. Всего четыре шага: выбрать файл, показать, где заголовок,
              сказать, в каком столбце что лежит, и проверить результат. Знакомые файлы (база расходов, листы по группам скважин, посуточные итоги) программа узнаёт сама.</p>
          </div>
          <Step n={1} title="Выберите файл с историей" lead="Подойдёт любой Excel (.xlsx, .xls), где одна строка — одни сутки работы одной скважины.">
            <div className="row">
              <input className="grow" value={path} placeholder="Нажмите «Выбрать файл» или вставьте путь к файлу" onChange={e => setPath(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && path.trim() && open()} />
              <button onClick={pick} disabled={busy}>Выбрать файл…</button>
              <button className="primary" onClick={() => open()} disabled={busy || !path.trim()}>Открыть файл</button>
            </div>
            {pv?.format && <p className="note">Программа узнала этот файл: «{pv.format}». Для него ничего настраивать не нужно, можно сразу загружать. Шаги ниже нужны только для нестандартных таблиц.</p>}
          </Step>

          {pv && <>
            <Step n={2} title="Покажите, где заголовок таблицы"
              lead="Заголовок — строка, в которой написаны названия столбцов («Скважина», «Дата» и т. п.). Программа выбрала её сама (подсвечена). Если ошиблась, нажмите на нужную строку.">
              <div className="row">
                <label>Лист книги
                  <select value={String(pv.sheet)} onChange={e => open(e.target.value)}>
                    {pv.sheets.map(s => <option key={s}>{s}</option>)}
                  </select>
                </label>
                <label>Номер строки с заголовком
                  <input type="number" min={1} value={pv.headerRow + 1} onChange={e => open(String(pv.sheet), Math.max(0, Number(e.target.value) - 1), false)} />
                </label>
                <span className="muted small">на листе {pv.total} строк, показаны первые {pv.rows.length}</span>
              </div>
              <div className="scroll">
                <table className="raw">
                  <tbody>
                    {pv.rows.map((r, i) => (
                      <tr key={i} className={i === pv.headerRow ? 'hdr' : ''} onClick={() => open(String(pv.sheet), i)} title="Нажмите, чтобы сделать эту строку заголовком">
                        <th>{i + 1}</th>{r.map((c, j) => <td key={j}>{c}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Step>

            <Step n={3} title="Скажите, в каком столбце что лежит"
              lead="Для каждого пункта выберите столбец из вашего файла. Подсказки уже расставлены автоматически: проверьте их. Обязательные пункты отмечены звёздочкой.">
              <div className="cols">
                <div className="colrow">
                  <div className="colinfo"><b>Как устроена таблица</b><span className="muted small">Разные файлы устроены по-разному: выберите ближайший вариант.</span></div>
                  <select value={layout} onChange={e => set('layout', e.target.value)}>
                    <option value="table">Список: одна строка = одни сутки (скважины нет — это итог по объекту)</option>
                    <option value="matrix">Матрица: даты в строках, скважины в столбцах</option>
                    <option value="matrix_t">Матрица: скважины в строках, даты в столбцах</option>
                  </select><span />
                </div>
                {FIELDS.filter(f => layout === 'table' || (layout === 'matrix' ? f.key === 'date' || f.key === 'kind' : f.key === 'well' || f.key === 'kind')).map(f => (
                  <div key={f.key} className={'colrow' + (f.need && f.key !== 'well' && !tpl[f.key] || layout === 'matrix_t' && f.key === 'well' && !tpl.well ? ' missing' : '')}>
                    <div className="colinfo"><b>{f.label}{(f.need && f.key !== 'well' || layout === 'matrix_t' && f.key === 'well') && <span className="req"> *</span>}</b><span className="muted small">{f.help}</span></div>
                    <select value={tpl[f.key]} onChange={e => set(f.key, e.target.value)}>
                      <option value="">— не указывать —</option>
                      {cols.map(c => <option key={c}>{c}</option>)}
                    </select>
                    <span className="example">{sample(tpl[f.key]) ? 'в файле, например: ' + sample(tpl[f.key]) : ''}</span>
                  </div>
                ))}
                <div className="colrow">
                  <div className="colinfo"><b>В каких единицах значения</b><span className="muted small">Как подписан расход или объём за сутки (м³, тыс. м³, млн м³ …). Программа пересчитает в м³/сут.</span></div>
                  <select value={tpl.unit} onChange={e => set('unit', e.target.value)}>{st?.units.map(u => <option key={u}>{u}</option>)}</select><span />
                </div>
                <div className="colrow">
                  <div className="colinfo"><b>Что делала скважина, если в файле это не указано</b><span className="muted small">Нужно, если нет столбца «Закачка или отбор». По умолчанию определим по названию листа.</span></div>
                  <select value={tpl.kind_default} onChange={e => set('kind_default', e.target.value)}>
                    <option value="">по названию листа</option>
                    {st?.kinds.map(k => <option key={k}>{k}</option>)}
                  </select><span />
                </div>
              </div>
              <div className="row">
                <button className="primary" onClick={test} disabled={busy || needMore}>Проверить на этом файле</button>
                {needMore && <span className="muted small">Сначала выберите нужные столбцы (отмечены звёздочкой).</span>}
                {!needMore && <span className="muted small">Ничего не сохраняется: просто покажем, что получится.</span>}
              </div>
            </Step>

            {trial && (
              <Step n={4} title="Что получилось" lead="Посмотрите на образец строк. Если всё верно, сохраните шаблон, и такие файлы будут открываться сразу.">
                {trial.rows === 0 ? <p className="note warn">{trial.summary}</p> : <>
                  <p>Прочитано строк: <b>{trial.rows}</b>, скважин: <b>{trial.wells}</b>, период с {trial.from} по {trial.to}.
                    {' '}{Object.entries(trial.kinds).map(([k, n]) => k + ': ' + n).join(', ')}.</p>
                  <div className="scroll">
                    <table className="raw">
                      <thead><tr><th>Скважина</th><th>Дата</th><th>Расход, м³/сут</th><th>Часы работы</th><th>Закачка / отбор</th></tr></thead>
                      <tbody>{trial.sample.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c ?? '—'}</td>)}</tr>)}</tbody>
                    </table>
                  </div>
                  <p className="muted">Проверка данных: {trial.summary}</p>
                </>}
                {trial.issues.length > 0 && <ul className="issues">{trial.issues.map((i, k) => <li key={k} className={i.level}>{i.message}</li>)}</ul>}
                {trial.rows > 0 && (
                  <div className="row">
                    <label>Название шаблона
                      <input value={tpl.name} placeholder="Например: Отчёт по закачке" onChange={e => setTpl({ ...tpl, name: e.target.value })} /></label>
                    <button className="primary" onClick={save} disabled={busy || !tpl.name.trim()}>Сохранить шаблон</button>
                  </div>
                )}
              </Step>
            )}
          </>}
        </>}

        {wiz === 'volumes' && <>
          <div className="intro">
            <h1>Объёмы по группам скважин</h1>
            <p>Программа берёт общий объём газа по объекту и раскладывает его по группам скважин и по скважинам внутри группы, так же как делал старый скрипт.
              В конце сверяет сумму с общим объёмом и показывает расхождения. Загрузите три вида файлов ниже.</p>
          </div>
          <Step n={1} title="Общий объём газа по дням" lead="Сколько газа в целом по объекту планируется или было за каждые сутки.">
            <FileSlot title="Файл с общими объёмами" help="Excel с двумя столбцами: дата и объём (м³ в сутки)." example="«Дата» — 01.11.2025, «Объем» — 28 636 363"
              value={ck.totals} onChange={v => setC('totals', v)} onPick={() => pickC('totals')} busy={busy} />
          </Step>
          <Step n={2} title="Утверждённые объёмы по группам скважин" lead="Сколько газа утверждено на каждую группу скважин по месяцам.">
            <FileSlot title="Файл с утверждёнными объёмами" help="Excel, где в строках группы скважин, а в столбцах месяцы. Первый столбец с номером группы скважин, справа объёмы по месяцам."
              example="строка «Номер группы скважин: 1», далее Ноябрь — 113,6; Декабрь — 238,56"
              value={ck.approved} onChange={v => setC('approved', v)} onPick={() => pickC('approved')} busy={busy} />
          </Step>
          <Step n={3} title="Файлы по группам скважин" lead="Файлы, по которым программа узнаёт, какую долю объёма даёт каждая скважина внутри своей группы. Можно добавить несколько файлов.">
            <div className="slot">
              <p className="muted small">Обычно это пара файлов на группу: на каждый месяц отдельный лист, в таблице номера скважин и часовой расход по дням.</p>
              {ck.groups.length === 0 && <p className="muted small">Файлы пока не добавлены.</p>}
              {ck.groups.map(g => (
                <div key={g} className="chip"><span title={g}>{g.split(/[\\/]/).pop()}</span><span className="muted small">{g}</span>
                  <button className="x" title="Убрать файл" onClick={() => dropGroup(g)}>×</button></div>
              ))}
              <div className="row">
                <button onClick={pickGroup} disabled={busy}>Добавить файл…</button>
                <input className="grow" value={ck.addPath} placeholder="или вставьте путь к файлу и нажмите Enter" onChange={e => setCk(c => ({ ...c, addPath: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && addGroupFile(ck.addPath)} />
              </div>
            </div>
          </Step>
          <Step n={4} title="Параметры" lead="Что считаем и за какой период.">
            <div className="grid">
              <label>Что считаем
                <select value={ck.mode} onChange={e => setC('mode', e.target.value)}><option>закачка</option><option>отбор</option></select></label>
              <label>Год начала сезона
                <input type="number" value={ck.year} onChange={e => setC('year', e.target.value)} />
                <span className="muted small">Например, для сезона отбора 2025–2026 укажите 2025.</span></label>
              <label>Куда сохранить результат
                <input value={ck.folder} onChange={e => setC('folder', e.target.value)} placeholder="Папка «Проверка» в проекте" />
                <span className="muted small">Оставьте пустым, чтобы сохранить в папку «Проверка» внутри проекта.</span></label>
            </div>
            <div className="row">
              <button className="primary" onClick={check} disabled={busy || !ck.totals.trim() || !ck.approved.trim() || ck.groups.length === 0}>Создать проверочный Excel</button>
              {(!ck.totals.trim() || !ck.approved.trim() || ck.groups.length === 0) &&
                <span className="muted small">Сначала добавьте файлы из шагов 1–3.</span>}
            </div>
            {res && (res.ok
              ? <p className="note">Готово: создано файлов по группам скважин — {res.files.length}, дней в сводке — {res.days}, наибольшее расхождение с общим объёмом — {res.maxDevPct}%. Папка: {res.folder}</p>
              : <p className="note warn">Файлы не созданы. Причины ниже.</p>)}
            {res && res.issues.length > 0 && <ul className="issues">{res.issues.map((i, k) => <li key={k} className={i.level}>{i.message}</li>)}</ul>}
          </Step>
        </>}
      </main>}
    </div>
  )
}
