import { useState } from 'react'
import PageHead from './PageHead'
import { AppState, HistoryBody, HistoryView, downloadHistoryLog, downloadHistorySchedule, pickFile, runHistory } from './api'

const KINDS: Record<string, string> = { закачка: 'закачка', отбор: 'отбор', нейтральный: 'нейтральный' }
const fmt = (x: number) => Math.round(x).toLocaleString('ru-RU')

export default function History({ st }: { st: AppState }) {
  const [mode, setMode] = useState<'daily' | 'dates'>('daily')
  const [dates, setDates] = useState('')
  const [periods, setPeriods] = useState('')
  const [pzrg, setPzrg] = useState('')
  const [split, setSplit] = useState(true)
  const [stitch, setStitch] = useState('')
  const [view, setView] = useState<HistoryView | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const body = (): HistoryBody => ({
    mode, ...(mode === 'dates' ? { dates } : {}), ...(periods.trim() ? { periods } : {}), ...(pzrg.trim() ? { pzrg_file: pzrg.trim() } : {}),
    ...(split ? {} : { split: {} }), ...(stitch ? { stitch } : {}),
  })
  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const run = () => guard(async () => { setView(await runHistory(body())) })
  const pick = () => guard(async () => { const r = await pickFile(pzrg); if (r.path) setPzrg(r.path) })
  const ready = mode === 'daily' || dates.trim().length > 0

  return (
    <main className="workspace">
      <PageHead title="История" lede="Schedule по фактическим расходам: для расчёта на прошедший период." />
      <section className="card">
        <h2>Режим «история»</h2>
        <p className="muted small">Schedule по фактическим расходам из файлов осреднения (вкладка «Осреднение»). Два варианта сетки шагов — как у прежних скриптов.</p>
        <div className="row">
          <label><input type="radio" checked={mode === 'daily'} onChange={() => { setMode('daily'); setView(null) }} /> Шаг сутки</label>
          <label><input type="radio" checked={mode === 'dates'} onChange={() => { setMode('dates'); setView(null) }} /> По датам замеров</label>
        </div>
        {mode === 'dates' && <label>Даты замеров (по одной в строке, ДД.ММ.ГГГГ)<br />
          <textarea rows={6} style={{ width: '100%' }} value={dates} onChange={e => setDates(e.target.value)} placeholder={'01.05.2026\n15.05.2026'} /></label>}
        <label>Периоды закачки/отбора (необязательно: «ДД.ММ.ГГГГ закачка|отбор|нейтральный», период идёт до следующей строки)<br />
          <textarea rows={3} style={{ width: '100%' }} value={periods} onChange={e => setPeriods(e.target.value)} placeholder="Если пусто — вид берётся из самой истории" /></label>
        <div className="row">
          <input className="grow" value={pzrg} placeholder="Файл ПЗРГ для поправки (необязательно)" onChange={e => setPzrg(e.target.value)} />
          <button onClick={pick} disabled={busy}>Выбрать…</button>
        </div>
        <div className="row">
          <label><input type="checkbox" checked={split} onChange={e => setSplit(e.target.checked)} /> Скважину «54/80» делить пополам на 54 и 80</label>
          <label>Сшить с прогнозом сценария:{' '}
            <select value={stitch} onChange={e => { setStitch(e.target.value); setView(null) }}>
              <option value="">— без сшивки —</option>{st.scenarios.map(s => <option key={s.name}>{s.name}</option>)}</select></label>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="primary" disabled={busy || !ready} onClick={run}>Посчитать</button>
          {view && view.steps > 0 && <button disabled={busy} onClick={() => guard(() => downloadHistorySchedule(body()))}>Скачать schedule.inc</button>}
          {view?.correction && <button disabled={busy} onClick={() => guard(() => downloadHistoryLog(body()))}>Журнал поправки (CSV)</button>}
        </div>
        {msg && <p className="note warn">{msg}</p>}
      </section>

      {view && <section className="card">
        <h2>Результат</h2>
        <p className="note">
          Шагов: {view.steps}{view.from && <> · с {view.from} по {view.to}</>}. {Object.entries(view.kinds).map(([k, n]) => (KINDS[k] || k) + ': ' + n).join(', ')}.
          {view.sources.length > 0 && <> Файлы: {view.sources.join(', ')}.</>}
        </p>
        {Object.keys(view.volumes).length > 0 && <p className="muted small">Объём по шагам, м³: {Object.entries(view.volumes).filter(([, v]) => v > 0).map(([k, v]) => k + ' ' + fmt(v)).join('; ')}.</p>}
        {view.stitch.length > 0
          ? <ul className="issues">{view.stitch.map((n, i) => <li key={i} className="warn">{n}</li>)}</ul>
          : stitch && <p className="muted small">Стык истории и прогноза без дыр и наложений.</p>}
        {view.notes.length > 0 && <ul className="issues">{view.notes.map((n, i) => <li key={i} className="warn">{n}</li>)}</ul>}
        {view.correction && <>
          <h3>Поправка по ПЗРГ</h3>
          <p className="note">Периодов: {view.correction.periods}, поправлено: {view.correction.corrected}, пропущено: {view.correction.skipped}.
            Наибольшее расхождение с ПЗРГ после поправки: {view.correction.worst.toFixed(2)} %.</p>
          <table className="raw"><thead><tr><th>С</th><th>По</th><th>Метод</th><th>ПЗРГ, м³</th><th>Коэфф.</th><th>После, м³</th><th>Расхожд., %</th><th>Комментарий</th></tr></thead>
            <tbody>{view.log.map((r, i) => <tr key={i} className={r.method === 'SKIP' || r.category >= 2 ? 'bad' : ''}>
              <td>{r.start}</td><td>{r.end}</td><td>{r.method}</td><td className="num">{fmt(r.pzrg)}</td><td className="num">{r.coef.toFixed(4)}</td>
              <td className="num">{fmt(r.total_after)}</td><td className="num">{r.discrepancy.toFixed(2)}</td><td>{r.comment}</td></tr>)}</tbody></table>
        </>}
        <h3>Шаги{view.table.length < view.steps && <span className="muted small"> — первые {view.table.length} из {view.steps}</span>}</h3>
        <table className="raw"><thead><tr><th>С</th><th>По</th><th>Вид</th><th>Скважин</th><th>Расход, м³/сут</th><th>Объём шага, м³</th></tr></thead>
          <tbody>{view.table.map((r, i) => <tr key={i}><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td className="num">{r[3]}</td>
            <td className="num">{fmt(r[4])}</td><td className="num">{fmt(r[5])}</td></tr>)}</tbody></table>
      </section>}
    </main>
  )
}
