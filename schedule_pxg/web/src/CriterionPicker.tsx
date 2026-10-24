import { useEffect, useState } from 'react'
import { type CriterionCfg, type CriterionPreset, getCriterionPresets } from './api'

const LOGICS = [
  { id: 'sg', title: 'Sg > порога' },
  { id: 'sg_sgcr', title: 'Sg > SGCR + запас' },
  { id: 'sw_swcr', title: 'Sw < SWCR − запас' },
]
const CUSTOM = 'custom'

/** Критерий газа для ГВК по модели: пресет из списка или свои числа. Подсказка — формула текстом; значение правится руками. */
export default function CriterionPicker({ value, onChange }: { value: CriterionCfg; onChange: (c: CriterionCfg) => void }) {
  const [presets, setPresets] = useState<CriterionPreset[]>([])
  const [text, setText] = useState({ value: String(value.value), fallback: String(value.fallback) })

  useEffect(() => {
    getCriterionPresets().then(r => setPresets(r.presets)).catch(() => undefined)
  }, [])
  useEffect(() => { setText({ value: String(value.value), fallback: String(value.fallback) }) }, [value.value, value.fallback])

  const num = (s: string) => Number(s.replace(',', '.'))
  const match = presets.find(p => p.logic === value.logic && p.value === value.value && p.fallback === value.fallback)
  const current = match ? match.id : CUSTOM
  const apply = (patch: Partial<CriterionCfg>) => onChange({ ...value, ...patch })

  return (
    <span className="row" style={{ flexWrap: 'wrap', gap: 6 }} title={match ? match.formula : ''}>
      <span className="muted small">Критерий газа:</span>
      <select value={current} onChange={e => {
        const p = presets.find(x => x.id === e.target.value)
        if (p) onChange({ logic: p.logic, value: p.value, fallback: p.fallback })
      }}>
        {presets.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}
        {current === CUSTOM && <option value={CUSTOM}>Свой критерий</option>}
      </select>
      <select value={value.logic} onChange={e => apply({ logic: e.target.value })} aria-label="Логика критерия">
        {LOGICS.map(l => <option key={l.id} value={l.id}>{l.title}</option>)}
      </select>
      <span className="muted small">порог / запас:</span>
      <input style={{ width: 60 }} value={text.value} onChange={e => setText({ ...text, value: e.target.value })}
        onBlur={() => Number.isFinite(num(text.value)) && apply({ value: num(text.value) })} />
      <span className="muted small">SGCR, если нет в INIT:</span>
      <input style={{ width: 60 }} value={text.fallback} onChange={e => setText({ ...text, fallback: e.target.value })}
        onBlur={() => Number.isFinite(num(text.fallback)) && apply({ fallback: num(text.fallback) })} />
      {match && <span className="muted small">{match.formula}</span>}
    </span>
  )
}
