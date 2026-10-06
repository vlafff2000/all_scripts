import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { GspData } from './api'
import { PAINTS, GAS, SEASON_STOPS, SEASON_STOPS_DARK, type PaintData, paintFor, rampColor, type Paint, MONTH_NAME, MONTH_SHORT, SeasonCalc, WATER, fmt1, fmtDay, fmtMln, fmtPct, fmtTh, monthOf, niceStep, place, sectorPath, waterByWell } from './model'

export interface MapOptions { sectors: 'months' | 'plain'; water: boolean; share: boolean; fixed: boolean; paint: Paint; scale: number; labels: 'num' | 'val' | 'none'; hideIdle: boolean; minValue: number }
export interface MapHandle { toPng: () => Promise<Blob>; fit: () => void; focus: (well: number) => void }
interface Props {
  g: GspData; calc: SeasonCalc; kind: string; season: string; a: number; b: number
  options: MapOptions; onOptions: (o: Partial<MapOptions>) => void; selected: number | null; onSelect: (w: number | null) => void; group: number[]; onGroup: (ws: number[]) => void; title: string
  /** Режим сравнения: общий масштаб кругов и общий вид (зум/сдвиг) у двух карт. */
  compact?: boolean; scaleMax?: number; view?: View; onView?: (v: View) => void
}
export interface View { k: number; tx: number; ty: number }
interface Tip { x: number; y: number; well: number }

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** Цвета карты берутся из темы и передаются числами: так они попадают и в PNG, где CSS-переменных нет. */
interface Pal { surface: string; bg: string; grid: string; ink: string; muted: string; line: string; accent: string; water: string; gas: string }
const readPal = (): Pal => ({
  surface: css('--surface') || '#fff', bg: css('--map-bg') || '#f7f9f9', grid: css('--map-grid') || '#e3e9ea', ink: css('--ink') || '#1b2a31',
  muted: css('--muted') || '#5f7178', line: css('--line') || '#dbe3e5', accent: css('--accent') || '#149ba5', water: css('--map-water') || WATER, gas: css('--map-gas') || GAS,
})

