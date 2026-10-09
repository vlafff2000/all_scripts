import { useMemo } from 'react'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { isoOfDay, mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import type { ChartEvent } from '../../../pxg_core/web-ui/chart/chartTypes'
import { fmtDay } from './model'

/** x — дни (для временной оси с неравномерными замерами); area — заливка под линией. */
export interface Series { key: string | number; label: string; color: string; y: number[]; x?: number[]; dash?: boolean; bold?: boolean; area?: boolean }
interface Props {
  days?: number[]; labels?: string[]; series: Series[]; mode: 'bars' | 'lines'; win?: [number, number]
  fmt: (v: number) => string; unit: string; label: string
  /** прочие свойства прежнего графика (height, group, yScale, barColor…) принимаются, но не нужны: общий график сам их ведёт */
  height?: number; group?: string; yScale?: boolean; onPick?: (j: number) => void
  xRange?: [number, number]; stack?: boolean; highlight?: string | null; gapDays?: number; barColor?: (j: number) => string | undefined
}

const resolve = (c: string) => {
  const m = /^var\((--[\w-]+)\)$/.exec(c)
  return m ? getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || '#888' : c
}
/** Во сколько раз отображаемое число (fmt) отличается от исходного: тыс., млн, доли → проценты. Единицы подписываются в unit. */
const scaleOf = (fmt: (v: number) => string) => {
  const v = parseFloat(fmt(1e9).replace(/[\s  ]/g, '').replace(',', '.'))
  return Number.isFinite(v) && v !== 0 ? v / 1e9 : 1
}

/** График приложения «Карты ГСП»: общий ChartView из Газового Атласа (подсказки, перекрестие, закрепление, зум, оси, PNG, тёмная тема). */
export default function Chart({ days = [], labels, series, mode, win, fmt, unit, label, xRange, stack, highlight, gapDays = 45, barColor }: Props) {
  const chart = useMemo(() => {
    const k = scaleOf(fmt)
    const isTime = series.some(s => s.x) || (!labels && days.length > 0)
    const names = labels ?? days.map(d => fmtDay(d))
    const bars = mode === 'bars'
    // столбцы разных цветов (рост/падение, выделенный) — отдельные ряды с пустыми местами
    const colorAt = (j: number, s: Series) => (barColor && barColor(j)) || s.color
    const specs = series.flatMap((s, i) => {
      const xs: (string | number)[] = isTime ? (s.x ?? days).map(isoOfDay) : names
      const base = { name: s.label, slot: i, dashed: !!s.dash, width: s.bold ? 3.5 : 2, ...(highlight && highlight !== s.label ? { opacity: 0.35 } : {}) }
      if (bars) {
        const colors = s.y.map((_, j) => resolve(colorAt(j, s)))
        return [...new Set(colors)].map((c, n) => {
          const part = mkSeries({ ...base, kind: 'bar', color: c, stack: stack ? 'all' : undefined, name: n ? s.label + ' (' + (n + 1) + ')' : s.label, x: xs, y: s.y.map((v, j) => (colors[j] === c ? v * k : null)) })
          part.legend = n === 0
          return part
        })
      }
      let x = xs, y: (number | null)[] = s.y.map(v => v * k)
      if (isTime && gapDays && s.x) {
        x = []; y = []
        s.x.forEach((d, j) => {
          if (j && d - s.x![j - 1] > gapDays) { x.push(isoOfDay(Math.round((d + s.x![j - 1]) / 2))); y.push(null) }
          x.push(isoOfDay(d)); y.push(s.y[j] * k)
        })
      }
      return [mkSeries({ ...base, color: resolve(s.color), x, y })]
    })
    const events: ChartEvent[] = isTime && win ? [{ x: isoOfDay(win[0]), label: 'начало выбранного окна', kind: 'other', well: '' }, { x: isoOfDay(win[1]), label: 'конец выбранного окна', kind: 'other', well: '' }] : []
    const xa = isTime
      ? mkAxis('', '', 'time', xRange ? { minimum: xRange[0] * 864e5, maximum: xRange[1] * 864e5 } : {})
      : mkAxis('', '', 'category', { categories: names })
    const c = mkChart('gsp-' + label, '', xa, mkAxis(unit.trim(), '', 'value', bars ? { from_zero: true } : {}), specs)
    if (events.length) c.events = events
    return c
  }, [days, labels, series, mode, win, fmt, unit, label, xRange, stack, highlight, gapDays, barColor])
  return <ChartView chart={chart} excludeMode={false} onExclude={() => {}} />
}
