import type { Series } from '../../../pxg_core/web-ui/chart/chartTypes'

/** Маркеры на показанной кривой при дебитах режимов. Пропуски и пределы модели сохраняются. */
export function indicatorMarkers(line: Series, rates: (number | null)[]): Series {
  const x: number[] = []
  const y: number[] = []
  for (const rate of new Set(rates)) {
    if (rate === null || !Number.isFinite(rate) || rate <= 0) continue
    const i = line.x.findIndex(v => typeof v === 'number' && v >= rate)
    if (i < 0) continue
    const right = line.x[i]
    const upper = line.y[i]
    if (typeof right !== 'number' || typeof upper !== 'number' || !Number.isFinite(upper)) continue
    if (right === rate) {
      x.push(rate)
      y.push(upper)
      continue
    }
    const left = line.x[i - 1]
    const lower = line.y[i - 1]
    if (typeof left !== 'number' || typeof lower !== 'number' || !Number.isFinite(lower) || left >= rate) continue
    x.push(rate)
    y.push(lower + (upper - lower) * (rate - left) / (right - left))
  }
  return { ...line, kind: 'points', x, y, total: x.length, legend: false, markers: false }
}