const Glyph = memo(function Glyph(p: {
  well: number; x: number; y: number; r: number; rmax: number; total: number; share: number; months: number[]; order: number[]; monthColors: string[]
  sectors: boolean; paint?: { color: string; label: string } | null; water: { factor: number | null; flow: number | null }[]; maxFlow: number; showShare: boolean
  selected: boolean; label: string; dim: boolean; pal: Pal
}) {
  const { x, y, rmax, pal } = p
  const idle = p.paint === undefined ? !(p.total > 0) : !p.paint
  const r = p.paint !== undefined ? (p.paint ? rmax * 0.62 : rmax * 0.24) : idle ? rmax * 0.24 : p.r
  const ring = rmax * 0.05
  const els: React.ReactNode[] = []
  if (idle) {
    els.push(<circle key="c" cx={x} cy={y} r={r} fill={pal.surface} stroke={pal.muted} strokeWidth={rmax * 0.04} strokeDasharray={`${rmax * 0.09} ${rmax * 0.07}`} />)
  } else if (p.paint) {
    els.push(<circle key="c" cx={x} cy={y} r={r} fill={p.paint.color} stroke={pal.surface} strokeWidth={ring} />)
  } else if (!p.sectors) {
    els.push(<circle key="c" cx={x} cy={y} r={r} fill={pal.gas} stroke={pal.surface} strokeWidth={ring} />)
  } else {
    const sum = p.months.reduce((s, v) => s + v, 0) || 1
    const parts = p.order.filter(m => p.months[m] > 0)
    if (parts.length <= 1) els.push(<circle key="c" cx={x} cy={y} r={r} fill={p.monthColors[parts[0] ?? 0] || pal.gas} stroke={pal.surface} strokeWidth={ring} />)
    else {
      let a0 = 0
      for (const m of parts) {
        const a1 = a0 + (p.months[m] / sum) * Math.PI * 2
        els.push(<path key={m} d={sectorPath(x, y, r, a0, a1)} fill={p.monthColors[m]} stroke={pal.surface} strokeWidth={rmax * 0.03} strokeLinejoin="round" />)
        a0 = a1
      }
      els.push(<circle key="o" cx={x} cy={y} r={r} fill="none" stroke={pal.surface} strokeWidth={ring} />)
    }
  }
  // вода: тонкое голубое кольцо снаружи (толщина ∝ л/ч), водный фактор — кружок на кольце
  const ws = p.water.filter(w => (w.flow ?? 0) > 0)
  if (ws.length && !idle) {
    const gap = ws.length > 1 ? 0.16 : 0, span = (Math.PI * 2) / ws.length, r0 = r + rmax * 0.07
    ws.forEach((w, i) => {
      const t = rmax * 0.14 * (0.35 + 0.65 * Math.sqrt((w.flow ?? 0) / (p.maxFlow || 1)))
      els.push(<path key={'w' + i} d={sectorPath(x, y, r0 + t, i * span + gap / 2, (i + 1) * span - gap / 2, r0)} fill={pal.water} />)
    })
    const wf = Math.max(...ws.map(w => w.factor ?? 0))
    if (wf > 0) {
      const t = String(Math.round(wf)), br = rmax * (t.length > 2 ? 0.27 : 0.22), ang = Math.PI / 4, rr = r0 + rmax * 0.08
      const bx = x + rr * Math.sin(ang), by = y - rr * Math.cos(ang)
      els.push(<g key="wf"><circle cx={bx} cy={by} r={br} fill={pal.water} stroke={pal.surface} strokeWidth={rmax * 0.035} />
        <text x={bx} y={by} fontSize={br * (t.length > 2 ? 0.95 : 1.15)} textAnchor="middle" dominantBaseline="central" fill="#fff" fontWeight={700}>{t}</text></g>)
    }
  }
  // подпись: внутри крупного круга — белым, у мелкого — рядом, цветом текста с ореолом фона
  const two = p.paint ? p.paint.label : ''
  const fs = rmax * (p.label.length > 4 ? 0.3 : p.label.length > 3 ? 0.36 : 0.42)
  const inside = !idle && r >= fs * (p.label.length > 3 ? 1.5 : 1.1)
  const share = !idle && p.paint === undefined && p.showShare && p.share >= 0.02 ? (p.share * 100).toFixed(p.share >= 0.1 ? 0 : 1).replace('.', ',') + ' %' : ''
  const lx = inside ? x : x + r + rmax * 0.1, ly = y
  return (
    <g className="glyph" data-well={p.well} opacity={p.dim ? 0.22 : 1}>
      {p.selected && <circle cx={x} cy={y} r={r + rmax * 0.26} fill={pal.accent} fillOpacity={0.16} stroke={pal.accent} strokeWidth={rmax * 0.06} />}
      {els}
      {p.label && (inside
        ? <text x={lx} y={ly - (two || (share && r > fs * 2) ? fs * 0.38 : 0)} fontSize={fs} textAnchor="middle" dominantBaseline="central" fontWeight={700} fill="#fff"
            stroke="rgba(30,8,12,.45)" strokeWidth={fs * 0.14} paintOrder="stroke" strokeLinejoin="round">{p.label}</text>
        : <text x={lx} y={ly} fontSize={fs * 0.9} dominantBaseline="central" fontWeight={700} fill={idle ? pal.muted : pal.ink}
            stroke={pal.bg} strokeWidth={fs * 0.28} paintOrder="stroke" strokeLinejoin="round">{p.label}{share && <tspan fontWeight={400} fill={pal.muted}> · {share}</tspan>}</text>)}
      {inside && (two || (share && r > fs * 2)) && <text x={x} y={y + fs * 0.62} fontSize={fs * 0.62} textAnchor="middle" dominantBaseline="central" fill="#fff" fillOpacity={0.92}
        stroke="rgba(30,8,12,.4)" strokeWidth={fs * 0.08} paintOrder="stroke">{two || share}</text>}
    </g>
  )
})

function niceCoord(v: number) { return Math.round(v).toLocaleString('ru-RU') }

