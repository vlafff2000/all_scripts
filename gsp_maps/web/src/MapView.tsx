import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { GspData } from './api'
import { PAINTS, GAS, MONTH_COLOR, type PaintData, paintFor, rampColor, type Paint, MONTH_NAME, MONTH_SHORT, SeasonCalc, WATER, fmt1, fmtDay, fmtMln, fmtPct, fmtTh, monthOf, niceStep, place, sectorPath, waterByWell } from './model'

export interface MapOptions { sectors: 'months' | 'plain'; water: boolean; share: boolean; fixed: boolean; paint: Paint; scale: number; labels: 'num' | 'val' | 'none'; hideIdle: boolean; minValue: number }
export interface MapHandle { toPng: () => Promise<Blob>; fit: () => void; focus: (well: number) => void }
interface Props {
  g: GspData; calc: SeasonCalc; kind: string; season: string; a: number; b: number
  options: MapOptions; onOptions: (o: Partial<MapOptions>) => void; selected: number | null; onSelect: (w: number | null) => void; group: number[]; onGroup: (ws: number[]) => void; title: string
}
interface View { k: number; tx: number; ty: number }
interface Tip { x: number; y: number; well: number }

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

const Glyph = memo(function Glyph(p: {
  well: number; x: number; y: number; r: number; rmax: number; total: number; share: number; months: number[]; order: number[]
  sectors: boolean; paint?: { color: string; label: string } | null; water: { factor: number | null; flow: number | null }[]; maxFlow: number; showShare: boolean; selected: boolean; label: string; dim: boolean
}) {
  const { x, y, r, rmax } = p
  if (p.paint !== undefined) {
    const pc = p.paint, rr = rmax * 0.8, fs0 = rmax * 0.44
    return (
      <g className="glyph" data-well={p.well} opacity={p.dim ? 0.25 : 1}>
        {p.selected && <circle cx={x} cy={y} r={rr + rmax * 0.3} fill="none" stroke="var(--accent)" strokeWidth={rmax * 0.1} strokeDasharray={`${rmax * 0.3} ${rmax * 0.18}`} />}
        <circle cx={x} cy={y} r={rr} fill={pc ? pc.color : '#c5cdd0'} fillOpacity={pc ? 0.95 : 0.5} stroke={pc ? '#fff' : '#8a979c'} strokeWidth={rmax * 0.05} />
        <text x={x} y={y - (pc ? rmax * 0.16 : 0)} fontSize={fs0} textAnchor="middle" dominantBaseline="central" fontWeight={700} fill="#fff" stroke="#0b1418" strokeWidth={fs0 * 0.2} paintOrder="stroke" strokeLinejoin="round">{p.label}</text>
        {pc && <text x={x} y={y + rmax * 0.34} fontSize={rmax * 0.32} textAnchor="middle" dominantBaseline="central" fontWeight={700} fill="#fff" stroke="#0b1418" strokeWidth={rmax * 0.06} paintOrder="stroke" strokeLinejoin="round">{pc.label}</text>}
      </g>
    )
  }
  const idle = !(p.total > 0)
  const els: React.ReactNode[] = []
  if (idle) {
    els.push(<circle key="c" cx={x} cy={y} r={r} fill="#c5cdd0" fillOpacity={0.45} stroke="#8a979c" strokeWidth={rmax * 0.04} />)
  } else if (!p.sectors) {
    els.push(<circle key="c" cx={x} cy={y} r={r} fill={GAS} fillOpacity={0.88} stroke="#7a1620" strokeWidth={rmax * 0.04} />)
  } else {
    let a0 = 0
    const sum = p.months.reduce((s, v) => s + v, 0) || 1
    const parts = p.order.filter(m => p.months[m] > 0)
    if (parts.length <= 1) els.push(<circle key="c" cx={x} cy={y} r={r} fill={MONTH_COLOR[parts[0] ?? 0]} stroke="#fff" strokeWidth={rmax * 0.04} />)
    else for (const m of parts) {
      const a1 = a0 + (p.months[m] / sum) * Math.PI * 2
      els.push(<path key={m} d={sectorPath(x, y, r, a0, a1)} fill={MONTH_COLOR[m]} stroke="#fff" strokeWidth={rmax * 0.035} strokeLinejoin="round" />)
      a0 = a1
    }
  }
  const ws = p.water.filter(w => (w.flow ?? 0) > 0)
  if (ws.length) {
    const gap = ws.length > 1 ? 0.12 : 0, span = (Math.PI * 2) / ws.length
    ws.forEach((w, i) => {
      const t = rmax * 0.2 * (0.35 + 0.65 * Math.sqrt((w.flow ?? 0) / (p.maxFlow || 1)))
      const r0 = Math.max(r, rmax * 0.25) + rmax * 0.05
      els.push(<path key={'w' + i} d={sectorPath(x, y, r0 + t, i * span + gap / 2, (i + 1) * span - gap / 2, r0)} fill={WATER} stroke="#fff" strokeWidth={rmax * 0.02} />)
    })
    const wf = Math.max(...ws.map(w => w.factor ?? 0))
    if (wf > 0) {
      const bx = x + r * 0.78 + rmax * 0.1, by = y + r * 0.78 + rmax * 0.1, fs = rmax * 0.3
      els.push(<g key="wf"><rect x={bx - fs * 1.1} y={by - fs * 0.65} width={fs * 2.2} height={fs * 1.3} rx={fs * 0.4} fill={WATER} stroke="#fff" strokeWidth={fs * 0.12} />
        <text x={bx} y={by} fontSize={fs} textAnchor="middle" dominantBaseline="central" fill="#fff" fontWeight={700}>{Math.round(wf)}</text></g>)
    }
  }
  const fs = Math.max(rmax * (p.label.length > 4 ? 0.36 : 0.52), 0.0001)
  return (
    <g className="glyph" data-well={p.well} opacity={p.dim ? 0.25 : 1}>
      {p.selected && <circle cx={x} cy={y} r={Math.max(r, rmax * 0.3) + rmax * 0.32} fill="none" stroke="var(--accent)" strokeWidth={rmax * 0.1} strokeDasharray={`${rmax * 0.3} ${rmax * 0.18}`} />}
      {els}
      <text x={x} y={y} fontSize={fs} textAnchor="middle" dominantBaseline="central" fontWeight={700}
        fill={idle ? '#26343a' : '#fff'} stroke={idle ? '#fff' : '#0b1418'} strokeWidth={fs * 0.2} paintOrder="stroke" strokeLinejoin="round">{p.label}</text>
      {idle && <text x={x + Math.max(r, rmax * 0.3) * 0.8} y={y - Math.max(r, rmax * 0.3) * 0.8} fontSize={rmax * 0.5} fontWeight={700} textAnchor="middle" dominantBaseline="central" fill="#d92d20" stroke="#fff" strokeWidth={rmax * 0.1} paintOrder="stroke">✕</text>}
      {!idle && p.showShare && p.share >= 0.02 && (
        <g><rect x={x + r + rmax * 0.08} y={y - rmax * 0.19} width={rmax * 0.95} height={rmax * 0.38} rx={rmax * 0.1} fill="#fff" fillOpacity={0.92} stroke="#8b1d27" strokeWidth={rmax * 0.025} />
          <text x={x + r + rmax * 0.08 + rmax * 0.475} y={y} fontSize={rmax * 0.27} textAnchor="middle" dominantBaseline="central" fill="#8b1d27" fontWeight={700}>{(p.share * 100).toFixed(p.share >= 0.1 ? 0 : 1)}%</text></g>
      )}
    </g>
  )
})

