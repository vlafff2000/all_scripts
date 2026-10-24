/** ГВК модели по всем скважинам модели («Карты», режим «все скважины модели», по умолчанию выключен).
 *  Числа приходят с сервера (/api/gis/model-wells); здесь — выбор способа и глубины, подсказки и невязка к ГИС.
 *  Подсказки не исключают скважину: исключает инженер вручную (клик по скважине). Только вычисления, без React. */
import type { IsoPoint } from './model'

/** Скважина с газом в колонне: td/lo — по границе ячейки (сверху вниз / самый нижний газ), tdi/loi — по интерполяции Sg. */
export interface ModelWell { w: string; n: number | null; x: number; y: number; td: number; tdi: number; lo: number; loi: number; torn: boolean; edge: boolean; cols: number }
export interface GisModelWells { dates: string[]; date: string; points: ModelWell[]; no_gas: string[]; sgr_source: string; thr: number; model: string; note: string }

/** Способ контакта: сверху вниз (от кровли газа) или самый нижний газ; глубина: по границе ячейки или по интерполяции Sg. */
export type AwMode = 'td' | 'lo'
export type AwDepth = 'cell' | 'interp'

export const AW_MODES: [AwMode, string][] = [['td', 'ГВК: сверху вниз'], ['lo', 'ГВК: самый нижний газ']]
export const AW_DEPTHS: [AwDepth, string][] = [['cell', 'глубина по границе ячейки'], ['interp', 'глубина по интерполяции Sg']]

export function awValue(p: ModelWell, mode: AwMode, depth: AwDepth): number {
  return mode === 'td' ? (depth === 'cell' ? p.td : p.tdi) : (depth === 'cell' ? p.lo : p.loi)
}

/** Список исключённых скважин из настройки («12,GSP-3»): пробелы убираются, пустые элементы пропускаются. */
export function parseExcl(raw: string): Set<string> {
  return new Set(raw.split(',').map(s => s.trim()).filter(Boolean))
}

export function median(vs: number[]): number | null {
  if (!vs.length) return null
  const s = [...vs].sort((a, b) => a - b), n = s.length
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2
}

export interface AwPoint extends IsoPoint { w: string; n: number | null; torn: boolean }

/** Отклонение значения от медианы соседей в радиусе `rad` (в координатах карты), м. Меньше трёх соседей — отклонения нет. */
export function awDeviation(pts: AwPoint[], rad: number): Map<string, number> {
  const out = new Map<string, number>()
  for (const p of pts) {
    const near = pts.filter(q => q !== p && Math.hypot(q.x - p.x, q.y - p.y) <= rad).map(q => q.v)
    if (near.length >= 3) out.set(p.w, p.v - (median(near) as number))
  }
  return out
}

/** Невязка «ГВК модели − факт ГИС» по скважинам, которые есть и там и там: число пар, медиана и средний модуль, м. */
export function awResidual(pts: AwPoint[], fact: Record<string, number> | null): { n: number; median: number | null; mae: number | null } {
  const d = fact ? pts.filter(p => p.n !== null && fact[String(p.n)] !== undefined).map(p => p.v - fact[String(p.n)]) : []
  return { n: d.length, median: median(d), mae: d.length ? d.reduce((a, b) => a + Math.abs(b), 0) / d.length : null }
}
