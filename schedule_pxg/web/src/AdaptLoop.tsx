import { useEffect, useRef, useState } from 'react'
import AdaptDashboard from './AdaptDashboard'
import { AdaptRequest, LoopInfo, LoopOpts, LoopState, getLoopInfo, getLoopStatus, loopInclude, pickFile, pickFolder, startLoop, stopLoop } from './api'

const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const STATUS: Record<string, string> = { idle: 'не запущен', running: 'идёт', done: 'завершён', failed: 'ошибка', cancelled: 'остановлен' }
const METRIC: Record<string, string> = { regimes: 'депрессия по режимам ГДИ', dp2: 'ΔP² (A и B)' }

/** Шаг 7 вкладки «Адаптация по ГДИ»: автоцикл по тестовому прогону модели (подбор → прогон tNavigator → чтение → порог). Решение за инженером. */
export default function AdaptLoop({ req, wells, kit }: { req: () => AdaptRequest; wells: string[]; kit: string }) {
  const [info, setInfo] = useState<LoopInfo | null>(null)
  const [o, setO] = useState<Partial<LoopOpts>>({ threshold_pct: 10, max_iter: 6, metric: 'regimes', restart: '' })
  const [id, setId] = useState('')
  const [st, setSt] = useState<LoopState | null>(null)
  const [well, setWell] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const guard = async (f: () => Promise<void>) => { setBusy(true); setMsg(''); try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) } }
  const upd = <K extends keyof LoopOpts>(k: K, v: LoopOpts[K]) => setO(x => ({ ...x, [k]: v }))

  useEffect(() => { getLoopInfo().then(i => { setInfo(i); setO(x => ({ ...x, ...i.saved })); const run = i.loops[i.loops.length - 1]; if (run) setId(run.id) }).catch(e => setMsg((e as Error).message)) }, [])
  useEffect(() => {
    window.clearInterval(timer.current)
    if (!id) return
    const tick = () => getLoopStatus(id).then(s => { setSt(s); if (s.status !== 'running') window.clearInterval(timer.current) }).catch(e => setMsg((e as Error).message))
    tick()
    timer.current = window.setInterval(tick, 2500)
    return () => window.clearInterval(timer.current)
  }, [id])
  useEffect(() => { if (st && !well) setWell(st.wells[0] || '') }, [st, well])

  const start = () => guard(async () => { const r = await startLoop(req(), { ...o, threshold_pct: Number(o.threshold_pct), max_iter: Number(o.max_iter), wells }); setSt(null); setWell(''); setId(r.id) })
  const stop = () => guard(async () => { await stopLoop(id) })
  const write = (k: number) => guard(async () => {
    const r = await loopInclude(id, k, o.workdir || kit)
    setMsg('Итерация ' + k + ': include записан в ' + r.path + ' (' + r.wells + ' скв.). Вставьте его в модель вручную или через копию .data; журнал мультов обновлён.')
  })
  const running = st?.status === 'running'
  return (
    <section className="card">
      <div className="step-head"><span className="step-n">7</span><h2>Подбор по модели (автоцикл)</h2></div>
      <p className="lead">Тестовый прогон копии модели: на дату ГДИ скважина задаётся дебитами режимов ГДИ, из результатов берётся депрессия Pпл − Pзаб и сравнивается с ГДИ режим за режимом. Мульты уточняются, пока ошибка не уложится в порог. Оригинал модели не меняется. Автоподбор лишь предлагает значения: решение по каждой скважине за вами.</p>
      <div className="row">
        <label className="grow">Программа tNavigator (Windows: tNavigator*.exe, РЕД ОС: tNavigator-con)
          <input value={o.exe || ''} onChange={e => upd('exe', e.target.value)} list="tnav-exe" placeholder="Путь к исполняемому файлу" />
          <datalist id="tnav-exe">{(info?.candidates || []).map(c => <option key={c} value={c} />)}</datalist></label>
        <button disabled={busy} onClick={() => guard(async () => { const r = await pickFile(o.exe || ''); if (r.path) upd('exe', r.path) })}>Выбрать…</button>
      </div>
      <div className="row">
        <label className="grow">Модель (.data), оригинал только читается
          <input value={o.model || ''} onChange={e => upd('model', e.target.value)} placeholder="Путь к файлу .data модели" /></label>
        <button disabled={busy} onClick={() => guard(async () => { const r = await pickFile(o.model || ''); if (r.path) upd('model', r.path) })}>Выбрать…</button>
      </div>
      <div className="row">
        <label className="grow">Рабочая папка (сюда один раз копируются результаты модели, нужно столько же места, сколько занимает RESULTS)
          <input value={o.workdir || ''} onChange={e => upd('workdir', e.target.value)} placeholder="Пустая папка на диске с запасом места" /></label>
        <button disabled={busy} onClick={() => guard(async () => { const d = await pickFolder(o.workdir || ''); if (d) upd('workdir', d) })}>Выбрать папку…</button>
      </div>
      <div className="row">
        <label>Шаг рестарта<input style={{ width: 90 }} value={o.restart || ''} onChange={e => upd('restart', e.target.value)} placeholder="номер" /></label>
        <label>Дата ГДИ (пусто — самая свежая)<input style={{ width: 130 }} value={o.date || ''} onChange={e => upd('date', e.target.value)} placeholder="ГГГГ-ММ-ДД" /></label>
        <label>Мера<select value={o.metric} onChange={e => upd('metric', e.target.value as 'regimes' | 'dp2')}>
          {Object.entries(METRIC).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>Порог, %<input style={{ width: 70 }} value={o.threshold_pct ?? ''} onChange={e => upd('threshold_pct', e.target.value as unknown as number)} /></label>
        <label>Макс. итераций<input style={{ width: 70 }} value={o.max_iter ?? ''} onChange={e => upd('max_iter', e.target.value as unknown as number)} /></label>
      </div>
      <p className="muted small">Шаг рестарта — номер шага результатов модели перед датой ГДИ (в tNavigator он виден в списке шагов расчёта). Один прогон занимает минуты, а не часы. Порог по скважине можно задать в настройках критерия депрессии, он приоритетнее общего.</p>
      <div className="row">
        <button className="primary" onClick={start} disabled={busy || running || !o.exe || !o.model || !o.workdir || !wells.length}>Запустить автоцикл</button>
        <button onClick={stop} disabled={!running}>Остановить</button>
        {st && <span className={st.status === 'failed' ? 'bad' : 'muted'}>{STATUS[st.status]}{st.message ? ': ' + st.message : ''}{st.stop_reason ? ' · ' + st.stop_reason : ''}</span>}
      </div>
      {!wells.length && <p className="muted small">Сначала выполните шаг 4: отберите скважины.</p>}
      {msg && <p className="note">{msg}</p>}
      {st?.job && running && <p className="muted small">tNavigator: шаг {st.job.step || '…'}, {fmt(st.job.seconds, 0)} с</p>}
      {st?.skipped_dates && st.skipped_dates.length > 0 && <p className="muted small">Один цикл ведётся по одной дате ГДИ: скважины с другой датой ({st.skipped_dates.join(', ')}) пропущены; запустите цикл для их даты отдельно.</p>}
      {st?.skipped && Object.entries(st.skipped).map(([w, r]) => <p key={w} className="muted small">Скв. {w}: {r}</p>)}

      {st && st.iterations.length > 0 && <AdaptDashboard st={st} well={well} setWell={setWell} write={write} busy={busy} />}
    </section>
  )
}
