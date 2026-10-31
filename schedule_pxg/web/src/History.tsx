import { useEffect, useState } from 'react'

import PageHead from './PageHead'
import { AppState, HistoryBody, HistoryView, downloadHistoryLog, downloadHistoryResidual, downloadHistorySchedule, pickFile, runHistory } from './api'
import { Tables } from '../../../pxg_core/web-ui/table/Tables'
import { tableOf } from '../../../pxg_core/web-ui/table/tableBuild'

const KINDS: Record<string, string> = { закачка: 'закачка', отбор: 'отбор', нейтральный: 'нейтральный' }
const fmt = (x: number) => Math.round(x).toLocaleString('ru-RU')

export default function History({ st }: { st: AppState }) {
  const [mode, setMode] = useState<'daily' | 'dates'>('daily')
  const [dates, setDates] = useState('')
  const [periods, setPeriods] = useState('')
  const [pzrg, setPzrg] = useState('')
  const [split, setSplit] = useState(true)
  const [stitch, setStitch] = useState('')
  const [winLo, setWinLo] = useState('80')
  const [winHi, setWinHi] = useState('600')
  const [view, setView] = useState<HistoryView | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (st.pzrg_window) { setWinLo(String(st.pzrg_window.lo)); setWinHi(String(st.pzrg_window.hi)) } }, [st.pzrg_window])

  const body = (): HistoryBody => ({
    window_lo: winLo, window_hi: winHi,
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
          <label title="Скважины с дебитом вне окна при поправке по ПЗРГ не меняются, невязка уходит скважинам в окне. Окно запоминается в проекте.">
            Окно рабочего дебита, тыс. м³/сут: от{' '}
            <input style={{ width: 70 }} value={winLo} onChange={e => setWinLo(e.target.value)} /></label>
          <label>до <input style={{ width: 70 }} value={winHi} onChange={e => setWinHi(e.target.value)} /></label>
          <span className="muted small">скважины вне окна при поправке не меняются</span>
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
          {view?.residual && <button disabled={busy} onClick={() => guard(() => downloadHistoryResidual(body()))}>Невязка по суткам (CSV)</button>}
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
            Наибольшее расхождение с ПЗРГ после поправки: {view.correction.worst.toFixed(2)} %.
            {view.window && <> Окно рабочего дебита: {view.window.lo}–{view.window.hi} тыс. м³/сут.</>}
            {view.correction.unallocated > 0 && <> Не распределено (нечему): {fmt(view.correction.unallocated)} м³.</>}</p>
          <Tables scope="sched-history-log" tables={[tableOf('log', 'Журнал поправки по периодам',
            [['С', 'date'], ['По', 'date'], 'Метод', ['ПЗРГ, м³', 'number', 0], ['Коэфф.', 'number', 4], ['После, м³', 'number', 0], ['Расхожд., %', 'number', 2], ['Не распред., м³', 'number', 0], 'Комментарий'],
            view.log.map(r => [r.start, r.end, r.method, r.pzrg, r.coef, r.total_after, r.discrepancy, r.unallocated > 0 ? r.unallocated : null, r.comment]))]} />
        </>}
        {view.residual && <>
          <h3>Невязка по суткам (до поправки)</h3>
          <p className="note">{view.residual.summary.verdict} Суток: {view.residual.summary.days}, с невязкой от 2 %: {view.residual.summary.over},
            медиана {view.residual.summary.median.toFixed(1)} %, разброс {view.residual.summary.spread.toFixed(1)} п. п.</p>
          {view.residual.rows.length > 0 && <>
            <p className="muted small">Сутки с невязкой от 2 %{view.residual.total > view.residual.shown && <> — {view.residual.shown} самых больших из {view.residual.total}</>}; все сутки — в CSV.
              «За 3 суток» — невязка по сумме трёх соседних суток: если она мала, а за сутки велика, это сдвиг учётных суток, а не ошибка скважин.</p>
            <Tables scope="sched-history-residual" tables={[tableOf('residual', 'Невязка по суткам',
              [['Дата', 'date'], 'Вид', ['ПЗРГ, м³', 'number', 0], ['Скважины, м³', 'number', 0], ['Невязка, м³', 'number', 0], ['%', 'number', 1], ['За 3 суток, %', 'number', 1], 'Подсказка'],
              view.residual.rows.map(r => [r.date, KINDS[r.kind] || r.kind, r.pzrg, r.wells, r.residual, r.pct, r.pct3, r.hint]))]} />
          </>}
        </>}
        <h3>Шаги{view.table.length < view.steps && <span className="muted small"> — первые {view.table.length} из {view.steps}</span>}</h3>
        <Tables scope="sched-history-steps" tables={[tableOf('steps', 'Шаги', [['С', 'date'], ['По', 'date'], 'Вид', ['Скважин', 'number', 0], ['Расход, м³/сут', 'number', 0], ['Объём шага, м³', 'number', 0]],
          view.table.map(r => [r[0], r[1], r[2], r[3], r[4], r[5]]))]} />
      </section>}
    </main>
  )
}
