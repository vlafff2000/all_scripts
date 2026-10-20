import { useEffect, useMemo, useState } from 'react'
import PageHead from './PageHead'
import AdaptResults from './AdaptResults'
import {
  AdaptColCheck, AdaptColumns, AdaptConfig, adaptCheckColumns, adaptCode, AdaptRequest, AdaptSelection, AdaptSettings, AdaptState, adaptKit, adaptSelect, getAdapt, getAdaptColumns, pickFile, pickFolder,
} from './api'

const ROLES: [string, string][] = [['well', 'Скважина'], ['date', 'Дата'], ['wbp', 'Рпл'], ['bhp', 'Рзаб'], ['q', 'Дебит']]
const STRATEGIES: [string, string][] = [['andrey', 'Сохранить ΔP² ГДИ при пластовом давлении модели'], ['dp', 'Депрессия как в ГДИ'], ['pzab', 'Рпл модели минус Рзаб ГДИ']]
const P_UNITS: Record<string, string> = { 'kgf/cm2': 'кгс/см² (абс.)', bar: 'бар (абс.)', MPa: 'МПа (абс.)' }
const Q_UNITS: Record<string, string> = { '10^3 m3/day': 'тыс. м³/сут', 'm3/day': 'м³/сут' }
const num = (s: string): number | undefined => { const v = Number(s.replace(',', '.')); return s.trim() !== '' && Number.isFinite(v) ? v : undefined }
const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const STATUS: Record<string, string> = { good: 'хорошее', fair: 'удовлетворительное', bad: 'забраковано' }
/** Решение по исследованию: 'auto' - как решила программа, 'on' - брать, 'off' - не брать. */
type Decision = 'auto' | 'on' | 'off'
const DECISION_TITLE: Record<Decision, string> = { auto: 'Как решила программа', on: 'Брать', off: 'Не брать' }
const decisionOf = (m: boolean | null | undefined): Decision => (m === null || m === undefined ? 'auto' : m ? 'on' : 'off')

