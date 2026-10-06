import { SIDE_MAX, SIDE_MIN, sideWidth } from './prefs'

/** Ручка на левом краю правой панели: потянуть, чтобы изменить ширину (двойной щелчок — вернуть по умолчанию). */
export default function SideGrip() {
  const clamp = (v: number) => Math.round(Math.max(SIDE_MIN, Math.min(SIDE_MAX, v)))
  return (
    <div className="side-grip" role="separator" aria-orientation="vertical" aria-label="Ширина панели сведений" tabIndex={0} title="Потяните, чтобы изменить ширину панели; двойной щелчок — по умолчанию"
      onDoubleClick={() => sideWidth.set(340)}
      onKeyDown={e => { if (e.key === 'ArrowLeft') sideWidth.set(clamp(sideWidth.get() + 20)); else if (e.key === 'ArrowRight') sideWidth.set(clamp(sideWidth.get() - 20)) }}
      onPointerDown={e => {
        e.preventDefault()
        const x0 = e.clientX, w0 = sideWidth.get(), el = e.currentTarget
        el.setPointerCapture(e.pointerId)
        const move = (ev: PointerEvent) => sideWidth.set(clamp(w0 + x0 - ev.clientX))
        const up = () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up) }
        el.addEventListener('pointermove', move); el.addEventListener('pointerup', up)
      }} />
  )
}
