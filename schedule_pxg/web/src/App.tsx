import { useEffect, useState } from 'react'
import { AppState, CheckResult, Preview, Template, Trial, deleteTemplate, getPreview, getState, pickFile, runCheck, runTrial, saveTemplate } from './api'

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
  const [ck, setCk] = useState({ totals: '', approved: '', gsp: '', mode: 'закачка', year: String(new Date().getFullYear()), folder: '' })
  const [res, setRes] = useState<CheckResult | null>(null)
  const setC = (k: string, v: string) => { setCk(c => ({ ...c, [k]: v })); setRes(null) }
  const pickC = (k: 'totals' | 'approved') => guard(async () => { const r = await pickFile(ck[k]); if (r.path) setC(k, r.path) })
  const gspList = ck.gsp.split('\n').map(x => x.trim()).filter(Boolean)
  const check = () => guard(async () => {
    setRes(await runCheck({ totals: ck.totals.trim(), approved: ck.approved.trim(), gsp: gspList, mode: ck.mode, year: Number(ck.year), folder: ck.folder.trim() }))
  })
  const cols = pv ? pv.columns.filter(c => c) : []

  return (
    <div className="shell">
      <aside className="side">
        <h1>Скедул ПХГ</h1>
        <p className="muted">Мастер импорта истории</p>
        <h2>Шаблоны проекта</h2>
        {st && st.templates.length === 0 && <p className="muted">Пока нет. Сопоставьте столбцы нового файла и сохраните шаблон.</p>}
        {st?.templates.map(t => (
          <div key={t.name} className="tpl-item">
            <button className="link" onClick={() => { setTpl(t); setTrial(null) }}>{t.name}</button>
            <button className="x" title="Удалить шаблон" onClick={() => remove(t.name)}>×</button>
          </div>
        ))}
        {st && <p className="muted small">Проект: {st.folder}</p>}
      </aside>
      <main className="work">
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
        <section className="card">
          <h2>Проверочный Excel по общим объёмам</h2>
          <p className="muted">Раскладывает общий объём газа по ГСП и скважинам, как старый скрипт, и сверяет сумму с фактом по объекту.</p>
          <div className="grid">
            <label>Общие объёмы (дата, м³/сут)
              <span className="row"><input className="grow" value={ck.totals} onChange={e => setC('totals', e.target.value)} />
                <button onClick={() => pickC('totals')} disabled={busy}>Выбрать…</button></span></label>
            <label>Утверждённые объёмы
              <span className="row"><input className="grow" value={ck.approved} onChange={e => setC('approved', e.target.value)} />
                <button onClick={() => pickC('approved')} disabled={busy}>Выбрать…</button></span></label>
            <label>Файлы ГСП (по одному пути в строке)
              <textarea rows={3} value={ck.gsp} onChange={e => setC('gsp', e.target.value)} /></label>
            <label>Режим
              <select value={ck.mode} onChange={e => setC('mode', e.target.value)}><option>закачка</option><option>отбор</option></select></label>
            <label>Год начала сезона
              <input type="number" value={ck.year} onChange={e => setC('year', e.target.value)} /></label>
            <label>Папка результата <span className="muted small">· пусто = «Проверка» в проекте</span>
              <input value={ck.folder} onChange={e => setC('folder', e.target.value)} /></label>
          </div>
          <div className="row">
            <button className="primary" onClick={check} disabled={busy || !ck.totals.trim() || !ck.approved.trim() || gspList.length === 0}>Создать проверочный Excel</button>
          </div>
          {res && (res.ok
            ? <p className="note">Готово: файлов ГСП {res.files.length}, дней в сводке {res.days}, наибольшее расхождение {res.maxDevPct}%. Папка: {res.folder}</p>
            : <p className="note warn">Файлы не созданы.</p>)}
          {res && res.issues.length > 0 && <ul className="issues">{res.issues.map((i, k) => <li key={k} className={i.level}>{i.message}</li>)}</ul>}
        </section>
        {msg && <p className="note warn">{msg}</p>}
      </main>
    </div>
  )
}
