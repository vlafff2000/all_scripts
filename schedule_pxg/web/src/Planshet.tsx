import { useEffect, useMemo, useRef, useState } from 'react'
import { MultiSelect } from '../../../pxg_core/web-ui/MultiSelect'
import '../../../pxg_core/web-ui/multiselect.css'
import PageHead from './PageHead'
import GwcCompare from './GwcCompare'
import CriterionPicker from './CriterionPicker'
import { CriterionCfg, CriterionPreset, FactWell, GisObs, ModelEntry, WellProfile, getCriterionPresets, getModelPerfs, ModelPerfRow, getModels, getPlanshetCatalog, getPlanshetFacts, getSources, getWellProfile, pickFile, pickFolder, setSources } from './api'

const fmt = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const tail = (path: string) => path.split(/[\\/]/).filter(Boolean).slice(-2).join('/')

interface Track { title: string; sub: string; gwc: { label: string; z: number | null }[]; bars: { top: number; bottom: number; v: number }[]; note?: string; color?: string; perf?: { top: number; bottom: number }[] }

const W = 150, PAD = 8, AXIS = 56, HEAD = 46

/** Цвет линии ГВК модели — по порядку модели в «Результатах расчёта»; факт остаётся цветом воды. */
const SERIES = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e', '#17becf', '#8c564b', '#e377c2']
const seriesColor = (i: number) => SERIES[(i < 0 ? 0 : i) % SERIES.length]
const wrapText = (s: string, n: number) => {
  const out: string[] = []
  let cur = ''
  s.split(' ').forEach(w => { if (cur && (cur + ' ' + w).length > n) { out.push(cur); cur = w } else cur = cur ? cur + ' ' + w : w })
  if (cur) out.push(cur)
  return out
}

type Mode = 'tvdss' | 'md'
interface Hover { z: number; cx: number; cy: number; x: number }

/** Одна скважина: ось глубины (а.о. или MD) и треки с общей шкалой 0…1; перфорация — полоса слева.
 *  Колесо — масштаб около курсора, перетаскивание — сдвиг, двойной щелчок — сброс; шкала общая у всех скважин, подсказка по наведению. */
