import { useEffect, useRef, useState } from 'react'
import { fmtDay } from './model'

export interface Series { key: string | number; label: string; color: string; y: number[]; dash?: boolean; bold?: boolean }
interface Props {
  days: number[]; series: Series[]; mode: 'bars' | 'lines'; win?: [number, number]
  fmt: (v: number) => string; unit: string; height?: number; compact?: boolean; interactive?: boolean; label: string
}

const niceTicks = (mx: number, n = 4) => {
  const raw = mx / n, p = Math.pow(10, Math.floor(Math.log10(raw || 1))), f = raw / p
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p
  const out: number[] = []
  for (let v = 0; v <= mx + step * 0.01; v += step) out.push(v)
  return { ticks: out, top: out[out.length - 1] || 1 }
}

/** Интерактивный график по дням сезона: значения при наведении, зум рамкой (двойной щелчок — сброс). */
export default function Chart({ days, series, mode, win, fmt, unit, height = 150, compact, interactive = true, label }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(300)
  const [zoom, setZoom] = useState<[number, number] | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  const [drag, setDrag] = useState<[number, number] | null>(null)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setW(Math.max(120, el.clientWidth)))
    ro.observe(el); setW(Math.max(120, el.clientWidth))
    return () => ro.disconnect()
  }, [])
  useEffect(() => { setZoom(null) }, [days])

  const nd = days.length, fs = compact ? 11 : 12
  const L = compact ? 34 : 44, R = 8, T = 8, B = 20, H = height, pw = Math.max(10, w - L - R), ph = H - T - B
  const [z0, z1] = zoom ?? [0, nd - 1]
  const span = Math.max(1, z1 - z0 + 1)
  const mx = Math.max(1e-9, ...series.map(s => Math.max(0, ...s.y.slice(z0, z1 + 1))))
  const { ticks, top } = niceTicks(mx, compact ? 3 : 4)
  const xs = (j: number) => L + (mode === 'bars' ? ((j - z0) / span) * pw : span > 1 ? ((j - z0) / (span - 1)) * pw : 0)
  const bw = pw / span
  const ys = (v: number) => T + ph - (Math.max(0, v) / top) * ph
  const jAt = (px: number) => {
    const t = (px - L) / pw
    return Math.max(z0, Math.min(z1, mode === 'bars' ? z0 + Math.floor(t * span) : z0 + Math.round(t * (span - 1))))
  }
  const px = (e: React.PointerEvent) => e.clientX - (box.current?.getBoundingClientRect().left ?? 0)
  const xTicks = [0, 1, 2, 3].map(k => z0 + Math.round(((span - 1) * k) / 3)).filter((v, k, a) => a.indexOf(v) === k)
  const hv = hover !== null && hover >= z0 && hover <= z1 ? hover : null
  const tipLeft = hv !== null && xs(hv) > w * 0.55

  return (
    <div className={'chart' + (compact ? ' compact' : '')} ref={box} style={{ height: H }}>
      <svg width={w} height={H} role="img" aria-label={label}
        onPointerMove={interactive ? e => { const j = jAt(px(e)); setHover(j); if (drag) setDrag([drag[0], j]) } : undefined}
        onPointerLeave={interactive ? () => { setHover(null); setDrag(null) } : undefined}
        onPointerDown={interactive ? e => { (e.target as Element).setPointerCapture?.(e.pointerId); const j = jAt(px(e)); setDrag([j, j]) } : undefined}
        onPointerUp={interactive ? () => {
          if (drag && Math.abs(drag[1] - drag[0]) >= 2) setZoom([Math.min(...drag), Math.max(...drag)])
          setDrag(null)
        } : undefined}
        onDoubleClick={interactive ? () => setZoom(null) : undefined}>
        {ticks.map(v => <g key={v}>
          <line x1={L} x2={L + pw} y1={ys(v)} y2={ys(v)} className="chart-grid" />
          <text x={L - 5} y={ys(v) + 4} textAnchor="end" className="chart-t" fontSize={fs}>{fmt(v)}</text>
        </g>)}
        {win && <rect x={Math.max(L, xs(Math.max(win[0], z0)))} width={Math.max(1, Math.min(L + pw, xs(Math.min(win[1], z1)) + (mode === 'bars' ? bw : 0)) - Math.max(L, xs(Math.max(win[0], z0))))} y={T} height={ph} className="daily-win" />}
        {mode === 'bars' && series.map(s => s.y.slice(z0, z1 + 1).map((v, k) => v > 0 && (
          <rect key={s.key + '_' + k} x={xs(z0 + k)} width={Math.max(0.8, bw - (bw > 4 ? 1 : 0.3))} y={ys(v)} height={T + ph - ys(v)} fill={s.color}
            opacity={win && (z0 + k < win[0] || z0 + k > win[1]) ? 0.35 : 1} />)))}
        {mode === 'lines' && series.map(s => (
          <polyline key={s.key} fill="none" stroke={s.color} strokeWidth={s.bold ? 2.6 : 2} strokeLinejoin="round" strokeDasharray={s.dash ? '5 4' : undefined}
            points={s.y.slice(z0, z1 + 1).map((v, k) => xs(z0 + k).toFixed(1) + ',' + ys(v).toFixed(1)).join(' ')} />))}
        <line x1={L} x2={L + pw} y1={T + ph} y2={T + ph} className="daily-axis" />
        {xTicks.map((j, k) => <text key={j} x={xs(j) + (mode === 'bars' ? bw / 2 : 0)} y={H - 5} className="chart-t" fontSize={fs}
          textAnchor={k === 0 ? 'start' : k === xTicks.length - 1 ? 'end' : 'middle'}>{fmtDay(days[j]).slice(0, 5)}</text>)}
        {drag && <rect x={xs(Math.min(...drag))} width={Math.max(1, Math.abs(xs(drag[1]) - xs(drag[0])) + (mode === 'bars' ? bw : 0))} y={T} height={ph} className="chart-brush" />}
        {hv !== null && <>
          <line x1={xs(hv) + (mode === 'bars' ? bw / 2 : 0)} x2={xs(hv) + (mode === 'bars' ? bw / 2 : 0)} y1={T} y2={T + ph} className="chart-cross" />
          {mode === 'lines' && series.map(s => <circle key={s.key} cx={xs(hv)} cy={ys(s.y[hv])} r={3.5} fill={s.color} stroke="var(--surface)" strokeWidth={1.5} />)}
        </>}
      </svg>
      {hv !== null && (
        <div className="chart-tip" style={{ left: tipLeft ? undefined : xs(hv) + 12, right: tipLeft ? w - xs(hv) + 12 : undefined, top: T }}>
          <b>{fmtDay(days[hv])}</b>
          {series.map(s => <div key={s.key}><i style={{ background: s.color }} />{series.length > 1 ? s.label + ': ' : ''}<b>{fmt(s.y[hv] ?? 0)}</b> {unit}</div>)}
        </div>
      )}
      {zoom && <button type="button" className="chart-reset" onClick={() => setZoom(null)}>Сбросить зум</button>}
    </div>
  )
}
