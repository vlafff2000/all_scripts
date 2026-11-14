import { useEffect, useRef, useState } from 'react'
import AdaptDashboard from './AdaptDashboard'
import { Tables } from '../../../pxg_core/web-ui/table/Tables'
import { tableOf } from '../../../pxg_core/web-ui/table/tableBuild'
import { AdaptRequest, BatchState, LoopInfo, LoopOpts, LoopState, getLoopInfo, getLoopStatus, loopInclude, pickFile, pickFolder, startLoop, stopLoop } from './api'

const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const STATUS: Record<string, string> = { idle: 'не запущен', running: 'идёт', done: 'завершён', failed: 'ошибка', cancelled: 'остановлен' }
const METRIC: Record<string, string> = { regimes: 'депрессия по режимам ГДИ', dp2: 'ΔP² (A и B)' }

/** Шаг 7 вкладки «Адаптация по ГДИ»: автоцикл по тестовому прогону модели (подбор → прогон tNavigator → чтение → порог). Решение за инженером. */
export default function AdaptLoop({ req, wells, kit }: { req: () => AdaptRequest; wells: string[]; kit: string }) {
  const [info, setInfo] = useState<LoopInfo | null>(null)
  const [o, setO] = useState<Partial<LoopOpts>>({ threshold_pct: 10, max_iter: 6, metric: 'regimes' })
  const [id, setId] = useState('')
  const [st, setSt] = useState<LoopState | null>(null)
  const [bs, setBs] = useState<BatchState | null>(null)
  const [selDate, setSelDate] = useState('')
  const [well, setWell] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const guard = async (f: () => Promise<void>) => { setBusy(true); setMsg(''); try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) } }
  const upd = <K extends keyof LoopOpts>(k: K, v: LoopOpts[K]) => setO(x => ({ ...x, [k]: v }))

  useEffect(() => { getLoopInfo().then(i => { setInfo(i); setO(x => ({ ...x, ...i.saved, exe: i.saved.exe || '', model: i.saved.model || '', workdir: i.saved.workdir || '' })); const run = i.loops[i.loops.length - 1]; if (run) setId(run.id) }).catch(e => setMsg((e as Error).message)) }, [])
  useEffect(() => {
    window.clearInterval(timer.current)
    if (!id) return
    const tick = () => getLoopStatus(id).then(async s => {
      if (s.dates) {                                    // очередь по датам: состояние цикла выбранной даты запрашивается отдельно
        setBs(s as BatchState)
        const d = selDate || (s.dates.find(x => x.status === 'running') || s.dates[s.dates.length - 1])?.date
        if (d) { try { setSt(await getLoopStatus(id, d)) } catch { setSt(null) } }
      } else { setBs(null); setSt(s) }
      if (s.status !== 'running') window.clearInterval(timer.current)
    }).catch(e => setMsg((e as Error).message))
    tick()
    timer.current = window.setInterval(tick, 2500)
    return () => window.clearInterval(timer.current)
  }, [id, selDate])
  useEffect(() => { if (st && !well) setWell(st.wells[0] || '') }, [st, well])

  const d = info?.defaults
  const eff = { exe: o.exe || d?.exe || '', model: o.model || d?.model || '', workdir: o.workdir || d?.workdir || '' }
  const start = () => guard(async () => {
    // пустые поля = «определить само» (сервер подставит найденное); заданное руками уходит как есть
    const r = await startLoop(req(), { ...o, batch: o.batch !== false, threshold_pct: Number(o.threshold_pct), max_iter: Number(o.max_iter), wells })
    setSt(null); setBs(null); setSelDate(''); setWell(''); setId(r.id)
  })
  const stop = () => guard(async () => { await stopLoop(id) })
  const write = (k: number) => guard(async () => {
    const r = await loopInclude(id, k, eff.workdir || kit)
    setMsg('Include записан в ' + r.path + ' (' + r.wells + ' скв.). Вставьте его в модель: журнал мультов обновлён.')
  })
  const running = (bs?.status ?? st?.status) === 'running'
  const missing = [!wells.length && 'Отберите скважины на шаге 4', !eff.model && 'не найден файл модели .data: укажите его в «Дополнительно»', !eff.exe && 'не найден tNavigator: укажите его в «Дополнительно»'].filter(Boolean) as string[]
  const finished = !!bs && !running && bs.dates.length > 0 && bs.dates.every(x => x.status === 'done' || x.status === 'accepted')
  const results = bs ? bs.dates.flatMap(x => Object.values(x.results)) : []
  const doneDates = bs ? bs.dates.filter(x => x.status === 'done' || x.status === 'accepted').length : 0
  return (
    <section className="card">
      <div className="step-head"><span className="step-n">5</span><h2>Запустить адаптацию</h2></div>
      <p className="lead">Одна кнопка. Программа сама гоняет копию модели по датам ГДИ (рестарт с нужного шага, дебиты режимов ГДИ), сравнивает депрессию с ГДИ и уточняет мульты, пока ошибка не уложится в порог. Оригинал модели не меняется. Всё найденное ниже можно изменить в «Дополнительно»: решение за вами.</p>
      <ul className="small" style={{ margin: '4px 0 10px', paddingLeft: 18 }}>
        <li>Скважин в расчёте: <b>{wells.length}</b> (из шага 4)</li>
        <li>Модель: <b>{eff.model || 'не найдена'}</b>{!o.model && d?.model ? ' (определена по результатам сценария)' : ''}</li>
        <li>tNavigator: <b>{eff.exe || 'не найден'}</b></li>
        <li>Рабочая папка: <b>{eff.workdir}</b>{d?.work_exists ? ' (копия результатов уже есть)' : d?.results_gb ? ' (один раз скопируются результаты модели ≈ ' + fmt(d.results_gb, 0) + ' ГБ' + (d.free_gb !== null && d.free_gb !== undefined ? ', свободно ' + fmt(d.free_gb, 0) + ' ГБ' : '') + ')' : ''}</li>
        <li>Даты ГДИ: все по очереди, от поздних к ранним; шаг рестарта определяется сам. Порог ошибки: {fmt(Number(o.threshold_pct), 1)} %</li>
      </ul>
      <div className="row">
        <button className="primary" onClick={start} disabled={busy || running || missing.length > 0}>Запустить адаптацию</button>
        <button onClick={stop} disabled={!running}>Остановить</button>
        {bs && <span className={bs.status === 'failed' ? 'bad' : 'muted'}>{running ? 'Дата ' + Math.min(doneDates + 1, bs.dates.length) + ' из ' + bs.dates.length : STATUS[bs.status]}{bs.message ? ': ' + bs.message : ''}{bs.stop_reason && bs.status !== 'done' ? ' · ' + bs.stop_reason : ''}</span>}
        {!bs && st && <span className={st.status === 'failed' ? 'bad' : 'muted'}>{STATUS[st.status]}{st.message ? ': ' + st.message : ''}{st.stop_reason ? ' · ' + st.stop_reason : ''}</span>}
      </div>
      {missing.length > 0 && <p className="muted small">{missing.join('; ')}.</p>}
      {finished && <p className="note">Готово: скважин с подобранными мультами {results.length}, ошибка депрессии в среднем {fmt(results.length ? results.reduce((a, r) => a + (r.err ?? 0), 0) / results.length : null, 1)} %. Проверьте таблицу ниже и запишите include в модель.</p>}
      {finished && <div className="row"><button className="primary" disabled={busy} onClick={() => write(0)}>Записать include (все даты)</button></div>}

      <details>
        <summary className="muted">Дополнительно</summary>
        <div className="row">
          <label className="grow">Программа tNavigator (Windows: tNavigator*.exe, РЕД ОС: tNavigator-con)
            <input value={o.exe || ''} onChange={e => upd('exe', e.target.value)} list="tnav-exe" placeholder={d?.exe || 'Путь к исполняемому файлу'} />
            <datalist id="tnav-exe">{(info?.candidates || []).map(c => <option key={c} value={c} />)}</datalist></label>
          <button disabled={busy} onClick={() => guard(async () => { const r = await pickFile(eff.exe); if (r.path) upd('exe', r.path) })}>Выбрать…</button>
        </div>
        <div className="row">
          <label className="grow">Модель (.data), оригинал только читается
            <input value={o.model || ''} onChange={e => upd('model', e.target.value)} placeholder={d?.model || 'Путь к файлу .data модели'} /></label>
          <button disabled={busy} onClick={() => guard(async () => { const r = await pickFile(eff.model); if (r.path) upd('model', r.path) })}>Выбрать…</button>
        </div>
        <div className="row">
          <label className="grow">Рабочая папка (копия результатов модели, нужно столько места, сколько занимает RESULTS)
            <input value={o.workdir || ''} onChange={e => upd('workdir', e.target.value)} placeholder={d?.workdir || 'Папка на диске с запасом места'} /></label>
          <button disabled={busy} onClick={() => guard(async () => { const f = await pickFolder(eff.workdir); if (f) upd('workdir', f) })}>Выбрать папку…</button>
        </div>
        <div className="row">
          <label>Порог, %<input style={{ width: 70 }} value={o.threshold_pct ?? ''} onChange={e => upd('threshold_pct', e.target.value as unknown as number)} /></label>
          <label>Макс. итераций на дату<input style={{ width: 70 }} value={o.max_iter ?? ''} onChange={e => upd('max_iter', e.target.value as unknown as number)} /></label>
          <label>Мера<select value={o.metric} onChange={e => upd('metric', e.target.value as 'regimes' | 'dp2')}>
            {Object.entries(METRIC).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>Одна дата (пусто — все)<input style={{ width: 130 }} value={o.date || ''} onChange={e => { upd('date', e.target.value); upd('batch', !e.target.value) }} placeholder="ГГГГ-ММ-ДД" /></label>
          <label>Шаг рестарта вручную<input style={{ width: 90 }} value={o.restart || ''} onChange={e => upd('restart', e.target.value)} placeholder="авто" /></label>
        </div>
        <div className="row">
          <label className="grow">Снимки модели (папка запуска или snapshots.pkl из калькулятора), необязательно: тогда базовый прогон на дату не нужен
            <input value={o.snapshots || ''} onChange={e => upd('snapshots', e.target.value)} placeholder={d?.snapshots || 'не заданы: базовый прогон делается сам'} /></label>
          <label title="Нужны снимки модели: скважины, у которых формула уже обещает ошибку в пределах порога, принимаются без прогона"><input type="checkbox" checked={!!o.accept_formula} onChange={e => upd('accept_formula', e.target.checked)} /> Принять по формуле без прогона</label>
        </div>
        <p className="muted small">Шаг рестарта берётся из журнала расчёта модели (RESULTS/*.job.log); вручную нужен только если журнала нет. Прогоны идут строго по одному, от поздних дат к ранним (рестарт с ранней даты перезаписывает шаги, нужные для поздних). Порог по скважине задаётся в настройках критерия депрессии и приоритетнее общего.</p>
      </details>
      {msg && <p className="note">{msg}</p>}
      {st?.job && running && <p className="muted small">tNavigator: шаг {st.job.step || '…'}, {fmt(st.job.seconds, 0)} с</p>}
      {st?.skipped_dates && st.skipped_dates.length > 0 && <p className="muted small">Один цикл ведётся по одной дате ГДИ: скважины с другой датой ({st.skipped_dates.join(', ')}) пропущены; запустите цикл для их даты отдельно.</p>}
      {st?.skipped && Object.entries(st.skipped).map(([w, r]) => <p key={w} className="muted small">Скв. {w}: {r}</p>)}

      {bs && <>
        <h3>Очередь по датам ({bs.dates.filter(d => d.status === 'done' || d.status === 'accepted').length} из {bs.dates.length})</h3>
        <Tables scope="adapt-batch" tables={[tableOf('adapt-batch', 'Очередь', [['Дата ГДИ', 'text'], ['Скважин', 'number', 0], ['Статус', 'text'], ['Прогонов', 'number', 0], ['Макс. ошибка, %', 'number', 1], ['Примечание', 'text']],
          bs.dates.map(d => [d.date, d.wells.length, { queued: 'в очереди', running: 'идёт', done: 'готово', accepted: 'принято по формуле', failed: 'ошибка' }[d.status], d.runs,
            Object.values(d.results).reduce((m, r) => (r.err === null ? m : Math.max(m, r.err)), 0) || null, d.message || '']))]}
          onRow={(_t, i) => { setSelDate(bs.dates[i].date); setWell('') }} />
        <p className="muted small">Нажмите на строку, чтобы открыть дашборд этой даты. «Записать include» для очереди собирает один файл по всем датам.</p>
        <div className="row"><button disabled={busy} onClick={() => write(0)}>Записать include очереди (все даты)</button></div>
      </>}
      {st && st.iterations.length > 0 && <AdaptDashboard st={st} well={well} setWell={setWell} write={write} busy={busy} />}
    </section>
  )
}
