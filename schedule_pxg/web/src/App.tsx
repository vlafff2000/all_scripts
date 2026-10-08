import { useEffect, useState } from 'react'
import Averaging from './Averaging'
import Charts from './Charts'
import Scenarios from './Scenarios'
import TechMaps from './TechMaps'
import { AppState, Preview, Template, Trial, deleteTemplate, getPreview, getState, pickFile, runTrial, saveTemplate } from './api'

type Field = 'well' | 'date' | 'rate' | 'hourly' | 'hours' | 'kind'
const FIELDS: { key: Field; label: string; hint: string }[] = [
  { key: 'well', label: 'Скважина', hint: 'обязательно' },
  { key: 'date', label: 'Дата', hint: 'обязательно' },
  { key: 'rate', label: 'Расход', hint: 'суточный; если нет, возьмём часовой × часы' },
  { key: 'hourly', label: 'Часовой расход', hint: 'м³/ч, нужен, если нет суточного' },
  { key: 'hours', label: 'Часы работы', hint: 'за сутки' },
  { key: 'kind', label: 'Вид (закачка/отбор)', hint: 'если нет столбца, выберите вид ниже' },
]
const empty = (): Template => ({ name: '', sheet: null, header_row: 0, well: '', date: '', rate: '', hourly: '', hours: '', kind: '', kind_default: '', unit: 'м3/сут' })

