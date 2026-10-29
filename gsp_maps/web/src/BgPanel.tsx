import AlignEditor from './AlignEditor'
import { bgAlign, bgOpacity, bgShow } from './background'
import { usePref } from './prefs'
import type { Placed } from './model'
import { alignTransform, emptyAlign, type AlignPoint } from './polygons'

/** Фото или растр на фон в «Вид карты → Фон»: показ, прозрачность и привязка по трём точкам (пиксели картинки ↔ скважины). */
export default function BgPanel({ placed, align }: { placed: Placed[]; align: AlignPoint[] }) {
  const show = usePref(bgShow), opacity = usePref(bgOpacity)
  const setPoint = (i: number, patch: Partial<AlignPoint>) => bgAlign.set(align.map((p, k) => (k === i ? { ...p, ...patch } : p)))
  return (
    <>
      <label className="check"><input type="checkbox" checked={show} onChange={e => bgShow.set(e.target.checked)} />Фото или растр на фоне</label>
      <label className="row"><span>Прозрачность</span><input type="range" min={0} max={1} step={0.05} value={opacity} onChange={e => bgOpacity.set(Number(e.target.value))} aria-label="Прозрачность фона" /></label>
      <AlignEditor title="Привязка фона по трём точкам" hint="Точки на картинке в пикселях (от левого верхнего угла, Y вниз) и номер скважины, стоящей в той же точке на карте. Без привязки фон не показывается."
        axes={['пикс. X', 'пикс. Y']} align={align} placed={placed} onPatch={setPoint} status={alignTransform(align, placed).status} onReset={() => bgAlign.set(emptyAlign())} />
      <span className="muted small">Файл задаётся в «Данные» (картинка: png, jpg, gif, bmp, webp).</span>
    </>
  )
}