const MapView = forwardRef<MapHandle, Props>(function MapView({ g, calc, kind, season, a, b, options, onOptions, selected, onSelect, group, onGroup, title }, ref) {
  const wrap = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 800, h: 560 })
  const [view, setView] = useState<View>({ k: 1, tx: 0, ty: 0 })
  const [tip, setTip] = useState<Tip | null>(null)
  const drag = useRef<{ x: number; y: number; moved: boolean; box?: boolean; x0?: number; y0?: number } | null>(null)
  const [box, setBox] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null)

  useLayoutEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setSize({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  const geo = useMemo(() => place(g, calc), [g, calc])
  const [frameAll, setFrameAll] = useState(false)
  const [layersOpen, setLayersOpen] = useState(false)
  const { placed, spacing, far } = geo
  const bounds = frameAll ? geo.boundsAll : geo.bounds
  const rmax = useMemo(() => {
    const span = Math.max(bounds.x1 - bounds.x0, bounds.y1 - bounds.y0, 1)
    // в плотных кустах медианный шаг крошечный: круг не меньше 2,2 % размаха карты (перекрытие лечат зум и порядок отрисовки)
    return Math.min(Math.max(spacing * 0.58, span * 0.022), span * 0.09)
  }, [spacing, bounds])

  // подгонка карты под окно
  const M = 70, top = layersOpen ? 190 : 54
  const bw = bounds.x1 - bounds.x0 + rmax * 4, bh = bounds.y1 - bounds.y0 + rmax * 4
  const s0 = Math.min((size.w - 2 * M) / bw, (size.h - top - M) / bh)
  const fit = { s: s0, ox: size.w / 2 - s0 * ((bounds.x0 + bounds.x1) / 2), oy: top + (size.h - top - M * 0.5) / 2 - s0 * ((bounds.y0 + bounds.y1) / 2) }
  const resetView = useCallback(() => setView({ k: 1, tx: 0, ty: 0 }), [])
  useEffect(resetView, [g, resetView, frameAll])
  useEffect(() => setFrameAll(false), [g])

  // итоги окна
  const win = useMemo(() => {
    const stats = placed.map(p => calc.stat(p.i, a, b))
    const sumAll = stats.reduce((s, v) => s + (v.total > 0 ? v.total : 0), 0)
    const maxWin = Math.max(1, ...stats.map(v => v.total))
    const maxSeason = Math.max(1, ...placed.map(p => calc.stat(p.i, 0, calc.nd - 1).total))
    const first = monthOf(calc.days[a])
    const order = Array.from({ length: 12 }, (_, i) => (first + i) % 12)
    const months = options.sectors === 'months' ? placed.map(p => calc.monthly(p.i, a, b)) : []
    return { stats, sumAll, scaleMax: options.fixed ? maxSeason : maxWin, order, months }
  }, [placed, calc, a, b, options.sectors, options.fixed])

  const water = useMemo(() => waterByWell(g.water, kind, season, calc.days[a], calc.days[b]), [g.water, kind, season, calc, a, b])
  const paintData: PaintData | null = useMemo(() => paintFor(options.paint, g, calc, kind, season, a, b), [options.paint, g, calc, kind, season, a, b])
  const maxFlow = useMemo(() => Math.max(1, ...[...water.values()].flat().map(w => w.flow ?? 0)), [water])
  const usedMonths = useMemo(() => {
    const s = new Set<number>()
    win.months.forEach(m => m.forEach((v, i) => { if (v > 0) s.add(i) }))
    return win.order.filter(m => s.has(m))
  }, [win])

  useImperativeHandle(ref, () => ({
    fit: resetView,
    focus: (w: number) => {
      const p = placed.find(q => q.well === w)
      if (!p) return
      const k = 2.6
      setView({ k, tx: size.w / 2 - k * (fit.s * p.x + fit.ox), ty: size.h / 2 - k * (fit.s * p.y + fit.oy) })
    },
    toPng: async () => {
      const el = svg.current!
      const clone = el.cloneNode(true) as SVGSVGElement
      clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
      clone.setAttribute('width', String(size.w * 2)); clone.setAttribute('height', String(size.h * 2))
      clone.querySelectorAll('.no-export').forEach(n => n.remove())
      const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(clone))
      const img = new Image()
      await new Promise<void>((ok, fail) => { img.onload = () => ok(); img.onerror = () => fail(new Error('Не удалось собрать картинку')); img.src = url })
      const cv = document.createElement('canvas'); cv.width = size.w * 2; cv.height = size.h * 2
      cv.getContext('2d')!.drawImage(img, 0, 0)
      return await new Promise<Blob>((ok, fail) => cv.toBlob(bl => (bl ? ok(bl) : fail(new Error('Пустая картинка'))), 'image/png'))
    },
  }), [placed, size, fit.s, fit.ox, fit.oy, resetView])

  // колесо мыши — масштаб к курсору (слушатель не пассивный, чтобы страница не прокручивалась)
  useEffect(() => {
    const el = svg.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top
      setView(v => {
        const k = Math.max(0.4, Math.min(24, v.k * Math.exp(-e.deltaY * 0.0015)))
        return { k, tx: px - ((px - v.tx) / v.k) * k, ty: py - ((py - v.ty) / v.k) * k }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const ink = css('--ink') || '#1b2a31', muted = css('--muted') || '#5f7178', bg = css('--surface') || '#fff', line = css('--line') || '#dbe3e5'
  const zoomBy = (f: number) => setView(v => {
    const px = size.w / 2, py = size.h / 2, k = Math.max(0.4, Math.min(24, v.k * f))
    return { k, tx: px - ((px - v.tx) / v.k) * k, ty: py - ((py - v.ty) / v.k) * k }
  })

  const unit = g.layout.mode === 'xy' ? 'м' : ''
  const bar = niceStep(160 / (fit.s * view.k))
  // опорные круги легенды: тот же масштаб, что на карте, но не крупнее 34 px
  const Rpx = rmax * options.scale * fit.s * view.k
  const vTop = (() => {
    const raw = win.scaleMax * Math.min(1, (34 / Rpx) ** 2), p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p
    return (f >= 5 ? 5 : f >= 2 ? 2 : 1) * p
  })()
  const ref3 = [1, 0.4, 0.1].map(f => ({ v: vTop * f, r: Rpx * Math.sqrt((vTop * f) / win.scaleMax) }))
  const refX = [0, 2 * Math.max(ref3[0].r, 2) + 58, 2 * Math.max(ref3[0].r, 2) + 58 + 2 * Math.max(ref3[1].r, 2) + 58]
  const legendH = 52 + 2 * ref3[0].r + (usedMonths.length ? 26 : 0) + (options.water ? 20 : 0)
  const tipWell = tip ? placed.find(p => p.well === tip.well) : null
  const tipIdx = tipWell ? placed.indexOf(tipWell) : -1

  return (
    <div className="map-wrap" ref={wrap}>
      <svg ref={svg} width="100%" height="100%" viewBox={`0 0 ${size.w} ${size.h}`} fontFamily="'PT Sans','Segoe UI',sans-serif"
        onPointerDown={e => {
          const r = wrap.current!.getBoundingClientRect(), bx = e.clientX - r.left, by = e.clientY - r.top
          drag.current = { x: e.clientX, y: e.clientY, moved: false, box: e.shiftKey, x0: bx, y0: by };
          (e.currentTarget as Element).setPointerCapture(e.pointerId)
        }}
        onPointerMove={e => {
          const d = drag.current
          if (d) {
            const dx = e.clientX - d.x, dy = e.clientY - d.y
            if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true
            if (d.moved && d.box) { const r = wrap.current!.getBoundingClientRect(); setBox({ x0: d.x0!, y0: d.y0!, x1: e.clientX - r.left, y1: e.clientY - r.top }); setTip(null) }
            else if (d.moved) { d.x = e.clientX; d.y = e.clientY; setView(v => ({ ...v, tx: v.tx + dx, ty: v.ty + dy })); setTip(null) }
          } else if (tip) {
            const r = wrap.current!.getBoundingClientRect(); setTip({ ...tip, x: e.clientX - r.left, y: e.clientY - r.top })
          }
        }}
        onPointerUp={e => {
          const d = drag.current, moved = d?.moved
          drag.current = null
          if (moved && d?.box && box) {
            const xa = Math.min(box.x0, box.x1), xb = Math.max(box.x0, box.x1), ya = Math.min(box.y0, box.y1), yb = Math.max(box.y0, box.y1)
            const inside = placed.filter(p => { const sx = view.k * (fit.s * p.x + fit.ox) + view.tx, sy = view.k * (fit.s * p.y + fit.oy) + view.ty; return sx >= xa && sx <= xb && sy >= ya && sy <= yb }).map(p => p.well)
            const base = e.ctrlKey || e.metaKey ? group : []
            onGroup(Array.from(new Set([...base, ...inside])))
            if (inside.length === 1 && !base.length) onSelect(inside[0])
          } else if (!moved) {
            const t = document.elementFromPoint(e.clientX, e.clientY)?.closest('[data-well]')
            const w = t ? Number(t.getAttribute('data-well')) : null
            if (w !== null && (e.ctrlKey || e.metaKey || e.shiftKey)) {
              const cur = group.length ? group : selected !== null ? [selected] : []
              onGroup(cur.includes(w) ? cur.filter(x => x !== w) : [...cur, w])
            } else onSelect(w)
          }
          setBox(null)
        }}
        onPointerLeave={() => setTip(null)}
        onPointerOver={e => {
          if (drag.current?.moved) return
          const t = (e.target as Element).closest('[data-well]')
          if (t) { const r = wrap.current!.getBoundingClientRect(); setTip({ x: e.clientX - r.left, y: e.clientY - r.top, well: Number(t.getAttribute('data-well')) }) }
          else setTip(null)
        }}>
        <rect width={size.w} height={size.h} fill={bg} className="map-bg" />
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
          <g transform={`translate(${fit.ox} ${fit.oy}) scale(${fit.s})`}>
            {placed.map((p, n) => ({ p, n })).sort((u, v) => win.stats[v.n].total - win.stats[u.n].total).map(({ p, n }) => (!paintData && ((options.hideIdle && !(win.stats[n].total > 0)) || (options.minValue > 0 && win.stats[n].total < options.minValue * 1e6)) && selected !== p.well && !group.includes(p.well) ? null :
              <Glyph key={p.well} well={p.well} x={p.x} y={p.y} rmax={rmax} total={win.stats[n].total}
                r={win.stats[n].total > 0 ? rmax * options.scale * Math.sqrt(win.stats[n].total / win.scaleMax) : rmax * 0.25}
                share={win.stats[n].total > 0 ? win.stats[n].total / win.sumAll : 0}
                months={win.months[n] || []} order={win.order} sectors={options.sectors === 'months'}
                paint={paintData ? (paintData.vals.has(p.well) ? { color: rampColor(paintData.stops, (paintData.vals.get(p.well)!.v - paintData.lo) / (paintData.hi - paintData.lo)), label: paintData.vals.get(p.well)!.label } : null) : undefined}
                water={options.water ? water.get(p.well) || [] : []} maxFlow={maxFlow} showShare={options.share}
                selected={selected === p.well || group.includes(p.well)} dim={!!tip && tip.well !== p.well && !group.includes(p.well)} label={options.labels === 'none' ? '' : options.labels === 'val' && win.stats[n].total > 0 ? fmtMln(win.stats[n].total) : String(p.well)} />
            ))}
          </g>
        </g>
        {/* подписи и легенда рисуются в координатах экрана, поэтому попадают и в PNG */}
        <rect x={54} y={10} width={Math.max(250, title.length * 7.4)} height={46} rx={8} fill={bg} fillOpacity={0.88} />
        <text x={62} y={29} fontSize={17} fontWeight={700} fill={ink}>{title.split(' · ').slice(0, 2).join(' · ')}</text>
        <text x={62} y={47} fontSize={13} fill={muted}>{title.split(' · ')[2] || ''}</text>
        {!paintData && (
        <g transform={`translate(14 ${size.h - 14 - legendH})`}>
          <rect width={Math.max(250, usedMonths.length * 50 + 24)} height={legendH} rx={8} fill={bg} fillOpacity={0.9} stroke={line} />
          <text x={12} y={19} fontSize={12} fontWeight={700} fill={ink}>Площадь круга — расход газа за окно, млн м³</text>
          {ref3.map((c, i) => (
            <g key={i} transform={`translate(${12 + refX[i]} ${24 + 2 * ref3[0].r})`}>
              <circle r={Math.max(c.r, 2)} cx={Math.max(c.r, 2)} cy={-Math.max(c.r, 2)} fill={GAS} fillOpacity={0.85} />
              <text x={2 * Math.max(c.r, 2) + 5} y={-2} fontSize={11} fill={muted}>{fmtMln(c.v)}</text>
            </g>
          ))}
          <text x={12} y={legendH - (usedMonths.length ? 10 : 10) - (usedMonths.length ? 26 : 0) - (options.water ? 20 : 0)} fontSize={11} fill={muted}>{options.fixed ? 'масштаб по максимуму сезона' : 'масштаб по максимуму окна'}</text>
          {usedMonths.length > 0 && <g transform={`translate(12 ${legendH - 24 - (options.water ? 20 : 0)})`}>
            {usedMonths.map((m, i) => <g key={m} transform={`translate(${i * 50} 0)`}><rect width={13} height={13} rx={3} fill={MONTH_COLOR[m]} /><text x={18} y={11} fontSize={12} fill={ink}>{MONTH_SHORT[m]}</text></g>)}</g>}
          {options.water && <g transform={`translate(12 ${legendH - 24})`}><rect width={13} height={9} rx={2} y={2} fill={WATER} /><text x={18} y={11} fontSize={11} fill={ink}>вынос воды: кольцо ∝ л/ч, число — ВФ, л/1000 м³</text></g>}
        </g>
        )}
        {paintData && (
          <g transform={`translate(14 ${size.h - 14 - 96})`}>
            <rect width={300} height={96} rx={8} fill={bg} fillOpacity={0.9} stroke={line} />
            <text x={12} y={19} fontSize={12} fontWeight={700} fill={ink}>{paintData.title}</text>
            <defs><linearGradient id="paintramp" x1="0" x2="1">{[0, 0.25, 0.5, 0.75, 1].map(t => <stop key={t} offset={t} stopColor={rampColor(paintData.stops, t)} />)}</linearGradient></defs>
            <rect x={12} y={30} width={276} height={14} rx={3} fill="url(#paintramp)" />
            <text x={12} y={60} fontSize={11} fill={muted}>{paintData.fmt(paintData.lo)}</text>
            <text x={288} y={60} fontSize={11} fill={muted} textAnchor="end">{paintData.fmt(paintData.hi)}</text>
            <circle cx={18} cy={78} r={5} fill="#c5cdd0" stroke="#8a979c" /><text x={28} y={82} fontSize={11} fill={ink}>нет данных · {paintData.note}</text>
          </g>)}
        <g transform={`translate(${size.w - 40} ${size.h - 92})`}>
          <circle r={17} fill={bg} stroke={line} /><path d="M0,-12 L5,6 L0,2 L-5,6Z" fill={ink} /><text y={-21} textAnchor="middle" fontSize={11} fontWeight={700} fill={ink}>С</text>
        </g>
        {unit && <g transform={`translate(${size.w - 60 - 160} ${size.h - 22})`}>
          <path d={`M0,0V-6H${bar * fit.s * view.k}V0`} fill="none" stroke={ink} strokeWidth={1.5} />
          <text y={-10} fontSize={11} fill={ink}>{bar >= 1000 ? fmt1(bar / 1000) + ' км' : bar + ' м'}</text></g>}
      </svg>
      <button type="button" className="quiet layers-toggle no-export" onClick={() => setLayersOpen(v => !v)} aria-expanded={layersOpen}>{layersOpen ? 'Скрыть настройки' : 'Настройки карты'}</button>
      {layersOpen && <div className="layers no-export">
        <label className="sel paintsel" title="Чем красить скважины"><span>Раскраска</span>
          <select value={options.paint} onChange={e => onOptions({ paint: e.target.value as Paint })}>{PAINTS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
        {!paintData && <><div className="segmented" role="radiogroup" aria-label="Секторы на круге">
          <button type="button" role="radio" aria-checked={options.sectors === 'months'} onClick={() => onOptions({ sectors: 'months' })} title="Круг разделён на секторы по месяцам">По месяцам</button>
          <button type="button" role="radio" aria-checked={options.sectors === 'plain'} onClick={() => onOptions({ sectors: 'plain' })}>Один цвет</button></div>
        <label className="sel" title="Множитель размера кругов"><span>Размер</span>
          <input type="range" min={0.4} max={2.5} step={0.1} value={options.scale} onChange={e => onOptions({ scale: Number(e.target.value) })} /></label>
        <label className="sel" title="Что писать на круге"><span>Подпись</span>
          <select value={options.labels} onChange={e => onOptions({ labels: e.target.value as 'num' | 'val' | 'none' })}><option value="num">номер</option><option value="val">расход</option><option value="none">нет</option></select></label>
        <label className="check" title="Скрыть скважины без расхода в окне"><input type="checkbox" checked={options.hideIdle} onChange={e => onOptions({ hideIdle: e.target.checked })} />Только работающие</label>
        <label className="sel" title="Скрыть скважины с расходом ниже порога"><span>Порог, млн м³</span>
          <input type="number" min={0} step={0.5} className="thr" value={options.minValue} onChange={e => onOptions({ minValue: Math.max(0, Number(e.target.value) || 0) })} /></label>
        <label className="check"><input type="checkbox" checked={options.water} onChange={e => onOptions({ water: e.target.checked })} />Вода</label>
        <label className="check"><input type="checkbox" checked={options.share} onChange={e => onOptions({ share: e.target.checked })} />Доли</label>
        <label className="check" title="Размер кругов считается от максимума всего сезона, а не выбранного окна"><input type="checkbox" checked={options.fixed} onChange={e => onOptions({ fixed: e.target.checked })} />Масштаб сезона</label></>}
      </div>}
      {box && <div className="selbox no-export" style={{ left: Math.min(box.x0, box.x1), top: Math.min(box.y0, box.y1), width: Math.abs(box.x1 - box.x0), height: Math.abs(box.y1 - box.y0) }} />}
      {group.length > 1 && <div className="group-chip no-export">Выбрано: {group.length} <button type="button" className="quiet" onClick={() => onGroup([])}>Сбросить</button></div>}
      <div className="map-tools no-export">
        <button type="button" className="icon" title="Приблизить" onClick={() => zoomBy(1.5)}>+</button>
        <button type="button" className="icon" title="Отдалить" onClick={() => zoomBy(1 / 1.5)}>−</button>
        <button type="button" className="icon" title="Показать всю карту" onClick={resetView}>
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" /></svg></button>
      </div>
      {tip && tipWell && (
        <div className="tip" style={{ left: Math.min(tip.x + 14, size.w - 230), top: Math.min(tip.y + 14, size.h - 150) }}>
          <b>Скважина {tipWell.well}</b>{tipWell.dir && <span className="muted"> · {tipWell.dir}</span>}
          <div className="tip-grid">
            <svg viewBox="0 0 200 34" className="tip-spark" aria-hidden="true">{(() => { const row = calc.flow[calc.index.get(tipWell.well) ?? 0] || [], mx = Math.max(1, ...row), bw = 200 / Math.max(1, row.length)
              return <><rect x={a * bw} width={Math.max(1, (b - a + 1) * bw)} height={34} className="daily-win" />{row.map((v, j) => v > 0 && <rect key={j} x={j * bw} width={Math.max(0.5, bw - 0.3)} y={34 - (v / mx) * 32} height={(v / mx) * 32} fill={GAS} opacity={j >= a && j <= b ? 1 : 0.4} />)}</> })()}</svg>
            <span>Накоплено</span><b>{fmtMln(win.stats[tipIdx].total)} млн м³</b>
            <span>Среднее за день с расходом</span><b>{fmtTh(win.stats[tipIdx].mean)} тыс. м³</b>
            <span>Дней с расходом</span><b>{win.stats[tipIdx].days}</b>
            <span>Доля ГСП</span><b>{win.stats[tipIdx].total > 0 ? fmtPct(win.stats[tipIdx].total / win.sumAll) : '—'}</b>
            {paintData && <span className="tip-water">{paintData.vals.get(tipWell.well)?.tip || 'Нет данных для этой раскраски'}</span>}
            {(water.get(tipWell.well) || []).map((w, i) => (
              <span key={i} className="tip-water">{MONTH_NAME[w.month]} {w.year}: {w.note !== 'Ок' ? w.note : (w.flow ?? 0) + ' л/ч · ВФ ' + Math.round(w.factor ?? 0)}</span>
            ))}
          </div>
        </div>
      )}
      {far.length > 0 && <div className="far-chip no-export" title={'Далёкие скважины: ' + far.join(', ')}>{frameAll ? 'Показаны все скважины' : `За кадром: ${far.length} далёк. скв.`} <button type="button" className="quiet" onClick={() => setFrameAll(v => !v)}>{frameAll ? 'Только основная группа' : 'Показать все'}</button></div>}
      {geo.unplaced.length > 0 && <div className="unplaced no-export" title={geo.unplaced.join(', ')}>Без координат: {geo.unplaced.length} скв. (есть в таблице)</div>}
      {!placed.length && <div className="empty-map">Для этого ГСП нет положений скважин. Задайте карту-сетку или файл XY в разделе «Данные».</div>}
      <span className="sr-only">{fmtDay(calc.days[a])} — {fmtDay(calc.days[b])}</span>
    </div>
  )
})
export default MapView
