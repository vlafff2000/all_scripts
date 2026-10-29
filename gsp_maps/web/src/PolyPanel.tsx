import { MARKERS, POLY_COLORS, resetStyle, setStyle, styleOf, type PolyStyle } from './polygons'
import { useState } from 'react'
import type { Poly } from './api'

/** Настройка многоугольников в «Вид карты»: выбор контура и его цвета, толщины, заливки и маркеров по вершинам. */
export default function PolyPanel({ polys, overrides, warnings }: { polys: Poly[]; overrides: Record<string, Partial<PolyStyle>>; warnings: string[] }) {
  const [name, setName] = useState(polys[0]?.name ?? '')
  const idx = Math.max(0, polys.findIndex(p => p.name === name))
  const st = styleOf(name, idx, overrides)
  return (
    <>
      <label className="row"><span>Контур</span>
        <select value={name} onChange={e => setName(e.target.value)} aria-label="Многоугольник">
          {polys.map(p => <option key={p.name} value={p.name}>{p.name} · {p.pts.length} вершин</option>)}</select></label>
      <label className="check"><input type="checkbox" checked={st.show} onChange={e => setStyle(name, { show: e.target.checked })} />Показывать</label>
      <label className="row"><span>Линия</span><input type="color" value={st.stroke} onChange={e => setStyle(name, { stroke: e.target.value })} aria-label="Цвет линии" /></label>
      <label className="row"><span>Толщина</span><input type="range" min={0.5} max={6} step={0.5} value={st.width} onChange={e => setStyle(name, { width: Number(e.target.value) })} aria-label="Толщина линии" /></label>
      <label className="check"><input type="checkbox" checked={st.dash} onChange={e => setStyle(name, { dash: e.target.checked })} />Пунктир</label>
      <label className="row"><span>Заливка</span><input type="color" value={st.fill} onChange={e => setStyle(name, { fill: e.target.value })} aria-label="Цвет заливки" /></label>
      <label className="row"><span>Прозрачность</span><input type="range" min={0} max={1} step={0.05} value={st.fillOpacity} onChange={e => setStyle(name, { fillOpacity: Number(e.target.value) })} aria-label="Прозрачность заливки" /></label>
      <label className="row"><span>Маркер</span><select value={st.marker} onChange={e => setStyle(name, { marker: e.target.value as PolyStyle['marker'] })} aria-label="Маркер вершин">
        {MARKERS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
      <label className="row"><span>Размер маркера</span><input type="range" min={1} max={12} step={1} value={st.markerSize} onChange={e => setStyle(name, { markerSize: Number(e.target.value) })} aria-label="Размер маркера" /></label>
      <label className="row"><span>Цвет маркера</span><input type="color" value={st.markerColor} onChange={e => setStyle(name, { markerColor: e.target.value })} aria-label="Цвет маркера" /></label>
      <button type="button" className="quiet" onClick={() => resetStyle(name)}>Вернуть стиль по умолчанию</button>
      <span className="muted small">Цвета по умолчанию идут по порядку: {POLY_COLORS.slice(0, 4).join(', ')}…</span>
      {warnings.map((w, i) => <span key={i} className="muted small">{w}</span>)}
    </>
  )
}
