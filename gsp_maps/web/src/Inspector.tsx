import { useMemo } from 'react'
import type { GspData } from './api'
import { GAS, MONTH_NAME, SeasonCalc, WATER, fmt1, fmtDay, fmtInt, fmtMln, fmtPct, fmtTh, place, waterByWell } from './model'

interface Props {
  g: GspData; calc: SeasonCalc; kind: string; season: string; a: number; b: number
  selected: number | null; onSelect: (w: number | null) => void; onFocus: (w: number) => void
}

function DailyBars({ row, days, a, b }: { row: number[]; days: number[]; a: number; b: number }) {
  const W = 300, H = 90, mx = Math.max(1, ...row), bw = W / row.length
  return (
    <svg viewBox={`0 0 ${W} ${H + 14}`} className="daily" role="img" aria-label="Суточный расход скважины по дням сезона">
      <rect x={a * bw} width={Math.max(1, (b - a + 1) * bw)} y={0} height={H} className="daily-win" />
      {row.map((v, j) => v > 0 && <rect key={j} x={j * bw} width={Math.max(0.6, bw - 0.4)} y={H - (v / mx) * H} height={(v / mx) * H} fill={GAS} opacity={j >= a && j <= b ? 1 : 0.35} />)}
      <line x1={0} x2={W} y1={H} y2={H} className="daily-axis" />
      <text x={0} y={H + 11} className="daily-t">{fmtDay(days[0])}</text>
      <text x={W} y={H + 11} textAnchor="end" className="daily-t">{fmtDay(days[days.length - 1])}</text>
      <text x={W} y={9} textAnchor="end" className="daily-t">макс. {fmtTh(mx)} тыс. м³/сут</text>
    </svg>
  )
}

export default function Inspector({ g, calc, kind, season, a, b, selected, onSelect, onFocus }: Props) {
  const { placed } = useMemo(() => place(g, calc), [g, calc])
  const rows = useMemo(() => calc.wells.map((w, i) => ({ w, i, ...calc.stat(i, a, b) })), [calc, a, b])
  const sum = rows.reduce((s, r) => s + Math.max(0, r.total), 0)
  const water = useMemo(() => waterByWell(g.water, kind, season, calc.days[0], calc.days[calc.nd - 1]), [g.water, kind, season, calc])

  if (selected !== null && calc.index.has(selected)) {
    const i = calc.index.get(selected)!, st = calc.stat(i, a, b)
    const full = calc.stat(i, 0, calc.nd - 1)
    const pos = placed.find(p => p.well === selected)
    const dep = g.depths[String(selected)], alt = g.altitude[String(selected)]
    const first = calc.flow[i].findIndex(v => v > 0)
    const wp = water.get(selected) || []
    const press = (which: 'gsp' | 'obj') => g.seasonPressure[which][kind + '|' + season]
    return (
      <aside className="inspector">
        <div className="insp-head"><div><h2>Скважина {selected}</h2><span className="muted">{pos?.dir || 'положение не задано'}{pos ? ' · ' + ({ grid: 'сетка Excel', xy: 'XY tNavigator', fit: 'по сетке, пересчёт в XY' } as Record<string, string>)[pos.src] : ''}</span></div>
          <div className="insp-actions">{pos && <button type="button" className="quiet" onClick={() => onFocus(selected)}>Найти на карте</button>}
            <button type="button" className="quiet" onClick={() => onSelect(null)} aria-label="Закрыть">×</button></div></div>
        <div className="stat-grid">
          <div><span>Накоплено в окне</span><b>{fmtMln(st.total)}</b><i>млн м³</i></div>
          <div><span>Доля ГСП</span><b>{st.total > 0 && sum > 0 ? fmtPct(st.total / sum) : '—'}</b></div>
          <div><span>В среднем за день с расходом</span><b>{fmtTh(st.mean)}</b><i>тыс. м³</i></div>
          <div><span>Дней с расходом</span><b>{st.days}</b><i>из {b - a + 1}</i></div>
        </div>
        <h3>Расход по дням сезона</h3>
        <DailyBars row={calc.flow[i]} days={calc.days} a={a} b={b} />
        <dl className="facts">
          <dt>За весь сезон</dt><dd>{fmtMln(full.total)} млн м³, {full.days} дн.</dd>
          {first >= 0 && <><dt>Первый расход</dt><dd>{fmtDay(calc.days[first])}</dd></>}
          {dep && <><dt>Перфорация</dt><dd>{fmt1(dep[0])} – {fmt1(dep[1])} м (абс.)</dd></>}
          {alt !== undefined && <><dt>Альтитуда</dt><dd>{fmt1(alt)} м</dd></>}
          {press('gsp') !== undefined && <><dt>Давление ГСП (ср.)</dt><dd>{fmt1(press('gsp'))} бар</dd></>}
          {press('obj') !== undefined && <><dt>Давление объекта (ср.)</dt><dd>{fmt1(press('obj'))} бар</dd></>}
        </dl>
        {wp.length > 0 && <>
          <h3>Вынос воды</h3>
          <table className="mini"><thead><tr><th>Замер</th><th className="number">л/ч</th><th className="number">ВФ, л/1000 м³</th></tr></thead>
            <tbody>{wp.map((w, k) => <tr key={k}><td>{MONTH_NAME[w.month]} {w.year}</td>
              {w.note !== 'Ок' ? <td colSpan={2} className="muted">{w.note}</td> : <><td className="number">{fmtInt(w.flow ?? 0)}</td><td className="number" style={{ color: WATER }}>{fmt1(w.factor ?? 0)}</td></>}</tr>)}</tbody></table>
        </>}
      </aside>
    )
  }
  const top = [...rows].sort((p, q) => q.total - p.total).slice(0, 8)
  const working = rows.filter(r => r.total > 0).length
  return (
    <aside className="inspector">
      <div className="insp-head"><div><h2>{g.gsp}</h2><span className="muted">{kind} {season}</span></div></div>
      <div className="stat-grid">
        <div><span>Накоплено в окне</span><b>{fmtMln(sum)}</b><i>млн м³</i></div>
        <div><span>Скважин с расходом</span><b>{working}</b><i>из {rows.length}</i></div>
      </div>
      <h3>Больше всего</h3>
      <ul className="toplist">{top.map(r => (
        <li key={r.w}><button type="button" onClick={() => onSelect(r.w)}>
          <b>{r.w}</b><span className="bar"><i style={{ width: (sum > 0 ? (r.total / top[0].total) * 100 : 0) + '%' }} /></span>
          <span className="number">{sum > 0 ? fmtPct(r.total / sum) : '—'}</span></button></li>))}</ul>
      <p className="muted hint">Нажмите на скважину на карте или в списке, чтобы увидеть её расход по дням, воду и глубины.</p>
    </aside>
  )
}