const MapView = forwardRef<MapHandle, Props>(function MapView({ g, calc, kind, season, a, b, options, onOptions, selected, onSelect, group, onGroup, title, compact, scaleMax, view: viewProp, onView }, ref) {
  const wrap = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 800, h: 560 })
  const [viewOwn, setViewOwn] = useState<View>({ k: 1, tx: 0, ty: 0 })
  const view = viewProp || viewOwn
  const viewNow = useRef(view); viewNow.current = view
  const setView = useCallback((u: View | ((v: View) => View)) => {
    const n = typeof u === 'function' ? u(viewNow.current) : u
    viewNow.current = n; setViewOwn(n); onView?.(n)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onView])
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
  const M = 64, top = 64
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
    return { stats, sumAll, scaleMax: scaleMax || (options.fixed ? maxSeason : maxWin), order, months }
  }, [placed, calc, a, b, options.sectors, options.fixed, scaleMax])

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

  const themeKey = document.documentElement.dataset.theme || ''
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const pal = useMemo(readPal, [themeKey])
  const zoomBy = (f: number) => setView(v => {
    const px = size.w / 2, py = size.h / 2, k = Math.max(0.4, Math.min(24, v.k * f))
    return { k, tx: px - ((px - v.tx) / v.k) * k, ty: py - ((py - v.ty) / v.k) * k }
  })
  // месяцы окна: цвет по порядку внутри сезона (раньше — светлее)
  const monthColors = useMemo(() => {
    const c: string[] = Array(12).fill(pal.gas)
    const stops = themeKey === 'dark' ? SEASON_STOPS_DARK : SEASON_STOPS
    usedMonths.forEach((m, i) => { c[m] = rampColor(stops, usedMonths.length > 1 ? i / (usedMonths.length - 1) : 0.5) })
    return c
  }, [usedMonths, pal.gas, themeKey])

  const unit = g.layout.mode === 'xy' ? 'м' : ''
  const K = fit.s * view.k
  const sx = (mx: number) => view.k * (fit.s * mx + fit.ox) + view.tx, sy = (my: number) => view.k * (fit.s * my + fit.oy) + view.ty
  const bar = niceStep(140 / K)
  // координатная сетка (только для настоящих координат XY)
  const grid = useMemo(() => {
    if (!unit || !placed.length) return null
    const mx0 = ((0 - view.tx) / view.k - fit.ox) / fit.s, mx1 = ((size.w - view.tx) / view.k - fit.ox) / fit.s
    const my0 = ((0 - view.ty) / view.k - fit.oy) / fit.s, my1 = ((size.h - view.ty) / view.k - fit.oy) / fit.s
    const st = niceStep(Math.max(mx1 - mx0, my1 - my0), 7)
    const xs: number[] = [], ys: number[] = []
    for (let v = Math.ceil(mx0 / st) * st; v <= mx1; v += st) xs.push(v)
    for (let v = Math.ceil(my0 / st) * st; v <= my1; v += st) ys.push(v)
    return { xs, ys }
  }, [unit, placed.length, view, fit.s, fit.ox, fit.oy, size])
  // «пятно» месторождения: объединение мягких кругов вокруг скважин
  const halo = Math.max(rmax * 1.5, spacing * 0.9)

  // легенда размеров: вложенные круги того же масштаба, что на карте (не крупнее 30 px)
  const Rpx = rmax * options.scale * K
  const vTop = (() => {
    const raw = win.scaleMax * Math.min(1, (30 / Math.max(Rpx, 1e-6)) ** 2), q = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / q
    return (f >= 5 ? 5 : f >= 2 ? 2 : 1) * q
  })()
  const refs = [1, 0.4, 0.1].map(f => ({ v: vTop * f, r: Math.max(2.5, Rpx * Math.sqrt((vTop * f) / win.scaleMax)) }))
  const R0 = refs[0].r
  // подписи легенды не налезают друг на друга: не ближе 14 px по вертикали
  const labY: number[] = []
  refs.forEach((c, i) => { const want = 34 + 2 * R0 - 2 * c.r; labY.push(i ? Math.max(want, labY[i - 1] + 14) : want) })
  const sizeH = Math.max(2 * R0, labY[labY.length - 1] - 34 + 6)
  const LW = 248
  const legH = 46 + sizeH + (!paintData && !compact && usedMonths.length > 1 ? 44 : 0) + (!paintData && !compact && options.water ? 26 : 0)
  const tipWell = tip ? placed.find(q => q.well === tip.well) : null
  const tipIdx = tipWell ? placed.indexOf(tipWell) : -1
  const [t1, t2] = [title.split(' · ').slice(0, 2).join(' · '), title.split(' · ')[2] || '']

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
            const inside = placed.filter(q => { const X = sx(q.x), Y = sy(q.y); return X >= xa && X <= xb && Y >= ya && Y <= yb }).map(q => q.well)
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
        <defs>
          <filter id="mapShadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="4" floodColor="#0b1418" floodOpacity="0.14" /></filter>
        </defs>
        <rect width={size.w} height={size.h} fill={pal.bg} className="map-bg" />
        {grid && <g className="map-grid">
          {grid.xs.map(v => <line key={'x' + v} x1={sx(v)} x2={sx(v)} y1={0} y2={size.h} stroke={pal.grid} strokeWidth={1} />)}
          {grid.ys.map(v => <line key={'y' + v} y1={sy(v)} y2={sy(v)} x1={0} x2={size.w} stroke={pal.grid} strokeWidth={1} />)}
          {grid.xs.filter(v => sx(v) > LW + 30 && sx(v) < size.w - 120).map(v => <text key={'tx' + v} x={sx(v) + 4} y={size.h - 6} fontSize={10} fill={pal.muted} opacity={0.75}>{niceCoord(v)}</text>)}
          {grid.ys.filter(v => sy(v) > 70 && sy(v) < size.h - 150).map(v => <text key={'ty' + v} x={size.w - 6} y={sy(v) - 4} fontSize={10} fill={pal.muted} opacity={0.75} textAnchor="end">{niceCoord(-v)}</text>)}
        </g>}
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
          <g transform={`translate(${fit.ox} ${fit.oy}) scale(${fit.s})`}>
            <g opacity={0.07} fill={pal.accent}>{placed.map(q => <circle key={q.well} cx={q.x} cy={q.y} r={halo} />)}</g>
            {placed.map((q, n) => ({ q, n })).sort((u, v) => win.stats[v.n].total - win.stats[u.n].total).map(({ q, n }) => (!paintData && ((options.hideIdle && !(win.stats[n].total > 0)) || (options.minValue > 0 && win.stats[n].total < options.minValue * 1e6)) && selected !== q.well && !group.includes(q.well) ? null :
              <Glyph key={q.well} well={q.well} x={q.x} y={q.y} rmax={rmax} total={win.stats[n].total} pal={pal}
                r={win.stats[n].total > 0 ? rmax * options.scale * Math.sqrt(win.stats[n].total / win.scaleMax) : rmax * 0.25}
                share={win.stats[n].total > 0 ? win.stats[n].total / win.sumAll : 0}
                months={win.months[n] || []} order={win.order} monthColors={monthColors} sectors={options.sectors === 'months'}
                paint={paintData ? (paintData.vals.has(q.well) ? { color: rampColor(paintData.stops, (paintData.vals.get(q.well)!.v - paintData.lo) / (paintData.hi - paintData.lo)), label: paintData.vals.get(q.well)!.label } : null) : undefined}
                water={options.water ? water.get(q.well) || [] : []} maxFlow={maxFlow} showShare={options.share}
                selected={selected === q.well || group.includes(q.well)} dim={!!tip && tip.well !== q.well && !group.includes(q.well)} label={options.labels === 'none' ? '' : options.labels === 'val' && win.stats[n].total > 0 ? fmtMln(win.stats[n].total) : String(q.well)} />
            ))}
          </g>
        </g>
        {/* заголовок и легенда рисуются в координатах экрана, поэтому попадают и в PNG */}
        <text x={18} y={32} fontSize={compact ? 15 : 18} fontWeight={700} fill={pal.ink} stroke={pal.bg} strokeWidth={5} paintOrder="stroke" strokeLinejoin="round">{t1}</text>
        <text x={18} y={compact ? 49 : 51} fontSize={compact ? 12 : 13} fill={pal.muted} stroke={pal.bg} strokeWidth={4} paintOrder="stroke" strokeLinejoin="round">{t2}</text>
        <g transform={`translate(14 ${size.h - 14 - (paintData ? 92 : legH)})`}>
          <rect width={LW} height={paintData ? 92 : legH} rx={10} fill={pal.surface} fillOpacity={0.96} stroke={pal.line} filter="url(#mapShadow)" />
          {paintData ? <>
            <text x={14} y={22} fontSize={12.5} fontWeight={700} fill={pal.ink}>{paintData.title}</text>
            <defs><linearGradient id="paintramp" x1="0" x2="1">{[0, 0.25, 0.5, 0.75, 1].map(t => <stop key={t} offset={t} stopColor={rampColor(paintData.stops, t)} />)}</linearGradient></defs>
            <rect x={14} y={32} width={LW - 28} height={10} rx={5} fill="url(#paintramp)" />
            <text x={14} y={57} fontSize={11} fill={pal.muted}>{paintData.fmt(paintData.lo)}</text>
            <text x={LW - 14} y={57} fontSize={11} fill={pal.muted} textAnchor="end">{paintData.fmt(paintData.hi)}</text>
            <circle cx={19} cy={75} r={4.5} fill={pal.surface} stroke={pal.muted} strokeDasharray="2 1.6" /><text x={30} y={79} fontSize={11} fill={pal.muted}>нет данных · {paintData.note}</text>
          </> : <>
            <text x={14} y={22} fontSize={12.5} fontWeight={700} fill={pal.ink}>Расход газа за окно</text>
            <text x={LW - 14} y={22} fontSize={11} fill={pal.muted} textAnchor="end">млн м³ · {options.fixed ? 'шкала сезона' : 'шкала окна'}</text>
            {refs.map((c, i) => (
              <g key={i}>
                <circle cx={14 + R0} cy={34 + 2 * R0 - c.r} r={c.r} fill={pal.gas} fillOpacity={0.1 + i * 0.12} stroke={pal.gas} strokeWidth={1} />
                <polyline points={`${14 + R0},${34 + 2 * R0 - 2 * c.r} ${14 + 2 * R0 + 6},${34 + 2 * R0 - 2 * c.r} ${14 + 2 * R0 + 14},${labY[i]}`} fill="none" stroke={pal.muted} strokeWidth={0.8} strokeDasharray="2 2" />
                <text x={14 + 2 * R0 + 18} y={labY[i]} fontSize={11} fill={pal.ink} dominantBaseline="central">{fmtMln(c.v)}</text>
              </g>
            ))}
            {!compact && usedMonths.length > 1 && <g transform={`translate(14 ${46 + sizeH})`}>
              <text y={0} fontSize={11} fill={pal.muted}>Секторы — месяцы окна, раньше светлее</text>
              {usedMonths.map((m, i) => {
                const w = (LW - 28) / usedMonths.length
                return <g key={m} transform={`translate(${i * w} 8)`}><rect width={w - 2} height={10} rx={3} fill={monthColors[m]} /><text x={(w - 2) / 2} y={25} fontSize={10.5} fill={pal.ink} textAnchor="middle">{MONTH_SHORT[m]}</text></g>
              })}
            </g>}
            {!compact && options.water && <g transform={`translate(14 ${legH - 14})`}>
              <path d={sectorPath(8, -4, 8, -1.2, 1.2, 5.5)} fill={pal.water} /><circle cx={16} cy={-9} r={4.5} fill={pal.water} />
              <text x={26} y={0} fontSize={11} fill={pal.muted}>вода: кольцо — л/ч, кружок — ВФ</text>
            </g>}
          </>}
        </g>
        {unit && <g transform={`translate(${size.w - 64 - bar * K} ${size.h - 24})`}>
          <rect x={-6} y={-20} width={bar * K + 12} height={26} rx={6} fill={pal.surface} fillOpacity={0.85} />
          <path d={`M0,-2V0H${bar * K}V-2`} fill="none" stroke={pal.ink} strokeWidth={1.5} />
          <rect x={0} y={-2} width={(bar * K) / 2} height={2} fill={pal.ink} />
          <text x={(bar * K) / 2} y={-7} fontSize={11} fill={pal.ink} textAnchor="middle">{bar >= 1000 ? fmt1(bar / 1000) + ' км' : bar + ' м'}</text></g>}
        <g transform={`translate(${size.w - 34} 34)`} className="no-export-keep">
          <circle r={15} fill={pal.surface} stroke={pal.line} filter="url(#mapShadow)" />
          <path d="M0,-10 L4.5,4 L0,1.5 L-4.5,4Z" fill={pal.gas} /><path d="M0,10 L4.5,4 L0,1.5 L-4.5,4Z" fill={pal.muted} opacity={0.5} />
          <text y={-19} textAnchor="middle" fontSize={10} fontWeight={700} fill={pal.muted} stroke={pal.bg} strokeWidth={3} paintOrder="stroke">С</text>
        </g>
      </svg>
      <div className="map-view-ctl no-export">
        <button type="button" className={'view-btn' + (layersOpen ? ' on' : '')} onClick={() => setLayersOpen(v => !v)} aria-expanded={layersOpen} title="Как показывать скважины">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2 1.5 5.5 8 9l6.5-3.5L8 2ZM1.5 8.5 8 12l6.5-3.5M1.5 11.5 8 15l6.5-3.5" /></svg><span className="view-label">Вид карты</span></button>
        {layersOpen && <div className="layers" role="dialog" aria-label="Вид карты">
          <section><h4>Цвет</h4>
            <select value={options.paint} onChange={e => onOptions({ paint: e.target.value as Paint })} aria-label="Раскраска">{PAINTS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
            {!paintData && <div className="segmented" role="radiogroup" aria-label="Секторы на круге">
              <button type="button" role="radio" aria-checked={options.sectors === 'months'} onClick={() => onOptions({ sectors: 'months' })} title="Круг разделён на секторы по месяцам">По месяцам</button>
              <button type="button" role="radio" aria-checked={options.sectors === 'plain'} onClick={() => onOptions({ sectors: 'plain' })}>Один цвет</button></div>}
          </section>
          <section><h4>Круги</h4>
            <label className="row"><span>Размер</span><input type="range" min={0.4} max={2.5} step={0.1} value={options.scale} onChange={e => onOptions({ scale: Number(e.target.value) })} /></label>
            <label className="row"><span>Подпись</span><select value={options.labels} onChange={e => onOptions({ labels: e.target.value as 'num' | 'val' | 'none' })}><option value="num">номер</option><option value="val">расход</option><option value="none">нет</option></select></label>
            {!paintData && <label className="check" title="Размер кругов считается от максимума всего сезона, а не выбранного окна"><input type="checkbox" checked={options.fixed} onChange={e => onOptions({ fixed: e.target.checked })} />Шкала по всему сезону</label>}
          </section>
          {!paintData && <section><h4>Показывать</h4>
            <label className="check"><input type="checkbox" checked={options.hideIdle} onChange={e => onOptions({ hideIdle: e.target.checked })} />Только работающие</label>
            <label className="row" title="Скрыть скважины с расходом ниже порога"><span>Порог, млн м³</span><input type="number" min={0} step={0.5} className="thr" value={options.minValue} onChange={e => onOptions({ minValue: Math.max(0, Number(e.target.value) || 0) })} /></label>
            <label className="check"><input type="checkbox" checked={options.water} onChange={e => onOptions({ water: e.target.checked })} />Вынос воды</label>
            <label className="check"><input type="checkbox" checked={options.share} onChange={e => onOptions({ share: e.target.checked })} />Доля ГСП у подписи</label>
          </section>}
        </div>}
      </div>
      {box && <div className="selbox no-export" style={{ left: Math.min(box.x0, box.x1), top: Math.min(box.y0, box.y1), width: Math.abs(box.x1 - box.x0), height: Math.abs(box.y1 - box.y0) }} />}
      <div className="map-chips no-export">
        {group.length > 1 && <span className="map-chip accent">Выбрано скважин: {group.length}<button type="button" onClick={() => onGroup([])} aria-label="Сбросить выбор">×</button></span>}
        {far.length > 0 && <span className="map-chip" title={'Далёкие скважины: ' + far.join(', ')}>{frameAll ? 'Показаны все скважины' : `За кадром: ${far.length} скв.`}<button type="button" onClick={() => setFrameAll(v => !v)}>{frameAll ? 'Основная группа' : 'Показать'}</button></span>}
        {geo.unplaced.length > 0 && <span className="map-chip warn" title={geo.unplaced.join(', ')}>Без координат: {geo.unplaced.length} скв.</span>}
      </div>
      <div className="map-tools no-export">
        <button type="button" title="Приблизить" onClick={() => zoomBy(1.5)}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg></button>
        <button type="button" title="Отдалить" onClick={() => zoomBy(1 / 1.5)}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10" /></svg></button>
        <button type="button" title="Показать всю карту" onClick={resetView}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" /></svg></button>
      </div>
      {tip && tipWell && (() => {
        const st = win.stats[tipIdx], share = st.total > 0 && win.sumAll > 0 ? st.total / win.sumAll : 0
        const row = calc.flow[calc.index.get(tipWell.well) ?? 0] || [], mx = Math.max(1, ...row), bw = 220 / Math.max(1, row.length)
        const ws = water.get(tipWell.well) || []
        const W = 252, left = tip.x + 18 + W > size.w ? tip.x - 18 - W : tip.x + 18
        return (
          <div className="tip" style={{ left: Math.max(8, left), top: Math.max(8, Math.min(tip.y - 20, size.h - 260)) }}>
            <div className="tip-head"><b>№ {tipWell.well}</b>{tipWell.dir && <span className="tip-dir">{tipWell.dir}</span>}</div>
            {paintData && <div className="tip-paint"><i style={{ background: paintData.vals.has(tipWell.well) ? rampColor(paintData.stops, (paintData.vals.get(tipWell.well)!.v - paintData.lo) / (paintData.hi - paintData.lo)) : 'transparent' }} />{paintData.vals.get(tipWell.well)?.tip || 'Нет данных для этой раскраски'}</div>}
            <div className="tip-hero">{st.total > 0 ? fmtMln(st.total) : '0'}<small> млн м³ за окно</small></div>
            <div className="tip-share"><span><i style={{ width: Math.min(100, share * 100 * 4) + '%' }} /></span>{share > 0 ? fmtPct(share) + ' ГСП' : 'не работала'}</div>
            <svg viewBox="0 0 220 38" className="tip-spark" aria-hidden="true">
              <rect x={a * bw} width={Math.max(1, (b - a + 1) * bw)} height={38} className="daily-win" />
              {row.map((v, j) => v > 0 && <rect key={j} x={j * bw} width={Math.max(0.6, bw - 0.3)} y={38 - (v / mx) * 34} height={(v / mx) * 34} rx={Math.min(1, bw / 3)} fill={pal.gas} opacity={j >= a && j <= b ? 0.95 : 0.3} />)}
              <line x1={0} x2={220} y1={37.5} y2={37.5} stroke={pal.line} />
            </svg>
            <div className="tip-kpis"><div><span>в среднем</span><b>{fmtTh(st.mean)}</b><small>тыс. м³/сут</small></div><div><span>дней с расходом</span><b>{st.days}</b><small>из {b - a + 1}</small></div></div>
            {ws.length > 0 && <div className="tip-water">{ws.map((w, i) => (
              <div key={i}><i />{MONTH_NAME[w.month]} {w.year}<span>{w.note !== 'Ок' ? w.note : (w.flow ?? 0) + ' л/ч · ВФ ' + Math.round(w.factor ?? 0)}</span></div>))}</div>}
          </div>
        )
      })()}
      {!placed.length && <div className="empty-map">Для этого ГСП нет положений скважин. Задайте карту-сетку или файл XY в разделе «Данные».</div>}
      <span className="sr-only">{fmtDay(calc.days[a])} — {fmtDay(calc.days[b])}</span>
    </div>
  )
})
export default MapView