function WellLog({ name, tracks, perf, zMin, zMax, h, mode, alt, hz, onHover, onView, onReset }: {
  name: string; tracks: Track[]; perf: FactWell['perforation']; zMin: number; zMax: number; h: number
  mode: Mode; alt: number | null; hz: number | null; onHover: (z: number | null) => void; onView: (lo: number, hi: number) => void; onReset: () => void
}) {
  const md = mode === 'md' && alt !== null
  const toD = (z: number) => (md ? (alt as number) - z : z)            // отметка а.о. → значение на оси
  const toZ = (d: number) => (md ? (alt as number) - d : d)
  const y = (z: number) => HEAD + ((zMax - z) / (zMax - zMin)) * h
  const dLo = Math.min(toD(zMin), toD(zMax)), dHi = Math.max(toD(zMin), toD(zMax))
  const step = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500].find(s => (dHi - dLo) / s <= 14) || 500
  const ticks: number[] = []
  for (let d = Math.ceil(dLo / step) * step; d <= dHi; d += step) ticks.push(Math.round(d / step) * step)
  const width = AXIS + 16 + tracks.length * (W + PAD)
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<{ y0: number; lo: number; hi: number } | null>(null)
  const [tip, setTip] = useState<Hover | null>(null)
  const clip = 'clip-' + name.replace(/[^a-zA-Z0-9_-]/g, '_')
  const live = useRef({ zMin, zMax, h, onView })
  live.current = { zMin, zMax, h, onView }
  const zAt = (clientY: number) => {
    const r = svg.current!.getBoundingClientRect()
    return zMax - ((clientY - r.top - HEAD) / h) * (zMax - zMin)
  }
  useEffect(() => {
    const el = svg.current
    if (!el) return
    const wheel = (e: WheelEvent) => {
      e.preventDefault()
      const { zMin: lo, zMax: hi, h: hh, onView: set } = live.current
      const r = el.getBoundingClientRect()
      const zc = hi - ((e.clientY - r.top - HEAD) / hh) * (hi - lo)
      const f = e.deltaY > 0 ? 1.25 : 0.8
      set(zc - (zc - lo) * f, zc + (hi - zc) * f)
    }
    el.addEventListener('wheel', wheel, { passive: false })
    return () => el.removeEventListener('wheel', wheel)
  }, [])
  const down = (e: React.PointerEvent) => { drag.current = { y0: e.clientY, lo: zMin, hi: zMax }; (e.target as Element).setPointerCapture?.(e.pointerId); setTip(null) }
  const move = (e: React.PointerEvent) => {
    const r = svg.current!.getBoundingClientRect()
    if (drag.current) {
      const dz = ((e.clientY - drag.current.y0) / h) * (drag.current.hi - drag.current.lo)
      onView(drag.current.lo + dz, drag.current.hi + dz)
      return
    }
    const inside = e.clientY - r.top >= HEAD && e.clientY - r.top <= HEAD + h
    if (!inside) { setTip(null); onHover(null); return }
    const z = zAt(e.clientY)
    setTip({ z, cx: e.clientX, cy: e.clientY, x: e.clientX - r.left })
    onHover(z)
  }
  const leave = () => { setTip(null); onHover(null) }
  const near = 4 / h * (zMax - zMin)
  const lines = (z: number): string[] => {
    const out: string[] = []
    if (perf && perf.top !== null && perf.bottom !== null && z <= Math.max(perf.top, perf.bottom) && z >= Math.min(perf.top, perf.bottom))
      out.push('Перфорация: ' + fmt(perf.top) + ' … ' + fmt(perf.bottom) + ' м а.о.')
    tracks.forEach(t => {
      const pf = (t.perf || []).filter(q => z <= Math.max(q.top, q.bottom) && z >= Math.min(q.top, q.bottom))
      if (pf.length) out.push(t.title + ': перфорация ' + pf.map(q => fmt(q.top) + ' … ' + fmt(q.bottom)).join('; ') + ' м а.о.')
      const bar = t.bars.find(b => z <= Math.max(b.top, b.bottom) && z >= Math.min(b.top, b.bottom))
      const g = t.gwc.filter(q => q.z !== null && Math.abs((q.z as number) - z) <= near)
      const parts = [bar ? `${t.sub.startsWith('Sg') ? 'Sg' : 'Кг'} ${fmt(bar.v, 2)} (${fmt(bar.top)} … ${fmt(bar.bottom)})` : '', ...g.map(q => `${q.label} ${fmt(q.z)}`)].filter(Boolean)
      if (parts.length) out.push(t.title + ' · ' + t.sub + ': ' + parts.join('; '))
    })
    return out
  }
  const hline = hz !== null && hz >= zMin && hz <= zMax ? y(hz) : null
  return (
    <>
    <svg ref={svg} width={width} height={HEAD + h + 8} role="img" aria-label={'Планшет скважины ' + name}
      style={{ background: 'var(--chart-surface)', border: '1px solid var(--line)', borderRadius: 6, cursor: drag.current ? 'grabbing' : 'crosshair', touchAction: 'none' }}
      onPointerDown={down} onPointerMove={move} onPointerUp={() => { drag.current = null }} onPointerLeave={leave} onDoubleClick={onReset}>
      <defs><clipPath id={clip}><rect x={AXIS} y={HEAD} width={width - AXIS} height={h} /></clipPath></defs>
      <text x={6} y={14} fill="var(--chart-ink)" fontWeight={700} fontSize={13}>Скв. {name}</text>
      {ticks.map(d => { const z = toZ(d); return <g key={d}><line x1={AXIS} x2={width} y1={y(z)} y2={y(z)} stroke="var(--chart-grid)" />
        <text x={AXIS - 6} y={y(z) + 4} textAnchor="end" fontSize={11} fill="var(--chart-muted)">{d.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}</text></g> })}
      <text x={6} y={HEAD - 6} fontSize={10} fill="var(--chart-muted)">{md ? 'м, MD' : 'м, а.о.'}</text>
      <g clipPath={`url(#${clip})`}>
      {perf && perf.top !== null && perf.bottom !== null && <g>
        {(perf.intervals && perf.intervals.length ? perf.intervals : [perf]).map((iv, n) =>
          <rect key={n} x={AXIS + 2} width={9} y={y(Math.max(iv.top ?? 0, iv.bottom ?? 0))} height={Math.max(2, Math.abs(y(iv.top ?? 0) - y(iv.bottom ?? 0)))} fill="var(--chart-accent)" opacity={0.85} />)}</g>}
      {tracks.map((t, i) => {
        const x0 = AXIS + 16 + i * (W + PAD)
        return <g key={i}>
          <rect x={x0} y={HEAD} width={W} height={h} fill="none" stroke="var(--chart-axis)" />
          {t.bars.map((b, k) => <rect key={k} x={x0} width={Math.max(0, Math.min(1, b.v)) * W} y={y(b.top)} height={Math.max(1, y(b.bottom) - y(b.top))} fill="var(--map-gas)" opacity={0.8} stroke="var(--chart-surface)" strokeWidth={0.5} />)}
          {t.gwc.map((g, k) => g.z === null ? null : <g key={k}>
            <line x1={x0} x2={x0 + W} y1={y(g.z)} y2={y(g.z)} stroke={t.color || 'var(--map-water)'} strokeWidth={2.5} strokeDasharray={k ? '5 3' : undefined} />
            <text x={x0 + W - 3} y={y(g.z) - 3} textAnchor="end" fontSize={10} fill="var(--chart-ink)">{g.label + ' ' + fmt(md ? toD(g.z) : g.z)}</text></g>)}
          {t.perf && t.perf.map((q, k) => <rect key={'p' + k} x={x0 + W - 7} width={6} y={y(Math.max(q.top, q.bottom))} height={Math.max(2, Math.abs(y(q.top) - y(q.bottom)))} fill={t.color || 'var(--chart-accent)'} opacity={0.9} stroke="var(--chart-surface)" strokeWidth={0.5} />)}
          {t.note && <text x={x0 + 4} y={HEAD + 14} fontSize={10} fill="var(--chart-muted)">{t.note}</text>}
        </g>
      })}
      {hline !== null && <line x1={AXIS} x2={width} y1={hline} y2={hline} stroke="var(--chart-ink)" strokeDasharray="3 3" opacity={0.6} />}
      </g>
      {tracks.map((t, i) => { const x0 = AXIS + 16 + i * (W + PAD)
        return <g key={'h' + i}><text x={x0} y={HEAD - 20} fontSize={11} fontWeight={700} fill="var(--chart-ink)">{t.title}</text>
          <text x={x0} y={HEAD - 8} fontSize={10} fill="var(--chart-muted)">{t.sub}</text></g> })}
    </svg>
    {tip && <div role="tooltip" style={{ position: 'fixed', left: tip.cx + 14, top: tip.cy + 14, zIndex: 30, pointerEvents: 'none', maxWidth: 360, fontSize: 12,
      background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--line)', borderRadius: 6, padding: '6px 8px', boxShadow: '0 4px 14px var(--shadow)' }}>
      <b>Скв. {name}</b><br />Отметка {fmt(tip.z)} м а.о.{alt !== null ? ' · MD ' + fmt(alt - tip.z) + ' м' : ' · MD: нет альтитуды'}
      {lines(tip.z).map((l, i) => <div key={i}>{l}</div>)}</div>}
    </>
  )
}

