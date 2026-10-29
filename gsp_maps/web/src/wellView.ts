// Фильтр скважин вкладки (pxg_core/web-ui/WellFilter.tsx) в «Картах»: прячет скважины в данных, которые страницы получают из api.ts.
// Решение за инженером: фильтр только прячет скважины на этой вкладке; «все» остаётся в `g.all`, чтобы фильтр можно было менять.
import type { GspData, SeasonData, SummaryData, WorkData } from './api'

export interface WellView { groups: string[]; wells: string[] }
let view: { groups: Set<string>; wells: Set<string> } | null = null
/** Текущий фильтр вкладки; страницы берут данные уже без скрытых скважин. */
export const setWellView = (f: WellView | null) => {
  view = f && (f.groups.length || f.wells.length) ? { groups: new Set(f.groups), wells: new Set(f.wells) } : null
}
/** Остаётся ли скважина группы `group` после фильтра: нужны и выбранная группа, и выбранная скважина (если заданы). */
export const keepWell = (well: number | string, group: string) =>
  !view || ((!view.groups.size || view.groups.has(group)) && (!view.wells.size || view.wells.has(String(well))))

const pick = <T,>(items: Record<string, T>, keep: (w: string) => boolean) => Object.fromEntries(Object.entries(items).filter(([w]) => keep(w)))

/** Одна группа (ГСП) без скрытых скважин; полный список скважин и групп — в `all`. */
export function viewGsp(g: GspData): GspData {
  if (!view) return g
  const keep = (w: string) => keepWell(w, g.gsp)
  return {
    ...g, wells: g.wells.filter(w => keep(String(w))),
    layout: { ...g.layout, wells: pick(g.layout.wells, keep), missing: g.layout.missing.filter(w => keep(String(w))) },
    water: g.water.filter(r => keep(String(r.well))), trends: g.trends.filter(t => keep(String(t.Скважина))),
    depths: pick(g.depths, keep), altitude: pick(g.altitude, keep),
    all: { wells: g.wells, groupOf: Object.fromEntries(g.wells.map(w => [String(w), g.gsp])) },
  }
}

/** Объединение групп: `all` складывается из полных списков каждой группы. */
export const mergeAll = (list: GspData[]): GspData['all'] =>
  view ? { wells: list.flatMap(g => g.all?.wells ?? g.wells), groupOf: Object.assign({}, ...list.map(g => g.all?.groupOf ?? g.groupOf ?? {})) } : undefined

export function viewSeason(d: SeasonData, group: string): SeasonData {
  if (!view) return d
  const at = d.wells.map((_w, i) => i).filter(i => keepWell(d.wells[i], group))
  return { wells: at.map(i => d.wells[i]), days: d.days, flow: at.map(i => d.flow[i]) }
}

export function viewWork(d: WorkData, group: string): WorkData {
  if (!view) return d
  const at = d.wells.map((_w, i) => i).filter(i => keepWell(d.wells[i], group))
  const by = <T,>(rows: T[]) => at.map(i => rows[i])
  return {
    wells: by(d.wells),
    seasons: d.seasons.map(s => ({ ...s, total: by(s.total), days: by(s.days), first: by(s.first), idle: by(s.idle) })),
    months: d.months, monthFlow: by(d.monthFlow), monthDays: by(d.monthDays), monthWater: by(d.monthWater),
  }
}

export function viewSummary(d: SummaryData, group: string): SummaryData {
  const col = d.columns.indexOf('Скважина')
  if (!view || col < 0) return d
  return { ...d, rows: d.rows.filter(r => keepWell(String(r[col]), group)) }
}
