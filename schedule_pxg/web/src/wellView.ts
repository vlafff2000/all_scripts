// Фильтр скважин вкладки в ГДМ: чистые функции, которые прячут скважины в уже полученных данных вкладки.
// Данные остаются целыми (в состоянии вкладки), фильтр применяется при показе: смена фильтра не требует нового расчёта.
// Решение за инженером: фильтр только прячет скважины на этой вкладке; итоги, которые считает сервер по всей группе, не меняются.
import type { AdaptView, AvgDaily, AvgView, ChartsView, GisObs, QualityView } from './api'

export type Keep = (well: string | number) => boolean

export function viewAveraging(v: AvgView | null, keep: Keep): AvgView | null {
  if (!v) return v
  return {
    ...v, wells: v.wells.filter(w => keep(w.well)), heat: v.heat.filter(h => keep(h.well)), exclusions: v.exclusions.filter(e => keep(e.well)),
    groups: Object.fromEntries(Object.entries(v.groups).map(([g, ws]) => [g, Object.fromEntries(Object.entries(ws).filter(([w]) => keep(w)))])),
  }
}

export const viewDaily = (d: AvgDaily | null, keep: Keep): AvgDaily | null =>
  d && { ...d, groups: Object.fromEntries(Object.entries(d.groups).map(([g, x]) =>
    [g, { ...x, wells: Object.fromEntries(Object.entries(x.wells).filter(([w]) => keep(w))) }])) }

export function viewQuality(v: QualityView | null, keep: Keep): QualityView | null {
  // строки без скважины (по объекту) остаются: фильтр скважин их не трогает
  return v && { ...v, rows: v.rows.filter(r => !r.well || keep(r.well)), excludedRows: v.excludedRows.filter(r => !r.well || keep(r.well)) }
}

export const viewCharts = (v: ChartsView | null, keep: Keep): ChartsView | null =>
  v && { ...v, targets: { ...v.targets, wells: v.targets.wells.filter(keep) } }

export const viewCatalog = (c: { wells: string[]; observations: GisObs[] }, keep: Keep) =>
  ({ wells: c.wells.filter(keep), observations: c.observations.filter(o => keep(o.well)) })

export const viewAdapt = (v: AdaptView | null, keep: Keep): AdaptView | null =>
  v && { ...v, rows: v.rows.filter(r => keep(r.well)), failures: v.failures.filter(f => keep(f.well)) }