/** Выносная легенда справа от планшетов (тоже SVG, попадает в PNG): цвет каждой модели, критерий газа текстом, смысл линий. */
function Legend({ entries, criterion }: { entries: { color: string; text: string }[]; criterion: string }) {
  const crit = wrapText('Критерий газа: ' + criterion, 34)
  const rowsTop = HEAD + 14
  const critTop = rowsTop + (entries.length + 1) * 18 + 16
  const ruleTop = critTop + crit.length * 14 + 14
  const height = ruleTop + 2 * 18 + 16
  return (
    <svg width={250} height={Math.max(height, HEAD + 200)} role="img" aria-label="Легенда планшета"
      style={{ background: 'var(--chart-surface)', border: '1px solid var(--line)', borderRadius: 6, flex: '0 0 auto' }}>
      <text x={8} y={HEAD - 20} fontSize={11} fontWeight={700} fill="var(--chart-ink)">Легенда</text>
      {[{ color: 'var(--map-water)', text: 'ГВК факт (ГИС по пачкам)' }, ...entries].map((e, i) => <g key={i}>
        <line x1={8} x2={36} y1={rowsTop + i * 18 - 4} y2={rowsTop + i * 18 - 4} stroke={e.color} strokeWidth={2.5} />
        <text x={42} y={rowsTop + i * 18} fontSize={11} fill="var(--chart-ink)">{e.text}</text></g>)}
      {crit.map((line, i) => <text key={'c' + i} x={8} y={critTop + i * 14} fontSize={10} fill="var(--chart-muted)">{line}</text>)}
      <line x1={8} x2={36} y1={ruleTop} y2={ruleTop} stroke="var(--chart-ink)" strokeWidth={2} />
      <text x={42} y={ruleTop + 4} fontSize={10} fill="var(--chart-muted)">граница ячейки модели</text>
      <line x1={8} x2={36} y1={ruleTop + 18} y2={ruleTop + 18} stroke="var(--chart-ink)" strokeWidth={2} strokeDasharray="5 3" />
      <text x={42} y={ruleTop + 22} fontSize={10} fill="var(--chart-muted)">интерполяция Sg</text>
    </svg>
  )
}

