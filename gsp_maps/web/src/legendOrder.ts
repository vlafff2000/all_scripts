/** Порядок подписей в легенде по возрастанию: тот же естественный порядок, что pxg_core/legend_order.py и Газовый Атлас.
 *  «№ 9» раньше «№ 10», «ГСП-1» = «ГСП 1», даты «01.12.2023» по дате, а не по дню. */
const DATE = /(\d{1,2})\.(\d{1,2})\.(\d{4})/g
const SEP = /[\s_-]+/g

export function labelKey(text: string): (string | number)[] {
  const t = String(text).trim().toLowerCase()
    .replace(DATE, (_, d: string, m: string, y: string) => `${y}${m.padStart(2, '0')}${d.padStart(2, '0')}`)
    .replace(SEP, ' ')
  return t.split(/(\d+)/).map((part, i) => (i % 2 ? Number(part) : part))
}

export function compareLabels(a: string, b: string): number {
  const x = labelKey(a), y = labelKey(b)
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    if (x[i] === y[i]) continue
    if (typeof x[i] === 'number' && typeof y[i] === 'number') return (x[i] as number) - (y[i] as number)
    return String(x[i]) < String(y[i]) ? -1 : 1
  }
  return x.length - y.length
}

/** Копия списка по возрастанию подписи; сам список не меняется. */
export const sortLabels = <T,>(items: T[], label: (item: T) => string): T[] =>
  [...items].sort((p, q) => compareLabels(label(p), label(q)))
