import { useEffect, useMemo, useRef, useState } from 'react'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import { AdaptRequest, LoopInfo, LoopIter, LoopOpts, LoopState, getLoopInfo, getLoopStatus, loopInclude, pickFile, pickFolder, startLoop, stopLoop } from './api'

const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const STATUS: Record<string, string> = { idle: 'не запущен', running: 'идёт', done: 'завершён', failed: 'ошибка', cancelled: 'остановлен' }
const METRIC: Record<string, string> = { regimes: 'депрессия по режимам ГДИ', dp2: 'ΔP² (A и B)' }

/** Лучшая итерация скважины с мультами (наименьшая ошибка). */
export const bestIter = (its: LoopIter[], w: string): LoopIter | undefined => {
  const c = its.filter(i => i.k > 0 && i.mults[w] && i.wells[w]?.err !== null && i.wells[w]?.err !== undefined)
  return c.length ? c.reduce((a, b) => ((b.wells[w].err as number) < (a.wells[w].err as number) ? b : a)) : undefined
}

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
  const its = st?.iterations || []
  const last = its[its.length - 1]
  const rows = useMemo(() => (st?.wells || []).map(w => {
    const b = bestIter(its, w)
    const base = its[0]?.wells[w]?.err ?? null
    const cur = last?.wells[w]?.err ?? null
    const thr = st?.thresholds[w] ?? 10
    const ok = b ? (b.wells[w].err as number) <= thr : null
    return { w, base, cur, best: b, thr, ok }
  }), [st, its, last])

  const chart = useMemo(() => {
    if (!well || !its.length) return null
    const ref = its[0].wells[well]
    if (!ref) return null
    const ser = [mkSeries({ name: 'ГДИ', kind: 'points', slot: 3, x: ref.q.map(q => q / 1000), y: ref.dep_gdi.map(v => v ?? NaN) })]
    its.forEach((it, i) => {
      const w = it.wells[well]
      if (w) ser.push(mkSeries({ name: it.k === 0 ? 'модель без мультов' : 'итерация ' + it.k, slot: i === 0 ? 5 : i - 1, dashed: i === 0, x: w.q.map(q => q / 1000), y: w.dep_model.map(v => v ?? NaN) }))
    })
    return mkChart('loop-dep', 'Депрессия по режимам ГДИ, скв. ' + well, mkAxis('Дебит', 'тыс. м³/сут'), mkAxis('Pпл − Pзаб', 'бар', 'value', { from_zero: true }), ser)
  }, [its, well])
  const errChart = useMemo(() => {
    if (!well || its.length < 2) return null
    const pts = its.filter(i => i.wells[well]?.err !== null && i.wells[well]?.err !== undefined)
    const thr = st?.thresholds[well]
    return mkChart('loop-err', 'Ошибка по итерациям, скв. ' + well, mkAxis('Итерация'), mkAxis(METRIC[st?.metric || 'regimes'], '%', 'value', { from_zero: true }), [
      mkSeries({ name: 'ошибка', kind: 'points', slot: 0, x: pts.map(i => i.k), y: pts.map(i => i.wells[well].err as number) }),
      { ...mkSeries({ name: 'линия', slot: 0, x: pts.map(i => i.k), y: pts.map(i => i.wells[well].err as number) }), legend: false },
      ...(thr === undefined ? [] : [mkSeries({ name: 'порог', slot: 5, dashed: true, x: pts.map(i => i.k), y: pts.map(() => thr) })])])
  }, [its, well, st])

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

      {st && rows.length > 0 && <>
        <h3>Сводка по скважинам ({st.date})</h3>
        <div className="scroll" style={{ maxHeight: 320 }}><table className="data-grid dense pick"><thead><tr>
          <th>Скв.</th><th>Ошибка до, %</th><th>Ошибка сейчас, %</th><th>Лучшая итерация</th><th>WPIMULT (итого)</th><th>D-фактор</th><th>Порог, %</th><th>Вывод</th></tr></thead>
          <tbody>{rows.map(r => {
            const m = r.best?.mults[r.w]
            return <tr key={r.w} className={r.w === well ? 'sel' : ''} onClick={() => setWell(r.w)} style={{ cursor: 'pointer' }}>
              <td>{r.w}</td><td>{fmt(r.base, 1)}</td><td>{fmt(r.cur, 1)}</td><td>{r.best ? r.best.k : '—'}</td>
              <td>{fmt(m?.inc, 4)}</td><td>{m?.d === null || m?.d === undefined ? '—' : m.d.toExponential(2)}</td><td>{fmt(r.thr, 1)}</td>
              <td className={r.ok === null ? '' : r.ok ? 'ok' : 'bad'}>{r.ok === null ? '' : r.ok ? 'в пределах порога' : 'выше порога'}</td></tr>
          })}</tbody></table></div>
      </>}

      {st && well && its.length > 0 && <>
        <h3>Скважина {well}</h3>
        <div className="scroll" style={{ maxHeight: 300 }}><table className="data-grid dense"><thead><tr>
          <th>Итерация</th><th>Мульт WPIMULT</th><th>D-фактор</th><th>Ошибка, %</th><th>по dP², %</th><th>Pпл модели − ГДИ, бар</th><th>Источник</th><th /></tr></thead>
          <tbody>{its.map(it => {
            const w = it.wells[well], m = it.mults[well]
            return <tr key={it.k}><td>{it.k === 0 ? '0 (без мультов)' : it.k}</td><td>{fmt(m?.inc, 4)}</td><td>{m?.d === null || m?.d === undefined ? '—' : m.d.toExponential(2)}</td>
              <td>{fmt(w?.err, 1)}</td><td>{fmt(w?.err_dp2, 1)}</td><td>{fmt(w?.p_res_gap, 1)}</td><td className="muted small">{m?.source || ''}</td>
              <td>{it.k > 0 && m && <button disabled={busy} onClick={() => write(it.k)}>Записать include этой итерации</button>}</td></tr>
          })}</tbody></table></div>
        <p className="muted small">«Записать include» делает откат на выбранную итерацию: файл wpimult_wdfac_loop.inc кладётся в рабочую папку, в журнал мультов пишется выбранное значение. Историю итераций это не стирает.</p>
        <div className="grid2">
          {chart && <div><ChartView chart={chart} excludeMode={false} onExclude={() => {}} /></div>}
          {errChart && <div><ChartView chart={errChart} excludeMode={false} onExclude={() => {}} /></div>}
        </div>
      </>}
    </section>
  )
}
