import { useEffect, useMemo, useRef, useState } from 'react'
import type { GspData } from './api'
import { MONTH_SHORT, SeasonCalc, fmtDay, fmtMln, monthOf } from './model'

interface Props { g: GspData; calc: SeasonCalc; a: number; b: number; setWindow: (a: number, b: number) => void }
const H = 78, PAD = 10

export default function Timeline({ g, calc, a, b, setWindow }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(900)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const drag = useRef<{ mode: 'a' | 'b' | 'move' | 'new'; at: number; a: number; b: number } | null>(null)
  const nd = calc.nd
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setW(el.clientWidth))
    ro.observe(el); setW(el.clientWidth)
    return () => ro.disconnect()
  }, [])
  const inner = Math.max(50, w - 2 * PAD)
  const px = (i: number) => PAD + (i / nd) * inner
  const idxAt = (x: number) => Math.max(0, Math.min(nd - 1, Math.floor(((x - PAD) / inner) * nd)))

  const wa = useRef({ a, b }); wa.current = { a, b }
  useEffect(() => {
    if (!playing) return
    let last = performance.now(), pos = wa.current.b
    const tick = (t: number) => {
      pos += ((t - last) / 1000) * speed * Math.max(6, nd / 12)
      last = t
      const next = Math.min(nd - 1, Math.floor(pos))
      if (next !== wa.current.b) setWindow(wa.current.a, next)
      if (next >= nd - 1) { setPlaying(false); return }
      id = requestAnimationFrame(tick)
    }
    let id = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(id)
  }, [playing, speed, nd, setWindow])

  const spark = useMemo(() => {
    const mx = Math.max(1, ...calc.daily)
    const pts = Array.from(calc.daily, (v, j) => `${(PAD + ((j + 0.5) / nd) * inner).toFixed(1)},${(40 - (Math.max(0, v) / mx) * 34).toFixed(1)}`)
    return { line: 'M' + pts.join('L'), area: `M${PAD},40L` + pts.join('L') + `L${PAD + inner},40Z`, max: mx }
  }, [calc, nd, inner])

  const bands = useMemo(() => {
    const out: { x0: number; x1: number; type: string }[] = []
    const d0 = calc.days[0], d1 = calc.days[nd - 1]
    const ps = g.periods
    for (let i = 0; i < ps.length; i++) {
      const s = ps[i].day, e = i + 1 < ps.length ? ps[i + 1].day : d1 + 1
      if (e <= d0 || s > d1) continue
      const i0 = lowerBound(calc.days, Math.max(s, d0)), i1 = lowerBound(calc.days, Math.min(e, d1 + 1))
      if (i1 > i0) out.push({ x0: px(i0), x1: px(i1), type: ps[i].type })
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [g.periods, calc, nd, inner])

  const months = useMemo(() => {
    const out: { i: number; m: number; y: number }[] = []
    let prev = -1
    calc.days.forEach((d, j) => { const m = monthOf(d); if (m !== prev) { out.push({ i: j, m, y: new Date(d * 86400000).getUTCFullYear() }); prev = m } })
    return out
  }, [calc])

  const pos = (e: React.PointerEvent) => e.clientX - box.current!.getBoundingClientRect().left
  const down = (e: React.PointerEvent) => {
    const x = pos(e), xa = px(a), xb = px(b + 1)
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    setPlaying(false)
    if (Math.abs(x - xa) < 9) drag.current = { mode: 'a', at: idxAt(x), a, b }
    else if (Math.abs(x - xb) < 9) drag.current = { mode: 'b', at: idxAt(x), a, b }
    else if (x > xa && x < xb) drag.current = { mode: 'move', at: idxAt(x), a, b }
    else { drag.current = { mode: 'new', at: idxAt(x), a, b }; setWindow(idxAt(x), idxAt(x)) }
  }
  const move = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const i = idxAt(pos(e))
    if (d.mode === 'a') setWindow(Math.min(i, d.b), d.b)
    else if (d.mode === 'b') setWindow(d.a, Math.max(i, d.a))
    else if (d.mode === 'new') setWindow(Math.min(i, d.at), Math.max(i, d.at))
    else {
      const len = d.b - d.a, na = Math.max(0, Math.min(nd - 1 - len, d.a + i - d.at))
      setWindow(na, na + len)
    }
  }
  const monthWindow = (j: number) => {
    const start = months[j].i, end = j + 1 < months.length ? months[j + 1].i - 1 : nd - 1
    setPlaying(false); setWindow(start, end)
  }
  const sel = Math.max(0, b - a + 1)
  const whole = a === 0 && b === nd - 1
  return (
    <div className="timeline">
      <div className="tl-row">
        <button type="button" className="play" onClick={() => { if (!playing && b >= nd - 1) setWindow(a, a); setPlaying(p => !p) }} aria-label={playing ? 'Пауза' : 'Показать развитие по дням'}
          title={playing ? 'Пауза' : 'Показать развитие по дням: окно растёт от его начала'}>
          <svg viewBox="0 0 16 16" aria-hidden="true">{playing ? <path d="M5 3v10M11 3v10" /> : <path d="M5 3l8 5-8 5z" />}</svg></button>
        <div className="segmented tl-speed" role="radiogroup" aria-label="Скорость">
          {[1, 2, 4, 8].map(s => <button key={s} type="button" role="radio" aria-checked={speed === s} onClick={() => setSpeed(s)}>{s}×</button>)}
        </div>
        <div className="tl-read"><b>{fmtDay(calc.days[a])}</b> — <b>{fmtDay(calc.days[b])}</b><span className="muted"> · {sel} дн. · {fmtMln(calc.daily.slice(a, b + 1).reduce((s, v) => s + v, 0))} млн м³</span></div>
        <div className="tl-chips">
          <button type="button" className={'chip-btn' + (whole ? ' on' : '')} onClick={() => { setPlaying(false); setWindow(0, nd - 1) }}>Весь сезон</button>
          {months.map((m, j) => <button key={j} type="button" className="chip-btn" onClick={() => monthWindow(j)} title={`Только ${MONTH_SHORT[m.m].toLowerCase()} ${m.y}`}>{MONTH_SHORT[m.m]}</button>)}
        </div>
      </div>
      <div ref={box} className="tl-track" onPointerDown={down} onPointerMove={move} onPointerUp={() => { drag.current = null }}>
        <svg width={w} height={H} role="img" aria-label="Бегунок времени: перетащите края окна или всё окно">
          {bands.map((p, i) => <rect key={i} x={p.x0} width={Math.max(0, p.x1 - p.x0)} y={44} height={6} className={'band ' + p.type} />)}
          <path d={spark.area} className="spark-area" /><path d={spark.line} className="spark-line" />
          {months.map((m, j) => {
            const room = (j + 1 < months.length ? px(months[j + 1].i) : px(nd)) - px(m.i)
            return (
              <g key={j}><line x1={px(m.i)} x2={px(m.i)} y1={6} y2={54} className="tl-tick" />
                {room > 34 && <text x={px(m.i) + 3} y={H - 8} className="tl-label">{MONTH_SHORT[m.m]}{(m.m === 0 || j === 0) && room > 64 ? ' ' + m.y : ''}</text>}</g>)
          })}
          <rect x={px(a)} width={Math.max(2, px(b + 1) - px(a))} y={2} height={52} className="tl-sel" />
          <rect x={px(a) - 3} y={14} width={6} height={28} rx={3} className="tl-handle" />
          <rect x={px(b + 1) - 3} y={14} width={6} height={28} rx={3} className="tl-handle" />
        </svg>
      </div>
    </div>
  )
}

function lowerBound(arr: number[], v: number) {
  let lo = 0, hi = arr.length
  while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < v) lo = m + 1; else hi = m }
  return lo
}