/** PNG из SVG планшетов: переменные цвета подставляются из текущей темы, планшеты идут в ряд на белом/тёмном фоне темы. */
function savePng(box: HTMLElement | null, name: string) {
  const svgs = Array.from(box?.querySelectorAll('svg') || [])
  if (!svgs.length) return
  const root = getComputedStyle(document.documentElement)
  const resolve = (src: string) => src.replace(/var\((--[a-z0-9-]+)\)/g, (_m, v: string) => root.getPropertyValue(v).trim() || '#888')
  const scale = 2, gap = 12
  const items = svgs.map(sv => ({ w: Number(sv.getAttribute('width')), h: Number(sv.getAttribute('height')), xml: resolve(new XMLSerializer().serializeToString(sv)) }))
  const W2 = items.reduce((a, i) => a + i.w + gap, -gap), H2 = Math.max(...items.map(i => i.h))
  const canvas = document.createElement('canvas'); canvas.width = W2 * scale; canvas.height = H2 * scale
  const ctx = canvas.getContext('2d')!; ctx.scale(scale, scale)
  ctx.fillStyle = root.getPropertyValue('--bg').trim() || '#fff'; ctx.fillRect(0, 0, W2, H2)
  let x = 0, left = items.length
  items.forEach(i => {
    const img = new Image(); const px = x
    img.onload = () => {
      ctx.drawImage(img, px, 0, i.w, i.h)
      if (--left === 0) canvas.toBlob(b => { if (!b) return; const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = name + '.png'; a.click(); URL.revokeObjectURL(a.href) })
    }
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(i.xml.includes('xmlns=') ? i.xml : i.xml.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"'))
    x += i.w + gap
  })
}

interface Item { fact: FactWell; perfs: Record<string, ModelPerfRow>; profiles: { model: ModelEntry; p: WellProfile | null; stepDate: string; err?: string }[] }
interface WellOut { well: string; perf: FactWell['perforation']; items: Item[] }

const pickKey = (o: GisObs) => o.well + '|' + o.date
const pickLabel = (o: GisObs) => 'Скв. ' + o.well + ' · ' + o.date + ' · ' + o.season

export default function Planshet() {
  const [gisFolder, setGisFolder] = useState('')
  const [perfFile, setPerfFile] = useState('')
  const [perfModel, setPerfModel] = useState('')                     // перфорации из входного файла этой модели (главнее файла); пусто — из файла
  const [allModels, setAllModels] = useState<ModelEntry[]>([])
  const [catalog, setCatalog] = useState<{ wells: string[]; observations: GisObs[] }>({ wells: [], observations: [] })
  const [wells, setWells] = useState<string[]>([])
  const [seasons, setSeasons] = useState<string[]>([])
  const [allInSeason, setAllInSeason] = useState(false)             // подсказка: все замеры сезона, а не последний
  const [manual, setManual] = useState<Record<string, boolean>>({}) // ручной выбор замеров главнее подсказки
  const [pasted, setPasted] = useState('')
  const [crit, setCrit] = useState<CriterionCfg>({ logic: 'sg_sgcr', value: 0, fallback: 0.01 })
  const [built, setBuilt] = useState<CriterionCfg | null>(null)     // критерий, с которым построен планшет (легенда показывает его, а не текущий выбор)
  const [presets, setPresets] = useState<CriterionPreset[]>([])
  const [models, setModels] = useState<ModelEntry[]>([])
  const [wellsOut, setWellsOut] = useState<WellOut[]>([])
  const [zFrom, setZFrom] = useState('')
  const [zTo, setZTo] = useState('')
  const [alts, setAlts] = useState<Record<string, string>>({})      // альтитуда вручную по скважинам
  const [hand, setHand] = useState<Record<string, string>>({})      // свой ГВК вручную по скважинам, м а.о.
  const [hidden, setHidden] = useState<string[]>([])                // скрытые модели
  const boxRef = useRef<HTMLDivElement>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [mode, setMode] = useState<Mode>('tvdss')
  const [hz, setHz] = useState<number | null>(null)       // общая линия наведения у всех скважин
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const loadCatalog = () => getPlanshetCatalog().then(setCatalog).catch(e => { setCatalog({ wells: [], observations: [] }); setMsg((e as Error).message) })
  useEffect(() => {
    getSources().then(v => { setGisFolder(v.sources.gis?.folder || ''); setPerfFile(v.sources.gis?.perf_file || ''); setPerfModel(v.sources.gis?.perf_model || ''); if (v.sources.gis?.folder) loadCatalog() }).catch(() => undefined)
    getModels().then(v => { setAllModels(v.models); setModels(v.models.filter(m => m.selected)) }).catch(e => setMsg((e as Error).message))
    getCriterionPresets().then(r => setPresets(r.presets)).catch(() => undefined)
  }, [])
  const guard = async (f: () => Promise<void>) => { setBusy(true); setMsg(''); try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) } }
  const saveGis = (folder: string, perf: string) => guard(async () => { await setSources({ gis: { folder, perf_file: perf } }); setGisFolder(folder); setPerfFile(perf); if (folder) await loadCatalog() })
  const savePerfModel = (id: string) => guard(async () => { await setSources({ gis: { folder: gisFolder, perf_file: perfFile, perf_model: id } }); setPerfModel(id); setMsg(id ? 'Перфорации будут взяты из модели; нажмите «Построить» ещё раз' : 'Перфорации снова из файла; нажмите «Построить» ещё раз') })
  const pickGis = async () => { const f = await pickFolder(gisFolder); if (f) await saveGis(f, perfFile) }
  const pickPerf = async () => { const r = await pickFile(perfFile); if (r.path) await saveGis(gisFolder, r.path) }

  // Замеры выбранных скважин; сезон = «осень/весна + год». Подсказка: без сезонов — последний замер скважины,
  // с сезонами — последний (или все) замер скважины в каждом выбранном сезоне. Ручной выбор главнее подсказки.
  const mine = useMemo(() => catalog.observations.filter(o => wells.includes(o.well)), [catalog, wells])
  const seasonList = useMemo(() => Array.from(new Set(catalog.observations.map(o => o.season))), [catalog])
  const suggested = useMemo(() => {
    const out = new Set<string>()
    for (const w of wells) {
      const ws = mine.filter(o => o.well === w)
      if (!seasons.length) { if (ws.length) out.add(pickKey(ws[ws.length - 1])); continue }
      for (const s of seasons) {
        const inS = ws.filter(o => o.season === s)
        if (allInSeason) inS.forEach(o => out.add(pickKey(o))); else if (inS.length) out.add(pickKey(inS[inS.length - 1]))
      }
    }
    return out
  }, [wells, seasons, allInSeason, mine])
  const chosen = mine.filter(o => (pickKey(o) in manual ? manual[pickKey(o)] : suggested.has(pickKey(o))))
  const setChosen = (labels: string[]) => {
    const next = { ...manual }
    mine.forEach(o => { next[pickKey(o)] = labels.includes(pickLabel(o)) })
    setManual(next)
  }
  const pasteWells = () => {
    const add = pasted.split(/[;,|\s]+/).map(x => x.trim()).filter(Boolean)
    const known = add.filter(w => catalog.wells.includes(w)), miss = add.filter(w => !catalog.wells.includes(w))
    setWells(catalog.wells.filter(w => wells.includes(w) || known.includes(w)))
    setPasted('')
    setMsg(miss.length ? 'В базе ГИС нет скважин: ' + miss.join(', ') : '')
  }

  const build = () => guard(async () => {
    if (!chosen.length) throw new Error('Выберите скважины и замеры')
    const f = await getPlanshetFacts(chosen.map(o => [o.well, o.date] as [string, string]), alts)
    setNotes(Array.from(new Set([...f.notes, ...f.rows.flatMap(r => r.notes.map(n => 'Скв. ' + r.well + ': ' + n))])))
    // профили моделей: один запрос на модель и дату среза сразу для всех скважин этой даты (сетка читается один раз)
    const items: Item[] = f.rows.map(row => ({ fact: row, perfs: {}, profiles: [] }))
    const byDate: Record<string, Item[]> = {}
    items.forEach(o => { (byDate[o.fact.date] = byDate[o.fact.date] || []).push(o) })
    for (const m of models) {
      for (const [day, group] of Object.entries(byDate)) {
        try {
          const r = await getWellProfile(m.id, group.map(g => g.fact.well), day, '', crit)
          group.forEach(g => g.profiles.push({ model: m, p: r.rows.find(x => x.well === g.fact.well) || null, stepDate: r.step_date }))
        } catch (e) { group.forEach(g => g.profiles.push({ model: m, p: null, stepDate: '', err: (e as Error).message })) }
      }
    }
    // перфорации каждой модели из её входных файлов (COMPDAT) на дату замера — чтобы сравнивать модели с разными интервалами
    if (models.length) {
      try {
        const r = await getModelPerfs(models.map(m => m.id), items.map(o => [o.fact.well, o.fact.date] as [string, string]))
        r.rows.forEach(x => { const it = items.find(o => o.fact.well === x.well && o.fact.date === x.date); if (it) it.perfs[x.model] = x })
      } catch (e) { setMsg('Перфорации моделей не прочитаны: ' + (e as Error).message) }
    }
    const out: WellOut[] = []
    items.forEach(it => {
      let w = out.find(x => x.well === it.fact.well)
      if (!w) { w = { well: it.fact.well, perf: it.fact.perforation, items: [] }; out.push(w) }
      w.items.push(it)
    })
    setBuilt(crit)
    setWellsOut(out)
  })

  const handGwc = (w: string) => { const z = Number((hand[w] || '').replace(',', '.')); return hand[w] && !isNaN(z) ? [{ label: 'ручн.', z }] : [] }
  const critText = (c: CriterionCfg) => {
    const p = presets.find(x => x.logic === c.logic && x.value === c.value && x.fallback === c.fallback)
    return p ? p.formula : 'ручной: ' + c.logic + ', порог ' + c.value + ', SGCR нет — ' + c.fallback
  }
  const tracksOfItem = ({ fact, perfs, profiles }: Item): Track[] => {
    const tr: Track[] = [{ title: 'ГИС, факт', sub: (fact.season || 'замер') + (fact.date ? ' · ' + fact.date : ''),
      bars: fact.intervals.filter(i => i.kg !== null).map(i => ({ top: i.top, bottom: i.bottom, v: i.kg as number })),
      gwc: [...fact.packs.map(p => ({ label: 'ГВК', z: p.gvk })), ...handGwc(fact.well)], note: fact.intervals.length ? undefined : 'нет интервалов' }]
    profiles.filter(x => !hidden.includes(x.model.id)).forEach(({ model, p, stepDate, err }) => tr.push({
      title: model.name, sub: err ? 'ошибка' : 'Sg · шаг ' + (stepDate || '—'), color: seriesColor(models.findIndex(m => m.id === model.id)),
      bars: (p?.cells || []).map(c => ({ top: c.top, bottom: c.bottom, v: c.sg })), perf: (perfs[model.id]?.intervals || []).map(q => ({ top: q.top, bottom: q.bottom })),
      gwc: p?.gwc ? [{ label: 'ГВК', z: p.gwc.cell }, { label: 'ГВК инт.', z: p.gwc.interp }] : [], note: err ? err.slice(0, 28) : p ? undefined : 'нет ячеек скважины' }))
    return tr
  }
  const trackSets = wellsOut.map(o => o.items.flatMap(tracksOfItem))
  // одна шкала глубины на все скважины: по общему диапазону данных и перфораций, если не задана вручную
  const zs = trackSets.flatMap(ts => ts.flatMap(t => [...t.bars.flatMap(b => [b.top, b.bottom]), ...t.gwc.map(g => g.z).filter((z): z is number => z !== null)]))
    .concat(wellsOut.flatMap(o => (o.perf ? [o.perf.top, o.perf.bottom].filter((z): z is number => z !== null) : [])))
  const auto: [number, number] = zs.length ? [Math.floor(Math.min(...zs) / 10) * 10 - 10, Math.ceil(Math.max(...zs) / 10) * 10 + 10] : [-1000, 0]
  const zMin = zFrom !== '' && !isNaN(Number(zFrom)) ? Number(zFrom) : auto[0]
  const zMax = zTo !== '' && !isNaN(Number(zTo)) ? Number(zTo) : auto[1]
  const setView = (lo: number, hi: number) => { setZFrom(String(Math.round(lo * 10) / 10)); setZTo(String(Math.round(hi * 10) / 10)) }
  const resetView = () => { setZFrom(''); setZTo('') }
  const zoom = (f: number) => { const c = (zMin + zMax) / 2; setView(c - ((zMax - zMin) / 2) * f, c + ((zMax - zMin) / 2) * f) }
  const gwcOf = (t: Track) => t.gwc.map(g => g.z).filter((z): z is number => z !== null)
  const rowsOut = wellsOut.flatMap(o => o.items.map(it => ({ it, tracks: tracksOfItem(it) })))

  return (
    <main className="workspace">
      <PageHead title="Планшет ГВК" lede="Газонасыщенность вдоль скважины в абсолютных отметках: фактический замер ГИС и выбранные модели рядом, ГВК и перфорация." />
      <section className="card">
        <h2>Источники</h2>
        <p className="muted small">Факт — папка выгрузки «Работы с исходными данными» → ГИС (файлы gis_*.csv или .parquet и gis_db_meta.json). Перфорации и альтитуды — «Глубины_перфораций.xlsx».
          Модели берутся те, что отмечены в разделе «Результаты расчёта».</p>
        <div className="row"><span className="small" style={{ width: 120 }}>База ГИС:</span><span title={gisFolder}>{gisFolder ? tail(gisFolder) : <span className="muted">не выбрана</span>}</span>
          <button disabled={busy} onClick={pickGis}>Выбрать папку…</button></div>
        <div className="row"><span className="small" style={{ width: 120 }}>Перфорации:</span><span title={perfFile}>{perfFile ? tail(perfFile) : <span className="muted">не выбран</span>}</span>
          <button disabled={busy} onClick={pickPerf}>Выбрать файл…</button>{perfFile && <button disabled={busy} onClick={() => saveGis(gisFolder, '')}>Убрать</button>}</div>
        <div className="row"><span className="small" style={{ width: 120 }}>Из модели:</span>
          <select disabled={busy} value={perfModel} onChange={e => savePerfModel(e.target.value)} title="Интервалы COMPDAT из входного файла модели на дату замера; если в модели скважины нет — берётся файл">
            <option value="">не брать (только файл)</option>
            {allModels.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
          <span className="muted small">COMPDAT из .data на дату замера; главнее файла, для скважин вне модели остаётся файл</span></div>
        <p className="muted small">Модели: {models.length ? models.map(m => m.name).join(', ') : 'не отмечены — планшет покажет только факт'}</p>
      </section>
      <section className="card">
        <div className="row" style={{ flexWrap: 'wrap', alignItems: 'stretch' }}>
          <MultiSelect label="Скважины" options={catalog.wells} value={wells} onChange={setWells} emptyMeaning="не выбраны" prefix="№ " />
          <MultiSelect label="Сезоны ГИС" options={seasonList} value={seasons} onChange={setSeasons} emptyMeaning="последний замер" />
          <MultiSelect label="Замеры" options={mine.map(pickLabel)} value={chosen.map(pickLabel)} onChange={setChosen} emptyMeaning="не выбраны" />
          <label className="small" title="Подсказка для выбранных сезонов; отдельные замеры в списке «Замеры» правятся вручную">
            <input type="checkbox" checked={allInSeason} onChange={e => setAllInSeason(e.target.checked)} /> все замеры сезона (иначе последний)</label>
          <input style={{ width: 200 }} placeholder="вставить номера скважин" value={pasted} onChange={e => setPasted(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') pasteWells() }} />
          <button disabled={!pasted.trim() || !catalog.wells.length} onClick={pasteWells}>Добавить</button>
        </div>
        <p className="muted small">Соседние месяцы одного сезона (например, октябрь и ноябрь) — один сезон: выберите сезон целиком, и в нём берётся последний замер каждой скважины.
          Замеры можно отметить и вручную — ручной выбор главнее подсказки. {catalog.wells.length ? '' : 'Выберите базу ГИС, чтобы получить список скважин.'}</p>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <button className="primary" disabled={busy || !gisFolder || !chosen.length} onClick={build}>Построить ({chosen.length})</button>
          <CriterionPicker value={crit} onChange={setCrit} />
          <span className="muted small">Шкала, м а.о. от:</span><input style={{ width: 70 }} placeholder="авто" value={zFrom} onChange={e => setZFrom(e.target.value)} />
          <span className="muted small">до:</span><input style={{ width: 70 }} placeholder="авто" value={zTo} onChange={e => setZTo(e.target.value)} />
        </div>
        {msg && <p className="note warn">{msg}</p>}
        {notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {wellsOut.length > 0 && <div style={{ overflowX: 'auto', marginTop: 12 }}>
          <div className="row small" style={{ flexWrap: 'wrap' }}>
            <span className="muted">Вручную (последнее слово за инженером):</span>
            {wellsOut.map(o => <span key={o.well}>Скв. {o.well}: альтитуда <input style={{ width: 70 }} placeholder={fmt(o.items[0]?.fact.altitude)} value={alts[o.well] || ''} onChange={e => setAlts({ ...alts, [o.well]: e.target.value })} />
              {' '}свой ГВК <input style={{ width: 70 }} placeholder="м а.о." value={hand[o.well] || ''} onChange={e => setHand({ ...hand, [o.well]: e.target.value })} /></span>)}
            <button disabled={busy} onClick={build} title="Пересчитать отметки с заданными альтитудами">Применить альтитуды</button>
            {models.map(m => <label key={m.id}><input type="checkbox" checked={!hidden.includes(m.id)} onChange={() => setHidden(hidden.includes(m.id) ? hidden.filter(x => x !== m.id) : [...hidden, m.id])} /> {m.name}</label>)}
            <select value={mode} onChange={e => setMode(e.target.value as Mode)} title="Шкала глубины">
              <option value="tvdss">TVDSS (м а.о.)</option><option value="md">MD (от стола)</option></select>
            <button onClick={() => zoom(0.7)} title="Приблизить">＋</button><button onClick={() => zoom(1.4)} title="Отдалить">－</button>
            <button onClick={resetView} title="Сбросить масштаб (двойной щелчок по планшету)">Сбросить масштаб</button>
            <button onClick={() => savePng(boxRef.current, 'планшет_ГВК')}>Сохранить PNG</button>
          </div>
          <div ref={boxRef} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            {wellsOut.map((o, i) => <WellLog key={o.well} name={o.well} tracks={trackSets[i]} perf={o.perf} zMin={zMin} zMax={zMax} h={560}
              mode={mode} alt={o.items[0]?.fact.altitude ?? null} hz={hz} onHover={setHz} onView={setView} onReset={resetView} />)}
            <Legend criterion={critText(built ?? crit)} entries={models.filter(m => !hidden.includes(m.id)).map(m => ({ color: seriesColor(models.indexOf(m)), text: 'Модель ' + m.name }))} />
          </div>
          <p className="muted small">Глубины — абсолютные отметки, вниз — меньше (со знаком минус); шкала глубины и шкалы 0…1 одинаковые у всех скважин. Узкая полоса слева — перфорация. Колесо мыши — масштаб, перетаскивание — сдвиг, двойной щелчок — сброс; подсказка — по наведению. MD = альтитуда − отметка (для наклонной скважины приближение).
            Линия цвета воды — ГВК: у факта по пачкам из базы ГИС, у каждой модели — свой цвет (легенда справа): сверху вниз, граница ячейки (сплошная) и интерполяция Sg (пунктир). Газ — по критерию, который указан в легенде; критерий применяется при «Построить».</p>
          {rowsOut.length > 1 && <table className="raw"><thead><tr><th>Скважина</th><th>Замер</th><th>Сезон</th><th>Альтитуда, м</th><th>ГВК факт, м</th>{models.filter(m => !hidden.includes(m.id)).map(m => <th key={m.id}>ГВК {m.name}, м</th>)}</tr></thead>
            <tbody>{rowsOut.map(({ it, tracks }) => <tr key={it.fact.well + it.fact.date}><td>{it.fact.well}</td><td>{it.fact.date || '—'}</td><td>{it.fact.season || '—'}</td><td className="num">{fmt(it.fact.altitude)}</td>
              {tracks.map((t, k) => <td key={k} className="num">{gwcOf(t).length ? gwcOf(t).map(z => fmt(z)).join('; ') : '—'}</td>)}</tr>)}</tbody></table>}
        </div>}
      </section>
      <GwcCompare models={models} criterion={crit} alts={alts} />
    </main>
  )
}
