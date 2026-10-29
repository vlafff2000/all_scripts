// Фильтр скважин вкладки ГДМ: свой у каждой вкладки (useWellFilter хранит по ключу вкладки), пресеты общие (pxg_core/well_presets.py).
// Скважины и их группы — из проекта ГДМ (/api/wells); у вкладки со своим списком скважин (планшет ГИС) он добавляется через `extra`.
import { useEffect, useMemo, useState } from 'react'
import { WellFilter, useWellFilter, wellKeeper } from '../../../pxg_core/web-ui/WellFilter'

interface WellsInfo { wells: string[]; groupOf: Record<string, string> }
let cached: Promise<WellsInfo> | null = null
const loadWells = () => (cached ??= fetch('/api/wells').then(r => r.json() as Promise<WellsInfo>).catch(() => { cached = null; return { wells: [], groupOf: {} } }))

/** Фильтр вкладки: `node` — поле для страницы, `keep` — остаётся ли скважина, `active` — фильтр включён. */
const NONE: string[] = []
export function useTabFilter(tab: string, extra: string[] = NONE) {
  const [filter, setFilter] = useWellFilter(tab)
  const [info, setInfo] = useState<WellsInfo>({ wells: [], groupOf: {} })
  useEffect(() => { loadWells().then(setInfo) }, [])
  const groupOf = (w: string) => info.groupOf[w]
  const keep = useMemo(() => wellKeeper(filter, w => info.groupOf[w]), [filter, info])
  const wells = useMemo(() => [...new Set([...info.wells, ...extra])].sort((a, b) => a.length - b.length || (a < b ? -1 : 1)), [info, extra])
  const groups = useMemo(() => [...new Set(Object.values(info.groupOf))].sort(), [info])
  const node = <div className="row"><WellFilter tab={tab} wells={wells} groups={groups} groupOf={groupOf} value={filter} onChange={setFilter} /></div>
  return { node, keep, active: filter !== null }
}
