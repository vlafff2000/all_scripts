// Фильтр скважин панели «Работы с исходными данными»: свой у каждой панели и модуля, пресеты общие (pxg_core/well_presets.py).
// Скважины — те, что есть в самих данных панели (замечания проверки, листы легенды); фильтр только прячет строки, решение за инженером.
import { useMemo } from 'react'
import { WellFilter, useWellFilter, wellKeeper } from '../../../pxg_core/web-ui/WellFilter'

const natural = (a: string, b: string) => a.length - b.length || (a < b ? -1 : 1)
const nobody = () => undefined

export function usePanelFilter(tab: string, wellsOf: (string | undefined)[]) {
  const [filter, setFilter] = useWellFilter(tab)
  const wells = useMemo(() => [...new Set(wellsOf.filter((w): w is string => !!w))].sort(natural), [wellsOf])
  const keep = useMemo(() => wellKeeper(filter, nobody), [filter])
  const node = wells.length ? <WellFilter tab={tab} wells={wells} groups={[]} groupOf={nobody} value={filter} onChange={setFilter} /> : null
  return { node, keep, active: filter !== null }
}
