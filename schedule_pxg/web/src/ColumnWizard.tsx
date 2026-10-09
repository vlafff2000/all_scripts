import { useEffect, useState } from 'react'
import { AppState, Preview, Template, Trial, deleteTemplate, getPreview, pickFile, runTrial, saveTemplate } from './api'

type Field = 'well' | 'date' | 'rate' | 'hourly' | 'hours' | 'kind' | 'group' | 'group'
const FIELDS: { key: Field; label: string; help: string; need?: boolean }[] = [
  { key: 'well', label: 'Номер скважины', help: 'Столбец, где записан номер или название скважины. Если файл — один объект целиком (дата и объём), оставьте пустым.', need: true },
  { key: 'date', label: 'Дата', help: 'Столбец с датой работы скважины (одна строка = одни сутки).', need: true },
  { key: 'rate', label: 'Суточный расход', help: 'Объём газа за сутки. Если такого столбца нет, оставьте пустым: возьмём часовой расход × часы работы.' },
  { key: 'hourly', label: 'Часовой расход', help: 'Нужен только если нет суточного расхода (м³/ч).' },
  { key: 'hours', label: 'Часы работы за сутки', help: 'Сколько часов скважина работала в эти сутки. Можно не указывать.' },
  { key: 'kind', label: 'Закачка или отбор', help: 'Столбец, где написано, что делала скважина. Если такого столбца нет, выберите вид ниже.' },
  { key: 'group', label: 'Группа скважины (необязательно)', help: 'Столбец с группой, к которой относится скважина (например, ГСП). Скважинам проекта без группы группа назначится при загрузке истории. Можно не указывать.' },
]
const empty = (): Template => ({ name: '', sheet: null, header_row: 0, well: '', date: '', rate: '', hourly: '', hours: '', kind: '', group: '', kind_default: '', unit: 'м3/сут', layout: 'table' })

function Step({ n, title, lead, children }: { n: number; title: string; lead?: string; children: React.ReactNode }) {
  return (
    <section className="card step">
      <div className="step-head"><span className="step-n">{n}</span><h2>{title}</h2></div>
      {lead && <p className="lead">{lead}</p>}
      {children}
    </section>
  )
}

/** Мастер столбцов: показывает файл и сопоставляет столбцы; нужен только для нестандартных таблиц. */
export default function ColumnWizard({ st, setSt, initialPath, onClose }:
  { st: AppState; setSt: (s: AppState) => void; initialPath: string; onClose: () => void }) {
  const [path, setPath] = useState(initialPath)
  const [pv, setPv] = useState<Preview | null>(null)
  const [tpl, setTpl] = useState<Template>(empty())
  const [trial, setTrial] = useState<Trial | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
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
  useEffect(() => { if (initialPath.trim()) open() }, [])  // eslint-disable-line react-hooks/exhaustive-deps
  const pick = () => guard(async () => {
    const r = await pickFile(path)
    if (r.path) setPath(r.path)
  })
  const set = (k: keyof Template, v: string | number) => { setTpl(t => ({ ...t, [k]: v })); setTrial(null) }
  const test = () => guard(async () => { setTrial(await runTrial(path.trim(), tpl)) })
  const save = () => guard(async () => { setSt(await saveTemplate(tpl)); setMsg('Шаблон «' + tpl.name + '» сохранён в проекте: такие файлы дальше читаются сами.') })
  const remove = (name: string) => guard(async () => { setSt(await deleteTemplate(name)) })
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
    <section className="card wizard">
      <div className="row between">
        <h2>Настройка столбцов базы расходов</h2>
        <button onClick={onClose}>Закрыть</button>
      </div>
      <p className="muted small">Нужна только для нестандартных таблиц: знакомые файлы программа читает сама. Сохранённый шаблон потом применяется ко всем похожим файлам.</p>
      {msg && <p className="note warn">{msg}</p>}
          {st && st.templates.length > 0 && (
            <section className="card">
              <h2>Сохранённые шаблоны</h2>
              <p className="muted small">Шаблон запоминает, в каких столбцах что лежит. Нажмите на название, чтобы применить его к файлу ниже.</p>
              <div className="tpl-list">{st.templates.map(t => (
                <span key={t.name} className="tpl-chip">
                  <button className="link" onClick={() => { setTpl(t); setTrial(null) }}>{t.name}</button>
                  <button className="x" title="Удалить шаблон" aria-label={'Удалить шаблон ' + t.name} onClick={() => remove(t.name)}>×</button>
                </span>))}</div>
            </section>)}
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
                    {trial.groups && trial.groups.wells > 0 && <> Групп найдено: <b>{trial.groups.groups}</b> (у {trial.groups.wells} скважин).</>}
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
    </section>
  )
}
