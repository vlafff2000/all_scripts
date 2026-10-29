import { useRef, useState } from 'react'
import { BUILTIN_PALETTES, cssGradient, defOf, isHex, paletteAt, palettePresets, type PaletteDef, type PStop } from './palette'
import { usePref } from './prefs'

const clamp01 = (t: number) => Math.max(0, Math.min(1, t))
const same = (a: PaletteDef, b: PaletteDef) => JSON.stringify(a) === JSON.stringify(b)

interface Props {
  /** Действующая палитра. */
  def: PaletteDef
  /** Палитра режима по умолчанию (для «Сбросить»). */
  base: PaletteDef
  /** Диапазон по данным: подсказка в полях «Мин» и «Макс». */
  auto: [number, number]
  onChange: (d: PaletteDef) => void
  onReset: () => void
}

/** Редактор палитры как в дизайнере геологии tNavigator: полоса градиента со стопами (тянуть, щёлкнуть по полосе — добавить стоп),
 *  цвет и положение выбранного стопа, число ступеней, обратить, диапазон, пресеты. */
export default function PaletteEditor({ def, base, auto, onChange, onReset }: Props) {
  const bar = useRef<HTMLDivElement>(null)
  const useRefStops = useRef<PStop[]>(def.stops), defRef = useRef(def), onChangeRef = useRef(onChange)
  const [sel, setSel] = useState(0)
  const mine = usePref(palettePresets)
  const cur = Math.min(sel, def.stops.length - 1)
  const set = (p: Partial<PaletteDef>) => onChange({ ...def, ...p })
  const setStops = (stops: PStop[]) => set({ stops })
  const sorted = (s: PStop[]) => [...s].sort((p, q) => p.t - q.t)

  const move = (i: number, t: number) => {
    const next = def.stops.map((s, k) => (k === i ? { ...s, t: clamp01(t) } : s))
    const c = def.stops[i].c
    const re = sorted(next)
    setStops(re)
    setSel(re.findIndex(s => s.c === c && s.t === clamp01(t)))
  }
  const posOf = (e: { clientX: number }) => {
    const r = bar.current!.getBoundingClientRect()
    return clamp01((e.clientX - r.left) / r.width)
  }
  const drag = (i: number) => (e: React.PointerEvent) => {
    e.preventDefault(); e.stopPropagation()
    let idx = i
    setSel(i)
    const el = e.currentTarget as HTMLElement
    el.setPointerCapture(e.pointerId)
    const onMove = (ev: PointerEvent) => {
      const t = posOf(ev)
      let list = useRefStops.current.map((s, k) => (k === idx ? { ...s, t } : s))
      const key = list[idx]
      list = sorted(list)
      idx = list.indexOf(key)
      useRefStops.current = list
      onChangeRef.current({ ...defRef.current, stops: list })
      setSel(idx)
    }
    const end = () => { el.removeEventListener('pointermove', onMove); el.removeEventListener('pointerup', end); el.removeEventListener('pointercancel', end) }
    useRefStops.current = def.stops
    defRef.current = def; onChangeRef.current = onChange
    el.addEventListener('pointermove', onMove); el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end)
  }

  const addAt = (e: React.MouseEvent) => {
    const t = posOf(e)
    const c = paletteAt({ ...def, reverse: false, steps: 0 }, t)
    const next = sorted([...def.stops, { t, c }])
    setStops(next); setSel(next.findIndex(s => s.t === t && s.c === c))
  }
  const remove = (i: number) => {
    if (def.stops.length <= 2) return
    setStops(def.stops.filter((_, k) => k !== i)); setSel(Math.max(0, i - 1))
  }
  const key = (i: number) => (e: React.KeyboardEvent) => {
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); remove(i) }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); move(i, def.stops[i].t + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 0.1 : 0.01)) }
  }
  const setColor = (c: string) => { if (isHex(c)) setStops(def.stops.map((s, k) => (k === cur ? { ...s, c: c.toLowerCase() } : s))) }

  const num = (s: string) => (s.trim() === '' || !Number.isFinite(Number(s.replace(',', '.'))) ? null : Number(s.replace(',', '.')))
  const st = def.stops[cur]
  const savePreset = () => {
    const name = window.prompt('Название пресета палитры')?.trim()
    if (!name) return
    palettePresets.set([...mine.filter(p => p.name !== name), { name, def: { ...def, lo: null, hi: null } }])
  }
  const pick = (v: string) => {
    if (v.startsWith('b:')) { const b = BUILTIN_PALETTES[Number(v.slice(2))]; if (b) onChange({ ...defOf(b[1]), steps: def.steps, reverse: def.reverse, lo: def.lo, hi: def.hi }) }
    else if (v.startsWith('m:')) { const m = mine[Number(v.slice(2))]; if (m) onChange({ ...m.def, lo: def.lo, hi: def.hi }) }
    else if (v === 'base') onChange({ ...base, lo: def.lo, hi: def.hi })
    setSel(0)
  }

  return (
    <div className="pal-ed">
      <div className="pal-bar-wrap">
        <div className="pal-bar" ref={bar} style={{ background: cssGradient(def) }} onClick={addAt} title="Щёлкните по полосе, чтобы добавить опорный цвет" role="presentation" />
        <div className="pal-marks">
          {def.stops.map((s, i) => (
            <button key={i} type="button" className={'pal-mark' + (i === cur ? ' on' : '')} style={{ left: `${(def.reverse ? 1 - s.t : s.t) * 100}%`, background: s.c }}
              onPointerDown={def.reverse ? undefined : drag(i)} onClick={e => { e.stopPropagation(); setSel(i) }} onKeyDown={key(i)}
              aria-label={`Опорный цвет ${i + 1}: ${s.c}, ${Math.round(s.t * 100)}%`} title="Тяните вдоль шкалы; Delete — убрать" />
          ))}
        </div>
      </div>
      {def.reverse && <p className="muted small">Палитра обращена: чтобы двигать опорные цвета, снимите «Обратить».</p>}
      <div className="pal-stop">
        <input type="color" value={st.c} onChange={e => setColor(e.target.value)} aria-label="Цвет выбранного опорного цвета" />
        <input type="text" className="pal-hex" value={st.c} spellCheck={false} onChange={e => { if (isHex(e.target.value)) setColor(e.target.value) }} aria-label="Код цвета" />
        <label className="pal-pos">положение
          <input type="number" min={0} max={100} step={1} value={Math.round(st.t * 100)} onChange={e => move(cur, Number(e.target.value) / 100)} aria-label="Положение на шкале, %" />%</label>
        <button type="button" onClick={() => remove(cur)} disabled={def.stops.length <= 2} title="Убрать выбранный опорный цвет" aria-label="Убрать опорный цвет">×</button>
      </div>
      <div className="pal-row">
        <div className="segmented" role="radiogroup" aria-label="Переход цвета">
          <button type="button" role="radio" aria-checked={def.steps < 2} onClick={() => set({ steps: 0 })}>Плавно</button>
          <button type="button" role="radio" aria-checked={def.steps >= 2} onClick={() => set({ steps: def.steps >= 2 ? def.steps : 8 })}>Ступени</button>
        </div>
        {def.steps >= 2 && <label className="pal-pos">интервалов
          <input type="number" min={2} max={32} step={1} value={def.steps} onChange={e => set({ steps: Math.max(2, Math.min(32, Math.round(Number(e.target.value) || 2))) })} aria-label="Число интервалов" /></label>}
      </div>
      <div className="pal-row">
        <label className="pal-pos">мин
          <input type="text" inputMode="decimal" className="pal-rng" value={def.lo === null ? '' : String(def.lo)} placeholder={String(+auto[0].toPrecision(4))}
            onChange={e => set({ lo: num(e.target.value) })} aria-label="Нижняя граница шкалы" /></label>
        <label className="pal-pos">макс
          <input type="text" inputMode="decimal" className="pal-rng" value={def.hi === null ? '' : String(def.hi)} placeholder={String(+auto[1].toPrecision(4))}
            onChange={e => set({ hi: num(e.target.value) })} aria-label="Верхняя граница шкалы" /></label>
        <button type="button" disabled={def.lo === null && def.hi === null} onClick={() => set({ lo: null, hi: null })} title="Границы шкалы снова по данным">По данным</button>
      </div>
      <label className="check"><input type="checkbox" checked={def.reverse} onChange={e => set({ reverse: e.target.checked })} />Обратить</label>
      <div className="pal-row">
        <select value="" onChange={e => pick(e.target.value)} aria-label="Готовые палитры">
          <option value="">Готовая палитра…</option>
          <option value="base">Палитра по умолчанию</option>
          <optgroup label="Встроенные">{BUILTIN_PALETTES.map(([n], i) => <option key={n} value={'b:' + i}>{n}</option>)}</optgroup>
          {mine.length > 0 && <optgroup label="Мои">{mine.map((m, i) => <option key={m.name} value={'m:' + i}>{m.name}</option>)}</optgroup>}
        </select>
      </div>
      <div className="pal-row">
        <button type="button" onClick={savePreset} title="Сохранить текущие цвета как пресет, доступный во всех режимах">Сохранить как пресет…</button>
        {mine.length > 0 && <select value="" onChange={e => { if (e.target.value) palettePresets.set(mine.filter(p => p.name !== e.target.value)) }} aria-label="Удалить свой пресет">
          <option value="">Удалить пресет…</option>{mine.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}</select>}
        <button type="button" disabled={same(def, base)} onClick={onReset} title="Вернуть палитру режима по умолчанию">Сбросить</button>
      </div>
    </div>
  )
}
