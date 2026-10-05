import { useEffect, useMemo, useRef, useState } from 'react'
import { getWork, type GspData, type WorkData } from './api'
import { GAS, MONTH_SHORT, SeasonCalc, WATER, fmtDay, fmtInt, fmtMln, monthOf } from './model'

type Tab = 'gantt' | 'months' | 'seasons' | 'order'
const TABS: [Tab, string][] = [['gantt', 'Гант по дням'], ['months', 'По месяцам'], ['seasons', 'По сезонам'], ['order', 'Очерёдность ввода']]
const INJ = '#149ba5'

function Gantt({ calc, kind, selected, onSelect }: { calc: SeasonCalc; kind: string; selected: number | null; onSelect: (w: number) => void }) {
  const cv = useRef<HTMLCanvasElement>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(900)
  const [hover, setHover] = useState<{ i: number; j: number } | null>(null)
  const L = 54, T = 26, RH = 15
  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(() => setW(el.clientWidth)); ro.observe(el); setW(el.clientWidth)
    return () => ro.disconnect()
  }, [])
  const H = T + calc.nw * RH + 4
  const cw = Math.max(1, (w - L - 8) / calc.nd)
  const color = kind === 'Отбор' ? GAS : INJ
  useEffect(() => {
    const c = cv.current
    if (!c) return
    const dpr = window.devicePixelRatio || 1
    c.width = w * dpr; c.height = H * dpr
    const g = c.getContext('2d')!
    g.scale(dpr, dpr)
    const css = getComputedStyle(document.documentElement)
    const ink = css.getPropertyValue('--ink').trim() || '#222', muted = css.getPropertyValue('--muted').trim() || '#666', line = css.getPropertyValue('--line-soft').trim() || '#eee'
    g.font = '12px "PT Sans", sans-serif'; g.textBaseline = 'middle'
    let mx = 1
    for (const row of calc.flow) for (const v of row) if (v > mx) mx = v
    calc.wells.forEach((well, i) => {
      const y = T + i * RH
      g.fillStyle = selected === well ? color : ink
      g.textAlign = 'right'; g.fillText(String(well), L - 6, y + RH / 2)
      const row = calc.flow[i]
      for (let j = 0; j < calc.nd; j++) {
        const v = row[j], x = L + j * cw
        if (v > 0) { g.globalAlpha = 0.25 + 0.75 * Math.sqrt(v / mx); g.fillStyle = color } else { g.globalAlpha = 1; g.fillStyle = line }
        g.fillRect(x, y + 1, Math.max(0.8, cw - 0.3), RH - 2)
      }
      g.globalAlpha = 1
    })
    // подписи месяцев
    g.fillStyle = muted; g.textAlign = 'left'
    let prev = -1
    calc.days.forEach((d, j) => { const m = monthOf(d); if (m !== prev) { prev = m; g.fillText(MONTH_SHORT[m], L + j * cw + 2, 10); g.fillStyle = line; g.fillRect(L + j * cw, 18, 1, H); g.fillStyle = muted } })
    if (hover) { g.strokeStyle = ink; g.lineWidth = 1.5; g.strokeRect(L + hover.j * cw - 0.5, T + hover.i * RH, Math.max(2, cw) + 1, RH) }
  }, [calc, w, H, cw, color, selected, hover])
  const at = (e: { clientX: number; clientY: number }) => {
    const r = cv.current!.getBoundingClientRect()
    const j = Math.floor((e.clientX - r.left - L) / cw), i = Math.floor((e.clientY - r.top - T) / RH)
    return i >= 0 && i < calc.nw && j >= 0 && j < calc.nd ? { i, j } : null
  }
  const h = hover
  return (
    <div ref={wrap}>
      <div className="gantt-read" aria-live="polite">{h ? <>Скважина <b>{calc.wells[h.i]}</b> · {fmtDay(calc.days[h.j])} · <b>{fmtInt(calc.flow[h.i][h.j])}</b> м³/сут</> : 'Наведите на ячейку: скважина, дата, суточный расход. Нажмите на строку, чтобы выбрать скважину.'}</div>
      <canvas ref={cv} style={{ width: w, height: H, display: 'block' }} onPointerMove={e => setHover(at(e))} onPointerLeave={() => setHover(null)}
        onClick={e => { const p = at(e); const r = cv.current!.getBoundingClientRect(); const i = Math.floor((e.clientY - r.top - T) / RH); if (p) onSelect(calc.wells[p.i]); else if (i >= 0 && i < calc.nw) onSelect(calc.wells[i]) }} />
    </div>
  )
}

