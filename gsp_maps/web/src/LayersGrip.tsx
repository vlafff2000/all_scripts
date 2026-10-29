import type { PointerEvent as ReactPointerEvent } from 'react'
import { layersBox } from './prefs'

/** Ручки окна «Вид карты»: левый край и низ растягивают окно, угол — сразу по двум направлениям. Размер запоминается; двойной щелчок — по умолчанию. */
export default function LayersGrip() {
  const start = (sx: number, sy: number) => (e: ReactPointerEvent<HTMLSpanElement>) => {
    e.preventDefault()
    const win = e.currentTarget.parentElement as HTMLElement
    const w0 = win.offsetWidth, h0 = win.offsetHeight, x0 = e.clientX, y0 = e.clientY
    const move = (ev: PointerEvent) => {
      const w = Math.round(Math.max(300, Math.min(window.innerWidth - 100, w0 + sx * (ev.clientX - x0))))
      const h = Math.round(Math.max(240, Math.min(window.innerHeight - 150, h0 + sy * (ev.clientY - y0))))
      layersBox.set({ w, h })
    }
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
  }
  const reset = () => layersBox.set(null)
  return (
    <>
      <span className="layers-grip lg-w" title="Потяните, чтобы изменить ширину; двойной щелчок — по умолчанию" onPointerDown={start(-1, 0)} onDoubleClick={reset} />
      <span className="layers-grip lg-s" title="Потяните, чтобы изменить высоту; двойной щелчок — по умолчанию" onPointerDown={start(0, 1)} onDoubleClick={reset} />
      <span className="layers-grip lg-sw" title="Потяните, чтобы изменить размер; двойной щелчок — по умолчанию" onPointerDown={start(-1, 1)} onDoubleClick={reset} />
    </>
  )
}
