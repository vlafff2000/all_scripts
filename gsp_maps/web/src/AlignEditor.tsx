import type { Placed } from './model'
import type { AlignPoint } from './polygons'

/** Три точки привязки: две координаты (из файла или пиксели картинки) и номер скважины, стоящей в той же точке на карте. */
export default function AlignEditor({ title, hint, axes, align, placed, onPatch, status, onReset }: {
  title: string; hint: string; axes: [string, string]; align: AlignPoint[]; placed: Placed[]
  onPatch: (i: number, patch: Partial<AlignPoint>) => void; status: string; onReset: () => void
}) {
  const num = (v: string) => (v === '' ? null : Number(v))
  return (
    <div className="poly-align">
      <b>{title}</b>
      <span className="muted small">{hint}</span>
      {align.map((pt, i) => <label key={i} className="row"><span>Точка {i + 1}</span>
        <input type="number" step="any" placeholder={axes[0]} value={pt.x ?? ''} aria-label={`Точка ${i + 1}, ${axes[0]}`} onChange={e => onPatch(i, { x: num(e.target.value) })} />
        <input type="number" step="any" placeholder={axes[1]} value={pt.y ?? ''} aria-label={`Точка ${i + 1}, ${axes[1]}`} onChange={e => onPatch(i, { y: num(e.target.value) })} />
        <select value={pt.well ?? ''} aria-label={`Точка ${i + 1}, скважина`} onChange={e => onPatch(i, { well: num(e.target.value) })}>
          <option value="">скважина…</option>{placed.map(q => <option key={q.well} value={q.well}>{q.well}</option>)}</select></label>)}
      <span className="muted small">{status}</span>
      <button type="button" className="quiet" onClick={onReset}>Сбросить привязку</button>
    </div>
  )
}