export default function WorkPage({ g, calc, kind, season, selected, onSelect }: { g: GspData; calc: SeasonCalc; kind: string; season: string; selected: number | null; onSelect: (w: number | null) => void }) {
  const [tab, setTab] = useState<Tab>('gantt')
  const [data, setData] = useState<WorkData | null>(null)
  const [err, setErr] = useState('')
  const [metric, setMetric] = useState<'days' | 'flow'>('days')
  useEffect(() => { setData(null); getWork(g.gsp).then(setData).catch(e => setErr(String(e.message || e))) }, [g.gsp])

  const monthCols = useMemo(() => data ? data.months.map(m => ({ m, y: Math.floor(m / 12), mo: m % 12 })) : [], [data])
  const years = useMemo(() => {
    const out: { y: number; n: number }[] = []
    monthCols.forEach(c => { const l = out[out.length - 1]; if (l && l.y === c.y) l.n++; else out.push({ y: c.y, n: 1 }) })
    return out
  }, [monthCols])
  const order = useMemo(() => {
    const s = data?.seasons.find(x => x.kind === kind && x.key === season)
    if (!data || !s) return []
    const rows = data.wells.map((w, i) => ({ w, first: s.first[i], idle: s.idle[i], days: s.days[i], total: s.total[i] })).filter(r => r.first >= 0)
    rows.sort((p, q) => p.first - q.first || p.w - q.w)
    const d0 = rows.length ? rows[0].first : 0
    return rows.map((r, n) => ({ ...r, rank: n + 1, delay: r.first - d0 }))
  }, [data, kind, season])

  return (
    <section className="card work">
      <div className="work-head">
        <div className="segmented" role="tablist" aria-label="Работа скважин">{TABS.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} aria-checked={tab === k} onClick={() => setTab(k)}>{l}</button>)}</div>
        {tab === 'months' && <div className="segmented" role="radiogroup" aria-label="Показатель">
          <button type="button" role="radio" aria-checked={metric === 'days'} onClick={() => setMetric('days')}>Дни работы</button>
          <button type="button" role="radio" aria-checked={metric === 'flow'} onClick={() => setMetric('flow')}>Расход, млн м³</button></div>}
        <span className="muted">{tab === 'gantt' || tab === 'order' ? `${g.gsp} · ${kind} ${season}` : g.gsp}</span>
      </div>
      {err && <div className="note warning">{err}</div>}
      {tab === 'gantt' && <Gantt calc={calc} kind={kind} selected={selected} onSelect={onSelect} />}
      {tab !== 'gantt' && !data && !err && <p className="muted">Считаю…</p>}
      {data && tab === 'months' && (
        <div className="scroll"><table className="matrix">
          <thead><tr><th rowSpan={2} className="stick">Скв.</th>{years.map(y => <th key={y.y} colSpan={y.n} className="yr">{y.y}</th>)}</tr>
            <tr>{monthCols.map(c => <th key={c.m} className="mo">{MONTH_SHORT[c.mo]}</th>)}</tr></thead>
          <tbody>{data.wells.map((w, i) => (
            <tr key={w} className={selected === w ? 'sel' : ''} onClick={() => onSelect(w)}><th className="stick">{w}</th>
              {monthCols.map((c, j) => {
                const d = data.monthDays[i][j], f = data.monthFlow[i][j], wf = data.monthWater[i][j]
                const dim = new Date(Date.UTC(c.y, c.mo + 1, 0)).getUTCDate()
                const k = (c.mo >= 9 || c.mo <= 3) ? GAS : INJ
                return <td key={c.m} title={`${w}: ${MONTH_SHORT[c.mo]} ${c.y} · ${d} дн. · ${fmtMln(f)} млн м³${wf ? ' · ВФ ' + Math.round(wf) : ''}`}
                  style={{ background: d > 0 ? `color-mix(in srgb, ${k} ${Math.round((0.25 + 0.75 * Math.min(1, d / dim)) * 100)}%, transparent)` : undefined }} className={d > 0 ? 'on' : ''}>
                  {metric === 'days' ? (d || '') : f > 0 ? fmtMln(f) : ''}{wf > 0 && <i className="wdot" style={{ background: WATER }} />}</td>
              })}</tr>))}</tbody>
        </table></div>)}
      {data && tab === 'seasons' && (
        <div className="scroll"><table className="matrix seasons">
          <thead><tr><th className="stick">Скв.</th>{data.seasons.map(s => <th key={s.kind + s.key} className="mo" title={s.kind}><span className={s.kind === 'Отбор' ? 'k-o' : 'k-z'}>{s.kind === 'Отбор' ? 'О' : 'З'}</span> {s.key}</th>)}</tr></thead>
          <tbody>{data.wells.map((w, i) => (
            <tr key={w} className={selected === w ? 'sel' : ''} onClick={() => onSelect(w)}><th className="stick">{w}</th>
              {data.seasons.map(s => {
                const present = s.first[i] !== -2, worked = s.days[i] > 0
                const cls = !present ? 'none' : !worked ? 'idle' : s.kind === 'Отбор' ? 'prod' : 'inj'
                return <td key={s.kind + s.key} className={'st ' + cls} title={!present ? 'нет данных' : `${s.kind} ${s.key}: ${s.days[i]} дн., ${fmtMln(s.total[i])} млн м³${s.idle[i] ? ' · дней «открыта, расхода нет»: ' + s.idle[i] : ''}`}>
                  {worked ? s.days[i] : present ? '0' : ''}{s.idle[i] > 0 && <i className="ydot" />}</td>
              })}</tr>))}</tbody>
        </table></div>)}
      {data && tab === 'seasons' && <p className="muted hint">Число в клетке — дней с расходом. Зелёные — отбор, синие — закачка, оранжевые — не работала, серые — нет данных; жёлтая точка — скважина была открыта, а расхода нет.</p>}
      {data && tab === 'order' && (order.length ? (
        <div className="scroll"><table className="data">
          <thead><tr><th className="number">№</th><th className="number">Скв.</th><th>Первый расход</th><th className="number">Позже первой, дн.</th><th className="number">Дней с расходом</th><th className="number">Накоплено, млн м³</th><th className="number">«Открыта, расхода нет», дн.</th></tr></thead>
          <tbody>{order.map(r => (
            <tr key={r.w} className={selected === r.w ? 'sel' : ''} onClick={() => onSelect(r.w)}><td className="number">{r.rank}</td><td className="number"><b>{r.w}</b></td><td>{fmtDay(r.first)}</td>
              <td className="number barcell"><i style={{ width: Math.min(100, r.delay / Math.max(1, order[order.length - 1].delay) * 100) + '%' }} /><span>{r.delay}</span></td>
              <td className="number">{r.days}</td><td className="number">{fmtMln(r.total)}</td><td className="number">{r.idle || '—'}</td></tr>))}</tbody>
        </table></div>) : <p className="muted">В этом сезоне ни одна скважина не работала.</p>)}
    </section>
  )
}
