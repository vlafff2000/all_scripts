import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, MarkAreaComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fmtDay } from './model'

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, DataZoomComponent, MarkAreaComponent, CanvasRenderer])

/** x — дни (для временной оси с неравномерными замерами); area — заливка под линией. */
export interface Series { key: string | number; label: string; color: string; y: number[]; x?: number[]; dash?: boolean; bold?: boolean; area?: boolean }
interface Props {
  days?: number[]; labels?: string[]; series: Series[]; mode: 'bars' | 'lines'; win?: [number, number]
  fmt: (v: number) => string; unit: string; height?: number; compact?: boolean; interactive?: boolean; label: string
  onPick?: (j: number) => void; barColor?: (j: number) => string | undefined
  yScale?: boolean; group?: string; gapDays?: number; xRange?: [number, number]
  stack?: boolean; highlight?: string | null
}

const cssVar = (name: string, fb: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fb
const resolve = (c: string) => { const m = /^var\((--[\w-]+)\)$/.exec(c); return m ? cssVar(m[1], '#888') : c }
const alpha = (hex: string, a: number) => {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return hex
  const n = parseInt(m[1], 16)
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`
}
const num = (s: string) => { const v = Number(s.trim().replace(/\s/g, '').replace(',', '.')); return s.trim() !== '' && Number.isFinite(v) ? v : null }

/** График в стиле Газового атласа (ECharts): колесо — масштаб, перетаскивание — сдвиг, ползунки и рамка на обеих осях,
 *  ввод границ осей, логарифмическая шкала Y. Для мини-графиков (compact) — только подсказка при наведении. */
export default function MiniChart({ days = [], labels, series, mode, win, fmt, unit, height = 150, compact, interactive = true, label, onPick, barColor, yScale, group, gapDays = 45, xRange, stack, highlight }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const inst = useRef<echarts.ECharts | null>(null)
  const [log, setLog] = useState(false)
  const [boxZoom, setBoxZoom] = useState(false)
  const [zoomed, setZoomed] = useState(false)
  const [axes, setAxes] = useState(false)
  const [theme, setTheme] = useState(0)
  const [bounds, setBounds] = useState({ x0: '', x1: '', y0: '', y1: '' })
  const pick = useRef(onPick); pick.current = onPick
  const full = interactive && !compact
  const isTime = series.some(s => s.x)
  const names = useMemo(() => labels ?? days.map(d => fmtDay(d)), [labels, days])
  const nd = names.length
  const xr = xRange ?? (isTime ? [Math.min(...series.flatMap(s => s.x ?? [])), Math.max(...series.flatMap(s => s.x ?? []))] : [0, 0])

  useEffect(() => {
    const el = document.documentElement
    const mo = new MutationObserver(() => setTheme(t => t + 1))
    mo.observe(el, { attributes: true, attributeFilter: ['data-theme'] })
    return () => mo.disconnect()
  }, [])

  useEffect(() => {
    const el = box.current
    if (!el) return
    const ch = echarts.init(el, undefined, { renderer: 'canvas' })
    inst.current = ch
    if (group) { ch.group = group; echarts.connect(group) }
    const ro = new ResizeObserver(() => ch.resize())
    ro.observe(el)
    ch.on('click', (p: unknown) => { const i = (p as { dataIndex?: number }).dataIndex; if (typeof i === 'number') pick.current?.(i) })
    return () => { ro.disconnect(); ch.dispose(); inst.current = null }
  }, [])

  const dataKey = nd + '|' + names[0] + '|' + names[nd - 1] + '|' + xr[0] + '|' + xr[1]
  const readBounds = useCallback(() => {
    const ch = inst.current
    if (!ch || !full) return
    const dz = (ch.getOption() as { dataZoom?: { start?: number; end?: number; startValue?: number; endValue?: number }[] }).dataZoom || []
    const x = dz[0], y = dz[2]
    setZoomed(dz.some(d => (d.start ?? 0) > 0.01 || (d.end ?? 100) < 99.99))
    const fx = (v: number | undefined) => (v === undefined ? '' : isTime ? fmtDay(Math.round(v)) : names[Math.max(0, Math.min(nd - 1, Math.round(v)))] ?? '')
    const fy = (v: number | undefined) => (v === undefined ? '' : String(Number(v.toPrecision(5))))
    const nb = { x0: fx(x?.startValue), x1: fx(x?.endValue), y0: fy(y?.startValue), y1: fy(y?.endValue) }
    setBounds(o => (o.x0 === nb.x0 && o.x1 === nb.x1 && o.y0 === nb.y0 && o.y1 === nb.y1 ? o : nb))
  }, [full, names, nd, isTime])

  useEffect(() => {
    const ch = inst.current
    if (!ch) return
    const ink = cssVar('--ink', '#1b2a31'), muted = cssVar('--muted', '#5f7178'), grid = cssVar('--line-soft', '#edf1f2'), axis = cssVar('--line-strong', '#b9c7cb')
    const surface = cssVar('--surface', '#fff'), accent = cssVar('--accent', '#149ba5')
    const fs = compact ? 11 : 12
    const val = (v: number) => (log && v <= 0 ? null : v)
    const sr = series.map((s, k) => {
      const color = resolve(s.color)
      const base = {
        name: s.label, silent: !full,
        data: s.x ? s.x.flatMap((d, i) => (i && gapDays && d - s.x![i - 1] > gapDays ? [[(d + s.x![i - 1]) / 2, null], [d, val(s.y[i])]] : [[d, val(s.y[i])]])) : s.y.map(val),
        markArea: k === 0 && win ? { silent: true, itemStyle: { color: alpha(accent, 0.12) }, data: [[{ xAxis: isTime ? win[0] : Math.max(0, win[0]) }, { xAxis: isTime ? win[1] : Math.min(nd - 1, win[1]) }]] } : undefined,
      }
      return mode === 'bars'
        ? { ...base, type: 'bar' as const, stack: stack ? 'all' : undefined, barCategoryGap: '12%', itemStyle: { opacity: highlight && highlight !== s.label ? 0.3 : 1, color: barColor ? (p: { dataIndex: number }) => resolve(barColor(p.dataIndex) ?? s.color) : color } }
        : { ...base, type: 'line' as const, showSymbol: !!s.x, symbolSize: 4, areaStyle: s.area ? { color: alpha(color, 0.22) } : undefined, lineStyle: { width: s.bold ? 2.8 : 2, type: s.dash ? ('dashed' as const) : ('solid' as const), color }, itemStyle: { color }, emphasis: { focus: 'series' as const } }
    })
    const zoomBase = { filterMode: 'none' as const, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false }
    const slider = { type: 'slider' as const, filterMode: 'none' as const, showDetail: false, brushSelect: false, borderColor: axis, backgroundColor: 'transparent', fillerColor: alpha(accent, 0.18), handleSize: '90%', textStyle: { color: muted }, dataBackground: { lineStyle: { color: axis }, areaStyle: { color: alpha(axis, 0.3) } } }
    const dataZoom = full ? [
      { type: 'inside' as const, xAxisIndex: 0, ...zoomBase },
      { ...slider, xAxisIndex: 0, height: 16, bottom: 6 },
      { type: 'inside' as const, yAxisIndex: 0, filterMode: 'none' as const, zoomOnMouseWheel: 'shift' as const, moveOnMouseMove: 'shift' as const, moveOnMouseWheel: false },
      { ...slider, yAxisIndex: 0, width: 14, right: 4, top: 12, bottom: 34 },
    ] : []
    ch.setOption({
      animation: false, backgroundColor: 'transparent', textStyle: { fontFamily: "'PT Sans','Segoe UI',sans-serif", fontSize: fs, color: muted },
      grid: { left: 6, right: full ? 28 : 8, top: 12, bottom: full ? 40 : 4, containLabel: true },
      xAxis: isTime ? { type: 'value', min: xr[0], max: xr[1], axisLine: { lineStyle: { color: axis } }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { color: muted, fontSize: fs, hideOverlap: true, formatter: (v: number) => fmtDay(v).slice(3) }, axisPointer: { show: interactive, label: { formatter: (p: { value: number }) => fmtDay(Math.round(p.value)) } } } : { type: 'category', data: names, boundaryGap: mode === 'bars', axisLine: { lineStyle: { color: axis } }, axisTick: { show: false }, axisLabel: { color: muted, fontSize: fs, hideOverlap: true, formatter: (v: string) => (labels ? v : v.slice(0, 5)) }, axisPointer: { show: interactive } },
      yAxis: { type: log ? 'log' : 'value', logBase: 10, scale: !!yScale, axisLabel: { color: muted, fontSize: fs, formatter: (v: number) => fmt(v) }, splitLine: { lineStyle: { color: grid, type: 'dashed' } }, axisLine: { show: false }, axisPointer: { show: false } },
      dataZoom,
      series: sr,
      tooltip: interactive ? {
        trigger: 'axis', confine: true, backgroundColor: surface, borderColor: cssVar('--line', '#dbe3e5'), textStyle: { color: ink, fontSize: 12.5 }, extraCssText: 'box-shadow:0 6px 18px rgba(27,42,49,.25);border-radius:8px',
        axisPointer: { type: mode === 'bars' && !isTime ? 'shadow' : 'line', shadowStyle: { color: alpha(ink, 0.06) }, lineStyle: { color: alpha(ink, 0.45) } },
        formatter: (ps: unknown) => {
          const a = (Array.isArray(ps) ? ps : [ps]) as { axisValue: number; axisValueLabel: string; seriesName: string; value: number | null | (number | null)[]; color: string }[]
          const rows = a.map(p => ({ ...p, value: Array.isArray(p.value) ? p.value[1] : p.value })).filter(p => p.value !== null && p.value !== undefined)
          if (!rows.length) return ''
          return `<b>${isTime ? fmtDay(Math.round(a[0].axisValue)) : a[0].axisValueLabel}</b>` + rows.map(p => `<div><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${p.color};margin-right:5px"></span>${rows.length > 1 ? p.seriesName + ': ' : ''}<b>${fmt(p.value as number)}</b> ${unit}</div>`).join('')
        },
      } : { show: false },
    }, { replaceMerge: ['series'] })
    ch.dispatchAction({ type: 'takeGlobalCursor', key: 'dataZoomSelect', dataZoomSelectActive: full && boxZoom })
    ch.off('datazoom'); if (full) ch.on('datazoom', readBounds)
    readBounds()
  }, [stack, highlight, series, names, isTime, xr[0], xr[1], yScale, gapDays, mode, win, fmt, unit, compact, interactive, full, log, boxZoom, theme, labels, nd, barColor, readBounds])

  useEffect(() => { inst.current?.dispatchAction({ type: 'dataZoom', batch: [0, 1, 2, 3].map(i => ({ dataZoomIndex: i, start: 0, end: 100 })) }) }, [dataKey])
  const reset = () => { inst.current?.dispatchAction({ type: 'dataZoom', batch: [0, 1, 2, 3].map(i => ({ dataZoomIndex: i, start: 0, end: 100 })) }); readBounds() }
  const applyX = (a: string, b: string) => {
    const dt = (t: string) => { const m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(t.trim()); return m ? Math.round(Date.UTC(+m[3], +m[2] - 1, +m[1]) / 86400000) : null }
    if (isTime) { const d0 = dt(a), d1 = dt(b); if (d0 !== null && d1 !== null && d1 > d0) inst.current?.dispatchAction({ type: 'dataZoom', dataZoomIndex: 0, startValue: d0, endValue: d1 }); return }
    const find = (t: string) => { const i = names.indexOf(t.trim()); if (i >= 0) return i; const n = num(t); return n !== null ? Math.max(0, Math.min(nd - 1, Math.round(n) - 1)) : null }
    const i0 = find(a), i1 = find(b)
    if (i0 !== null && i1 !== null && i1 > i0) inst.current?.dispatchAction({ type: 'dataZoom', dataZoomIndex: 0, startValue: i0, endValue: i1 })
  }
  const applyY = (a: string, b: string) => {
    const lo = num(a), hi = num(b)
    if (lo !== null && hi !== null && hi > lo && (!log || lo > 0)) inst.current?.dispatchAction({ type: 'dataZoom', dataZoomIndex: 2, startValue: lo, endValue: hi })
  }
  const field = (k: 'x0' | 'x1' | 'y0' | 'y1', ph: string) => (
    <input key={k} value={bounds[k]} placeholder={ph} aria-label={ph} onChange={e => setBounds(b => ({ ...b, [k]: e.target.value }))}
      onKeyDown={e => { if (e.key === 'Enter') { const b = { ...bounds, [k]: (e.target as HTMLInputElement).value }; k[0] === 'x' ? applyX(b.x0, b.x1) : applyY(b.y0, b.y1) } }}
      onBlur={() => (k[0] === 'x' ? applyX(bounds.x0, bounds.x1) : applyY(bounds.y0, bounds.y1))} />)

  return (
    <div className={'chart' + (compact ? ' compact' : '')}>
      {full && (
        <div className="chart-bar">
          <button type="button" className={boxZoom ? 'on' : ''} aria-pressed={boxZoom} title="Выделить область мышью, чтобы приблизить" onClick={() => setBoxZoom(v => !v)}>Рамка</button>
          <button type="button" className={log ? 'on' : ''} aria-pressed={log} title="Логарифмическая шкала по Y" onClick={() => { setLog(v => !v); reset() }}>Лог. Y</button>
          <button type="button" className={axes ? 'on' : ''} aria-pressed={axes} title="Задать границы осей числами" onClick={() => setAxes(v => !v)}>Оси</button>
          <button type="button" disabled={!zoomed} title="Показать всё" onClick={reset}>Сбросить</button>
          <span className="chart-hint">колесо — масштаб, перетаскивание — сдвиг, Shift+колесо — по Y</span>
        </div>
      )}
      {full && axes && (
        <div className="chart-axes"><span>X</span>{field('x0', 'от')}{field('x1', 'до')}<span>Y</span>{field('y0', 'от')}{field('y1', 'до')}</div>
      )}
      <div ref={box} role="img" aria-label={label} style={{ height: height + (full ? 34 : 0), width: '100%' }} />
    </div>
  )
}