export default function App() {
  const [st, setSt] = useState<AppState | null>(null)
  const [path, setPath] = useState('')
  const [pv, setPv] = useState<Preview | null>(null)
  const [tpl, setTpl] = useState<Template>(empty())
  const [trial, setTrial] = useState<Trial | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState<'import' | 'techmaps' | 'averaging' | 'scenarios' | 'charts'>('import')

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
  const save = () => guard(async () => { setSt(await saveTemplate(tpl)); setMsg('Шаблон «' + tpl.name + '» сохранён в проекте') })
  const remove = (name: string) => guard(async () => { setSt(await deleteTemplate(name)) })
  const cols = pv ? pv.columns.filter(c => c) : []

  return (
    <div className="shell">
      <aside className="side">
        <h1>Скедул ПХГ</h1>
        <div className="tabs">
          <button className={tab === 'import' ? 'on' : ''} onClick={() => setTab('import')}>Импорт истории</button>
          <button className={tab === 'techmaps' ? 'on' : ''} onClick={() => setTab('techmaps')}>Тех.карты</button>
          <button className={tab === 'averaging' ? 'on' : ''} onClick={() => setTab('averaging')}>Осреднение</button>
          <button className={tab === 'scenarios' ? 'on' : ''} onClick={() => setTab('scenarios')}>Сценарии</button>
          <button className={tab === 'charts' ? 'on' : ''} onClick={() => setTab('charts')}>Графики</button>
        </div>
        {tab === 'import' && <><h2>Шаблоны проекта</h2>
        {st && st.templates.length === 0 && <p className="muted">Пока нет. Сопоставьте столбцы нового файла и сохраните шаблон.</p>}
        {st?.templates.map(t => (
          <div key={t.name} className="tpl-item">
            <button className="link" onClick={() => { setTpl(t); setTrial(null) }}>{t.name}</button>
            <button className="x" title="Удалить шаблон" onClick={() => remove(t.name)}>×</button>
          </div>
        ))}</>}
        {st && <p className="muted small">Проект: {st.folder}</p>}
      </aside>
      {tab === 'charts' && st ? <Charts st={st} /> : tab === 'averaging' && st ? <Averaging st={st} /> : tab === 'scenarios' && st ? <Scenarios st={st} setSt={setSt} /> : tab === 'techmaps' && st ? <TechMaps st={st} setSt={setSt} /> : <main className="work">
        <section className="card">
          <h2>1. Файл</h2>
          <div className="row">
            <input className="grow" value={path} placeholder="Путь к файлу Excel" onChange={e => setPath(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && path.trim() && open()} />
            <button onClick={pick} disabled={busy}>Выбрать…</button>
            <button className="primary" onClick={() => open()} disabled={busy || !path.trim()}>Показать</button>
          </div>
          {pv?.format && <p className="note">Формат узнан сам: «{pv.format}». Шаблон нужен только для нестандартных таблиц.</p>}
        </section>

        {pv && <>
          <section className="card">
            <h2>2. Лист и строка заголовка</h2>
            <div className="row">
              <label>Лист
                <select value={String(pv.sheet)} onChange={e => open(e.target.value)}>
                  {pv.sheets.map(s => <option key={s}>{s}</option>)}
                </select>
              </label>
              <label>Строка заголовка (с 1)
                <input type="number" min={1} value={pv.headerRow + 1} onChange={e => open(String(pv.sheet), Math.max(0, Number(e.target.value) - 1), false)} />
              </label>
              <span className="muted">строк на листе: {pv.total}</span>
            </div>
            <div className="scroll">
              <table className="raw">
                <tbody>
                  {pv.rows.map((r, i) => (
                    <tr key={i} className={i === pv.headerRow ? 'hdr' : ''} onClick={() => open(String(pv.sheet), i)} title="Нажмите, чтобы сделать строкой заголовка">
                      <th>{i + 1}</th>{r.map((c, j) => <td key={j}>{c}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h2>3. Столбцы</h2>
            <div className="grid">
              {FIELDS.map(f => (
                <label key={f.key}>{f.label}<span className="muted small"> · {f.hint}</span>
                  <select value={tpl[f.key]} onChange={e => set(f.key, e.target.value)}>
                    <option value="">не задан</option>
                    {cols.map(c => <option key={c}>{c}</option>)}
                  </select>
                </label>
              ))}
              <label>Единица столбца «Расход»
                <select value={tpl.unit} onChange={e => set('unit', e.target.value)}>{st?.units.map(u => <option key={u}>{u}</option>)}</select>
              </label>
              <label>Вид, если столбца нет
                <select value={tpl.kind_default} onChange={e => set('kind_default', e.target.value)}>
                  <option value="">по названию листа</option>
                  {st?.kinds.map(k => <option key={k}>{k}</option>)}
                </select>
              </label>
            </div>
            <div className="row">
              <button className="primary" onClick={test} disabled={busy}>Пробный импорт</button>
            </div>
          </section>

          {trial && (
            <section className="card">
              <h2>4. Результат</h2>
              {trial.rows === 0 ? <p className="note warn">{trial.summary}</p> : <>
                <p>Строк: <b>{trial.rows}</b>, скважин: <b>{trial.wells}</b>, период {trial.from} — {trial.to}.
                  {' '}{Object.entries(trial.kinds).map(([k, n]) => k + ': ' + n).join(', ')}.</p>
                <div className="scroll">
                  <table className="raw">
                    <thead><tr><th>Скважина</th><th>Дата</th><th>Расход, м³/сут</th><th>Часы</th><th>Вид</th></tr></thead>
                    <tbody>{trial.sample.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c ?? '—'}</td>)}</tr>)}</tbody>
                  </table>
                </div>
                <p className="muted">Проверка исходников: {trial.summary}</p>
              </>}
              {trial.issues.length > 0 && <ul className="issues">{trial.issues.map((i, k) => <li key={k} className={i.level}>{i.message}</li>)}</ul>}
              {trial.rows > 0 && (
                <div className="row">
                  <input value={tpl.name} placeholder="Название шаблона" onChange={e => setTpl({ ...tpl, name: e.target.value })} />
                  <button className="primary" onClick={save} disabled={busy || !tpl.name.trim()}>Сохранить шаблон</button>
                </div>
              )}
            </section>
          )}
        </>}
        {msg && <p className="note warn">{msg}</p>}
      </main>}
    </div>
  )
}
