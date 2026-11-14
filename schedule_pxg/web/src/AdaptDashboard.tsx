import { useMemo } from 'react'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import { Tables } from '../../../pxg_core/web-ui/table/Tables'
import { tableOf } from '../../../pxg_core/web-ui/table/tableBuild'
import type { Table, TableStyle } from '../../../pxg_core/web-ui/table/tableTypes'
import type { LoopIter, LoopState } from './api'

const fmt = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const METRIC: Record<string, string> = { regimes: 'депрессия по режимам ГДИ', dp2: 'ΔP² (A и B)' }
const GREEN = { fill: 'E3F4E8', font: '1B6B3A', border: '' }, RED = { fill: 'FBE4E1', font: '9B2A1E', border: '' }
const median = (v: number[]) => { if (!v.length) return null; const s = [...v].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2 }

/** Лучшая итерация скважины с мультами (наименьшая ошибка). */
export const bestIter = (its: LoopIter[], w: string): LoopIter | undefined => {
  const c = its.filter(i => i.k > 0 && i.mults[w] && i.wells[w]?.err !== null && i.wells[w]?.err !== undefined)
  return c.length ? c.reduce((a, b) => ((b.wells[w].err as number) < (a.wells[w].err as number) ? b : a)) : undefined
}

/** Дашборд автоцикла: сводка по объекту, обзорная таблица со статусами, карточка скважины (итерации, депрессия, индикаторная кривая). */
export default function AdaptDashboard({ st, well, setWell, write, busy }: { st: LoopState; well: string; setWell: (w: string) => void; write: (k: number) => void; busy: boolean }) {
  const its = st.iterations
  const thr = (w: string) => st.thresholds[w] ?? 10
  const rows = useMemo(() => st.wells.map(w => {
    const b = bestIter(its, w)
    return { w, base: its[0]?.wells[w]?.err ?? null, best: b, err: b ? (b.wells[w].err as number) : null }
  }), [st, its])

  const sum = useMemo(() => {
    const withMult = rows.filter(r => r.best)
    const inside = withMult.filter(r => (r.err as number) <= thr(r.w))
    return {
      wells: st.wells.length, inside: inside.length, outside: withMult.length - inside.length, none: st.wells.length - withMult.length,
      before: median(rows.map(r => r.base).filter((x): x is number => x !== null)), after: median(withMult.map(r => r.err as number)),
      runs: its.length, sec: st.job?.seconds ?? 0,
    }
  }, [rows, st, its])

  const overview = useMemo<Table>(() => {
    const green: number[] = [], red: number[] = []
    rows.forEach((r, i) => { if (r.err !== null) (r.err <= thr(r.w) ? green : red).push(i) })
    const styles: TableStyle[] = [
      ...(green.length ? [{ rows: green, columns: ['c4', 'c8'], ...GREEN }] : []), ...(red.length ? [{ rows: red, columns: ['c4', 'c8'], ...RED }] : [])]
    return tableOf('adapt-loop-overview', 'Обзор скважин (' + st.date + ')',
      [['Скважина', 'text'], ['Ошибка до, %', 'number', 1], ['Лучшая итерация', 'number', 0], ['WPIMULT (итого)', 'number', 4], ['Ошибка после, %', 'number', 1], ['D-фактор', 'text'], ['Порог, %', 'number', 1], ['Pпл модели − ГДИ, бар', 'number', 1], ['Вывод', 'text']],
      rows.map(r => {
        const m = r.best?.mults[r.w]
        return [r.w, r.base, r.best ? r.best.k : null, m ? m.inc : null, r.err, m?.d === null || m?.d === undefined ? '—' : m.d.toExponential(2), thr(r.w),
          r.best ? (r.best.wells[r.w].p_res_gap ?? null) : null, r.err === null ? 'нет данных' : r.err <= thr(r.w) ? 'в пределах порога' : 'выше порога']
      }), 'Цвет подсказка: порог и меру задаёт инженер, решение по скважине за ним.', styles)
  }, [rows, st])

  const itTable = useMemo<Table | null>(() => {
    if (!well || !its.length) return null
    return tableOf('adapt-loop-iters', 'Итерации, скв. ' + well,
      [['Итерация', 'number', 0], ['WPIMULT (итого)', 'number', 4], ['D-фактор', 'text'], ['Ошибка, %', 'number', 1], ['Ошибка по dP², %', 'number', 1], ['Pпл модели − ГДИ, бар', 'number', 1], ['Источник', 'text']],
      its.map(it => {
        const w = it.wells[well], m = it.mults[well]
        return [it.k, m ? m.inc : null, m?.d === null || m?.d === undefined ? '—' : m.d.toExponential(2), w?.err ?? null, w?.err_dp2 ?? null, w?.p_res_gap ?? null, m?.source || (it.k === 0 ? 'без мультов' : '')]
      }))
  }, [its, well])

  const dep = useMemo(() => {
    const ref = its[0]?.wells[well]
    if (!ref) return null
    const ser = [mkSeries({ name: 'ГДИ', kind: 'points', slot: 3, x: ref.q.map(q => q / 1000), y: ref.dep_gdi.map(v => v ?? NaN) })]
    its.forEach((it, i) => {
      const w = it.wells[well]
      if (w) ser.push(mkSeries({ name: it.k === 0 ? 'модель без мультов' : 'итерация ' + it.k, slot: i === 0 ? 5 : i - 1, dashed: i === 0, x: w.q.map(q => q / 1000), y: w.dep_model.map(v => v ?? NaN) }))
    })
    return mkChart('loop-dep', 'Депрессия по режимам ГДИ, скв. ' + well, mkAxis('Дебит', 'тыс. м³/сут'), mkAxis('Pпл − Pзаб', 'бар', 'value', { from_zero: true }), ser)
  }, [its, well])

  const curve = useMemo(() => {
    const ref = its[0]?.wells[well]
    if (!ref) return null
    const qmax = Math.max(...ref.q) / 1000 * 1.15
    const xs = Array.from({ length: 31 }, (_, i) => (qmax * i) / 30)
    const line = (a: number | null, b: number | null) => (a === null || b === null ? null : xs.map(x => a * x + b * x * x))
    const ser = []
    const g = line(ref.a_gdi, ref.b_gdi)
    if (g) ser.push(mkSeries({ name: 'ГДИ (A, B)', slot: 3, x: xs, y: g }))
    its.forEach((it, i) => {
      const w = it.wells[well]
      const y = w && line(w.a_model, w.b_model)
      if (y) ser.push(mkSeries({ name: it.k === 0 ? 'модель без мультов' : 'итерация ' + it.k, slot: i === 0 ? 5 : i - 1, dashed: i === 0, x: xs, y }))
    })
    return ser.length ? mkChart('loop-ip', 'Индикаторная кривая ΔP² = A·Q + B·Q², скв. ' + well, mkAxis('Дебит', 'тыс. м³/сут'), mkAxis('ΔP²', 'бар²', 'value', { from_zero: true }), ser) : null
  }, [its, well])

  const errs = useMemo(() => {
    const pts = its.filter(i => i.wells[well]?.err !== null && i.wells[well]?.err !== undefined)
    if (pts.length < 2) return null
    const y = pts.map(i => i.wells[well].err as number)
    return mkChart('loop-err', 'Ошибка по итерациям, скв. ' + well, mkAxis('Итерация'), mkAxis(METRIC[st.metric] || 'ошибка', '%', 'value', { from_zero: true }), [
      mkSeries({ name: 'ошибка', kind: 'points', slot: 0, x: pts.map(i => i.k), y }), { ...mkSeries({ name: 'линия', slot: 0, x: pts.map(i => i.k), y }), legend: false },
      mkSeries({ name: 'порог', slot: 5, dashed: true, x: pts.map(i => i.k), y: pts.map(() => thr(well)) })])
  }, [its, well, st])

  const bestK = bestIter(its, well)?.k
  return (
    <div className="adapt-dash">
      <h3>Сводка по объекту</h3>
      <div className="row adapt-tiles">
        <div className="tile"><b>{sum.wells}</b><span>скважин в цикле</span></div>
        <div className="tile ok"><b>{sum.inside}</b><span>в пределах порога</span></div>
        <div className="tile bad"><b>{sum.outside}</b><span>выше порога</span></div>
        <div className="tile"><b>{fmt(sum.before)} → {fmt(sum.after)}</b><span>медианная ошибка, % (до → после)</span></div>
        <div className="tile"><b>{sum.runs}</b><span>прогонов модели · {fmt(sum.sec / 60, 0)} мин последний</span></div>
      </div>
      {sum.none > 0 && <p className="muted small">Без мультов осталось скважин: {sum.none} (см. причины выше).</p>}
      <Tables scope="adapt-loop" tables={[overview]} onRow={(_t, i) => setWell(rows[i].w)} />
      {itTable && <>
        <h3>Скважина {well}</h3>
        <div className="row">
          <label>Скважина<select value={well} onChange={e => setWell(e.target.value)}>{st.wells.map(w => <option key={w} value={w}>{w}</option>)}</select></label>
          <button disabled={busy || bestK === undefined} onClick={() => bestK !== undefined && write(bestK)}>Записать include лучшей итерации ({bestK ?? '—'})</button>
          {its.filter(i => i.k > 0 && i.mults[well] && i.k !== bestK).map(i => <button key={i.k} disabled={busy} onClick={() => write(i.k)}>Откатить на итерацию {i.k}</button>)}
        </div>
        <p className="muted small">Откат записывает wpimult_wdfac_loop.inc выбранной итерации в рабочую папку и обновляет журнал мультов; историю итераций не стирает. Include вставляете в модель вы.</p>
        <Tables scope="adapt-loop-iters" tables={[itTable]} />
        <div className="adapt-charts">
          {dep && <div><ChartView chart={dep} excludeMode={false} onExclude={() => {}} /></div>}
          {curve && <div><ChartView chart={curve} excludeMode={false} onExclude={() => {}} /></div>}
          {errs && <div><ChartView chart={errs} excludeMode={false} onExclude={() => {}} /></div>}
        </div>
      </>}
    </div>
  )
}