/** Вкладка «Адаптация по ГДИ», шаг 1: подготовка. БД ГДИ → отбор исследований → комплект для тНавигатора. */
export default function Adapt() {
  const [st, setSt] = useState<AdaptState | null>(null)
  const [db, setDb] = useState('')
  const [colsInfo, setColsInfo] = useState<AdaptColumns | null>(null)
  const [cols, setCols] = useState<Record<string, string>>({})
  const [settings, setSettings] = useState<Partial<AdaptSettings>>({})
  const [config, setConfig] = useState<Partial<AdaptConfig>>({})
  const [scenario, setScenario] = useState('')
  const [overrides, setOverrides] = useState<Record<string, boolean>>({})
  const [studyOv, setStudyOv] = useState<Record<string, boolean>>({})
  const [sel, setSel] = useState<AdaptSelection | null>(null)
  const [filter, setFilter] = useState('all')
  const [out, setOut] = useState('')
  const [kit, setKit] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [check, setCheck] = useState<AdaptColCheck | null>(null)
  const [code, setCode] = useState('')

  const guard = async (f: () => Promise<void>) => { setBusy(true); setMsg(''); try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) } }
  useEffect(() => {
    getAdapt().then(s => {
      setSt(s); setKit(s.kit); setOut(s.kit); setDb(s.db); setCols(s.cols); setSettings(s.saved_settings); setConfig(s.saved_config); setOverrides(s.overrides); setStudyOv(s.study_overrides || {})
      setScenario(s.scenario || s.scenarios.find(x => x.path)?.name || '')
      if (s.db) getAdaptColumns(s.db, s.sheet).then(setColsInfo).catch(() => undefined)
    }).catch(e => setMsg((e as Error).message))
  }, [])

  const cfg = { ...(st?.config || {}), ...config } as AdaptConfig
  const set = { ...(st?.settings || {}), ...settings } as AdaptSettings
  const upd = <K extends keyof AdaptConfig>(k: K, v: AdaptConfig[K]) => setConfig(c => ({ ...c, [k]: v }))
  const req = (): AdaptRequest => ({ db, sheet: st?.sheet || '', cols, settings: set, config: cfg, overrides, study_overrides: studyOv, scenario })
  const applyCols = () => guard(async () => { setCheck(await adaptCheckColumns({ db, sheet: st?.sheet || '', cols })) })
  const copyCode = () => guard(async () => {
    const r = await adaptCode(kit)
    setCode(r.code)
    try { await navigator.clipboard.writeText(r.code); setMsg('Код скопирован. Вставьте его в python-секцию тНавигатора и запустите.') }
    catch { setMsg('Браузер не дал скопировать сам: выделите код в окне ниже (Ctrl+A) и скопируйте (Ctrl+C).') }
  })

  const pick = () => guard(async () => {
    const r = await pickFile(db)
    if (!r.path) return
    setDb(r.path); setSel(null)
    const c = await getAdaptColumns(r.path)
    setColsInfo(c); setCols(c.detected)
  })
  const run = (o = overrides, so = studyOv) => guard(async () => { const r = await adaptSelect({ ...req(), overrides: o, study_overrides: so }); setSel(r); setCols(r.cols) })
  const toggle = (well: string, on: boolean) => { const o = { ...overrides, [well]: on }; setOverrides(o); run(o) }
  /** Ручное решение по исследованию; «Как решила программа» убирает его из сохранённых решений. */
  const decide = (key: string, d: Decision) => {
    const so = { ...studyOv }
    if (d === 'auto') delete so[key]; else so[key] = d === 'on'
    setStudyOv(so); run(overrides, so)
  }
  const resetDecisions = () => { setStudyOv({}); run(overrides, {}) }
  const bound = (well: string, key: 'pi_mult_bounds' | 'dfac_bounds', idx: 0 | 1, s: string) => {
    const wb = { ...(cfg.well_bounds || {}) }
    const cur = { ...(wb[well] || {}) }
    const base = (cur[key] || cfg[key]) as [number, number]
    const v = num(s)
    if (v === undefined) { delete cur[key] } else { const arr = [...base] as [number, number]; arr[idx] = v; cur[key] = arr }
    if (Object.keys(cur).length) wb[well] = cur; else delete wb[well]
    upd('well_bounds', Object.keys(wb).length ? wb : null)
  }
  const makeKit = () => guard(async () => {
    const dir = out || (await pickFolder(out))
    if (!dir) return
    setOut(dir)
    const r = await adaptKit({ ...req(), out: dir })
    setKit(dir)
    setCode(r.code)
    setMsg('Комплект готов: ' + r.folder + ', скважин: ' + r.wells.length + '. Дальше шаг 5: скопируйте код и запустите его в тНавигаторе.')
  })

  const rows = useMemo(() => (sel?.rows || []).filter(r =>
    filter === 'all' ? true : filter === 'on' ? r.include : filter === 'off' ? !r.include : filter === 'bad' ? r.note.startsWith('все ГДИ забракованы') : filter === 'nomodel' ? r.note === 'нет в модели' : true), [sel, filter])
  const pm = cfg.pi_mult_bounds || [1e-4, 1000]
  const dm = cfg.dfac_bounds || [0, 1e-4]

  if (!st) return <main className="workspace">{msg && <p className="note warn">{msg}</p>}</main>
  return (
    <main className="workspace">
      <PageHead title="Адаптация по ГДИ" lede="Подбираем для каждой скважины множитель продуктивности (WPIMULT) и D-фактор так, чтобы модель повторяла результаты ГДИ. Здесь готовим запуск: какие исследования и скважины брать, в каких границах подбирать." />

      <section className="card">
        <div className="step-head"><span className="step-n">1</span><h2>База ГДИ</h2></div>
        <p className="lead">Файл, который собрала «База ПХГ» (модуль «Преобразование таблиц ГДИ в базу»). Коэффициенты a и b берутся не из файла, а считаются заново по режимам.</p>
        <div className="row">
          <label className="grow">Файл<input value={db} onChange={e => setDb(e.target.value)} placeholder="Путь к БД ГДИ (.xlsx)" /></label>
          <button onClick={pick} disabled={busy}>Выбрать файл</button>
          {db && !colsInfo && <button onClick={() => guard(async () => { const c = await getAdaptColumns(db); setColsInfo(c); setCols(c.detected) })} disabled={busy}>Прочитать столбцы</button>}
        </div>
        {colsInfo && <div className="row">
          {ROLES.map(([k, title]) => <label key={k}>{title}
            <select value={cols[k] || ''} onChange={e => { setCols(c => ({ ...c, [k]: e.target.value })); setCheck(null) }}>
              <option value="">— не выбрано —</option>{colsInfo.columns.map(c => <option key={c}>{c}</option>)}</select></label>)}
          <label>Давление в файле<select value={set.p_units} onChange={e => setSettings(s => ({ ...s, p_units: e.target.value }))}>
            {st.p_units.map(u => <option key={u} value={u}>{P_UNITS[u] || u}</option>)}</select></label>
          <label>Дебит в файле<select value={set.q_units} onChange={e => setSettings(s => ({ ...s, q_units: e.target.value }))}>
            {st.q_units.map(u => <option key={u} value={u}>{Q_UNITS[u] || u}</option>)}</select></label>
        </div>}
        {colsInfo && <div className="row"><button onClick={applyCols} disabled={busy}>Применить столбцы</button>
          {check && <span className={check.ok ? 'ok' : 'warn'}>{check.ok ? 'Столбцы применены.' : 'Нужно поправить столбцы.'}</span>}</div>}
        {check && <div className="scroll"><table className="raw"><thead><tr><th>Роль</th><th>Столбец</th><th>Разобрано значений</th><th>Примеры</th></tr></thead>
          <tbody>{check.roles.map(r => <tr key={r.role} className={r.valid ? '' : 'warnrow'}><td>{r.title}</td><td>{r.col || '—'}</td><td>{r.valid} из {r.total}</td><td className="muted small">{r.examples.join(' · ')}</td></tr>)}</tbody></table>
          {check.problems.map((x, i) => <p key={i} className="note warn">{x}</p>)}</div>}
        {colsInfo && <p className="muted small">Строк в файле: {colsInfo.rows}. Давления должны быть абсолютными.</p>}
      </section>

      <section className="card">
        <div className="step-head"><span className="step-n">2</span><h2>Какие исследования брать</h2></div>
        <div className="row">
          <label>Модель (откуда взять скважины)<select value={scenario} onChange={e => setScenario(e.target.value)}>
            <option value="">— скважины проекта —</option>
            {st.scenarios.map(s => <option key={s.name} value={s.name} disabled={!s.path}>{s.name}{s.path ? '' : ' (нет результатов)'}</option>)}</select></label>
          <label>Допустимое качество ГДИ<select value={set.min_status} onChange={e => setSettings(s => ({ ...s, min_status: e.target.value }))}>
            <option value="fair">хорошее и удовлетворительное</option><option value="good">только хорошее</option></select></label>
          <label>Не старше, лет<input style={{ width: 90 }} value={set.max_age_years ?? ''} placeholder="без ограничения"
            onChange={e => setSettings(s => ({ ...s, max_age_years: num(e.target.value) ?? null }))} /></label>
        </div>
        <p className="muted small">По каждой скважине проверяется качество всех исследований; берётся самое свежее из прошедших проверку. Модель задаёт, какие скважины вообще можно адаптировать.</p>
      </section>

      <section className="card">
        <div className="step-head"><span className="step-n">3</span><h2>Настройки подбора</h2></div>
        <div className="row">
          <label className="grow">Что сохранять<select value={cfg.strategy} onChange={e => upd('strategy', e.target.value)}>
            {STRATEGIES.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
          <label>Приток<select value={cfg.inflow} onChange={e => upd('inflow', e.target.value)}><option value="p-p">псевдодавление</option><option value="r-g">Рассел — Гудрич</option></select></label>
          <label>Ошибка дебита<select value={cfg.objective} onChange={e => upd('objective', e.target.value)}><option value="relative">относительная</option><option value="absolute">абсолютная</option></select></label>
        </div>
        <div className="row">
          <label className="grow"><input type="checkbox" checked={!!cfg.all_dates} onChange={e => upd('all_dates', e.target.checked)} /> Настроить на все исследования скважины (динамика по датам)</label>
          <label><input type="checkbox" checked={cfg.include_sequential !== false} onChange={e => upd('include_sequential', e.target.checked)} /> В include — приращение WPIMULT (накопительный множитель)</label>
        </div>
        <p className="muted small">С динамикой в include для каждой даты ГДИ записывается свой WPIMULT; итог по дате считается от базовой модели, в файл идёт отношение к уже заданному ранее. Для строгой проверки подключите include к модели, пересчитайте её и повторите адаптацию — остаточный WPIMULT должен быть около 1.</p>
        <div className="row">
          <label>WPIMULT от<input style={{ width: 110 }} defaultValue={pm[0]} onBlur={e => { const v = num(e.target.value); if (v !== undefined) upd('pi_mult_bounds', [v, pm[1]]) }} /></label>
          <label>до<input style={{ width: 110 }} defaultValue={pm[1]} onBlur={e => { const v = num(e.target.value); if (v !== undefined) upd('pi_mult_bounds', [pm[0], v]) }} /></label>
          <label>D-фактор от<input style={{ width: 110 }} defaultValue={dm[0]} onBlur={e => { const v = num(e.target.value); if (v !== undefined) upd('dfac_bounds', [v, dm[1]]) }} /></label>
          <label>до<input style={{ width: 110 }} defaultValue={dm[1]} onBlur={e => { const v = num(e.target.value); if (v !== undefined) upd('dfac_bounds', [dm[0], v]) }} /></label>
          <label>R² ниже — замечание<input style={{ width: 80 }} defaultValue={cfg.r2_ok} onBlur={e => { const v = num(e.target.value); if (v !== undefined) upd('r2_ok', v) }} /></label>
          <label>Мин. режимов<input style={{ width: 80 }} defaultValue={cfg.min_regimes} onBlur={e => { const v = num(e.target.value); if (v !== undefined) upd('min_regimes', v) }} /></label>
        </div>
        <p className="muted small">Границы можно задать и для отдельной скважины в таблице ниже (пустое поле — общие границы).</p>
        <div className="row"><button className="primary" onClick={() => run()} disabled={busy || !db || !colsInfo}>Подобрать исследования и скважины</button></div>
        {msg && <p className="note">{msg}</p>}
      </section>

      {sel && <section className="card">
        <div className="step-head"><span className="step-n">4</span><h2>Скважины и исследования</h2></div>
        <p className="lead">Выбрано <b>{sel.counts.included}</b> из {sel.counts.wells_db} скважин БД ГДИ. Нет в модели: {sel.counts.no_model}; все ГДИ забракованы: {sel.counts.all_bad}; старше допустимого: {sel.counts.old}; в модели есть, а ГДИ нет: {sel.counts.model_only}.</p>
        <p className="lead">Ручных решений: <b>{sel.counts.manual}</b>{sel.counts.manual > 0 && <> · <button onClick={resetDecisions} disabled={busy}>Сбросить все ручные решения</button></>}</p>
        <p className="muted small">Программа лишь советует: замечания по качеству показаны в таблице исследований. Окончательное решение по каждому исследованию за инженером.</p>
        {sel.notes.map((n, i) => <p key={i} className="muted small">{n}</p>)}
        <div className="row">
          <label>Показать<select value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="all">все</option><option value="on">включённые</option><option value="off">выключенные</option>
            <option value="bad">все ГДИ забракованы</option><option value="nomodel">нет в модели</option></select></label>
          <button className="primary" onClick={makeKit} disabled={busy || !sel.counts.included}>Подготовить комплект для тНавигатора</button>
        </div>
        <div className="row">
          <label className="grow">Папка для комплекта (создайте или выберите пустую, например D:\PHG\gdi_kit)<input value={out} onChange={e => setOut(e.target.value)} placeholder="Куда сложить файлы для тНавигатора" /></label>
          <button onClick={() => guard(async () => { const d = await pickFolder(out); if (d) setOut(d) })} disabled={busy}>Выбрать папку…</button>
        </div>
        <p className="muted small">Файл выбирать не нужно: программа сама создаст в этой папке код и данные. Если папку не указать, откроется окно выбора папки.</p>
        <div className="scroll" style={{ maxHeight: 520 }}><table className="raw"><thead><tr>
          <th /><th>Скв. БД</th><th>В модели</th><th>ГДИ в БД</th><th>Прошли</th><th>Взято</th><th>Качество</th><th>Возраст, лет</th><th>Режимов</th><th>a</th><th>b</th>
          <th>WPIMULT от</th><th>до</th><th>D до</th><th>Примечание</th></tr></thead>
          <tbody>{rows.map(r => {
            const wb = cfg.well_bounds?.[r.well] || {}
            return <tr key={r.well} className={r.include ? '' : 'dim'}>
              <td><input type="checkbox" checked={r.include} disabled={busy || !r.date || !r.model} onChange={e => toggle(r.well, e.target.checked)} aria-label="Адаптировать скважину" /></td>
              <td>{r.well}</td><td>{r.model || '—'}</td><td>{r.n_studies}</td><td>{r.n_usable}</td><td>{r.date || '—'}</td><td>{STATUS[r.status] || ''}</td>
              <td>{fmt(r.age_years, 1)}</td><td>{r.n_regimes || ''}</td><td>{fmt(r.a, 4)}</td><td>{fmt(r.b, 5)}</td>
              <td><input style={{ width: 70 }} defaultValue={wb.pi_mult_bounds?.[0] ?? ''} placeholder={String(pm[0])} onBlur={e => bound(r.well, 'pi_mult_bounds', 0, e.target.value)} /></td>
              <td><input style={{ width: 70 }} defaultValue={wb.pi_mult_bounds?.[1] ?? ''} placeholder={String(pm[1])} onBlur={e => bound(r.well, 'pi_mult_bounds', 1, e.target.value)} /></td>
              <td><input style={{ width: 80 }} defaultValue={wb.dfac_bounds?.[1] ?? ''} placeholder={String(dm[1])} onBlur={e => bound(r.well, 'dfac_bounds', 1, e.target.value)} /></td>
              <td className="muted small">{r.note}</td></tr>
          })}</tbody></table></div>
        <h3>Исследования ГДИ</h3>
        <p className="muted small">Что решила программа, и почему. Выберите для каждого исследования: брать, не брать или оставить решение программы. Исследование, которое программа забраковала, можно взять вручную: замечание останется в таблице.</p>
        <div className="scroll" style={{ maxHeight: 420 }}><table className="raw"><thead><tr>
          <th>Скв. БД</th><th>В модели</th><th>Дата</th><th>Качество (программа)</th><th>Замечание программы</th><th>Решение инженера</th><th>В расчёте</th><th>Режимов</th><th>a</th><th>b</th></tr></thead>
          <tbody>{sel.studies.map(s => {
            const d = decisionOf(s.manual)
            return <tr key={s.key} className={s.use ? '' : 'dim'}>
              <td>{s.well}</td><td>{s.model || '—'}</td><td>{s.date}</td><td>{STATUS[s.status] || s.status}</td>
              <td className="muted small">{[s.reasons, s.warnings].filter(Boolean).join('; ') || '—'}</td>
              <td><select value={d} disabled={busy} onChange={e => decide(s.key, e.target.value as Decision)} aria-label="Решение по исследованию">
                {(Object.keys(DECISION_TITLE) as Decision[]).map(k => <option key={k} value={k}>{DECISION_TITLE[k]}</option>)}</select>
                {d !== 'auto' && <span className="muted small"> вручную</span>}</td>
              <td className={s.use ? 'ok' : ''}>{s.use ? 'да' : 'нет'}</td>
              <td>{s.n_regimes}</td><td>{fmt(s.a, 4)}</td><td>{fmt(s.b, 5)}</td></tr>
          })}</tbody></table></div>
        {sel.model_only.length > 0 && <p className="muted small">В модели есть, а исследований нет: {sel.model_only.slice(0, 60).join(', ')}{sel.model_only.length > 60 ? ' …' : ''}</p>}
      </section>}
      <section className="card">
        <div className="step-head"><span className="step-n">5</span><h2>Запуск в тНавигаторе</h2></div>
        <p className="lead">Один раз читаем данные модели по отобранным скважинам. Править код не нужно: путь к комплекту уже вписан.</p>
        <ol className="steps">
          <li>Нажмите «Копировать код».</li>
          <li>В тНавигаторе откройте «Шаблоны графиков», «калькулятор графиков» (тот же шаблон, где раньше работал скрипт адаптации), вставьте код и нажмите «Вычислить».</li>
          <li>Дождитесь строки «Готово» в консоли тНавигатора и вернитесь сюда: результаты читаются на шаге 6.</li>
        </ol>
        <div className="row"><button className="primary" onClick={copyCode} disabled={busy || !kit}>Копировать код</button>
          <span className="muted small">{kit ? 'Файл: ' + kit + (kit.includes('\\') ? '\\' : '/') + 'code.py' : 'Кнопка станет активной после шага 4: выберите скважины и нажмите «Подготовить комплект для тНавигатора».'}</span></div>
        {code && <textarea readOnly rows={8} value={code} onFocus={e => e.currentTarget.select()} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} />}
      </section>
      <AdaptResults kit={kit} config={cfg} />
    </main>
  )
}
