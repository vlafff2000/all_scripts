import Chart from './MiniChart'
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { legendOpen, pickedSeasons, seasonScope, spreadWells, clusterWells, groupColoring, mapGrid, refWells, refSize, usePref, type SeasonScope } from './prefs'
import { createPortal } from 'react-dom'
import { groupColor, reportIssue, type TnavModel, type Observers, type GisCatalog, type GspData, type ParamItem, type SeasonInfo } from './api'
import ModelPicker, { type ModelPickerProps } from './ModelPicker'
import PolyPanel from './PolyPanel'
import { sortLabels } from './legendOrder'
import BgPanel from './BgPanel'
import { bgAlign, bgOpacity, bgShow, useBgUrl } from './background'
import { alignTransform, applyAffine, FLIP_Y, polyAlign, polyStyles, styleOf, usePolygons } from './polygons'
import { ALL_CRITERION_SPEC, AW_MODES, AW_DEPTHS, awDeviation, awResidual, awValue, type AwDepth, type AwMode, type AwPoint, type GisModelWells, type GisVariants } from './allWells'
import { PAINTS, ATLAS_AGGS, GAS, SEASON_STOPS, SEASON_STOPS_DARK, type PaintData, paintFor, rampColor, scopeKeys, waterMonths, type Paint, type Scope, MONTH_NAME, MONTH_SHORT, SeasonCalc, WATER, fmt1, fmtDay, fmtMln, fmtPct, fmtTh, contourLines, fillRoofGaps, parseRefWells, REF_PRESET_AN2025, gwcContour, gwcUnified, isolines, niceLevelStep, monthOf, niceStep, place, sectorPath, waterByWell, type GwcParams, type GwcUnified, type IsoResult, type RoofRaster } from './model'

/** Цвета вариантов критерия: одинаковы на карте, в списке вариантов панели и в подписях изолиний. */
/** Кровля пласта: от синего (глубже) к светло-жёлтому (выше). */
const ROOF_STOPS = ['#9cc3e4', '#c7dfe9', '#e8efd9', '#f6e9bf']
export const AW_COLORS = ['#d62728', '#1f77b4', '#2ca02c', '#9467bd', '#ff7f0e', '#17becf', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#393b79', '#e7ba52']

export interface MapOptions { sectors: 'months' | 'plain'; water: boolean; share: boolean; fixed: boolean; paint: Paint; scale: number; labels: 'num' | 'val' | 'none'; hideIdle: boolean; minValue: number }
/** Параметр Атласа на карте: список параметров, выбор и агрегация, готовая раскраска (считает страница). */
export interface AtlasPicker { items: ParamItem[]; pick: string; agg: string; onPick: (pick: string, agg: string) => void; paint: PaintData | null }
/** Раскраска по моделям tNavigator: выбор моделей и вектора (панель) и значения на карте (paint). */
/** Режим «ГИС и ГВК»: что выбрано и что можно выбрать; замер скважины закрепляется вручную (pins), по умолчанию берётся последний в сезоне. */
export interface GisPicker {
  catalog: GisCatalog | null; pack: string; metric: string; season: string; against: string; pins: Record<string, string>
  options: Record<string, string[]>; dates: Record<string, string>; paint: PaintData | null
  iso: { on: boolean; step: string; reach: string }; isoNote: string
  /** Наблюдательные скважины (вне групп): свой флажок показа, ручное отнесение к наблюдательным/эксплуатационным. */
  obs: { on: boolean; geoOn: boolean; data: Observers | null; onToggle: (v: boolean) => void; onToggleGeo: (v: boolean) => void }
  source: 'fact' | 'model' | 'delta'; modelInfo: string; error?: string
  gwc: { on: boolean; mode: 'unified' | 'plane' | 'idw'; par: GwcParams; excl: Set<string> }
  /** ГВК по всем скважинам модели (выключено по умолчанию): модель, срез, способ и глубина, порог Sg, порог подсказки о выбросе, исключённые скважины. */
  allWells: { on: boolean; model: string; models: TnavModel[]; date: string; dates: string[]; mode: AwMode; depth: AwDepth; preset: string; presets: { id: string; title: string }[]; outlier: string; excl: Set<string>; data: GisModelWells | null; err: string; fact: Record<string, number> | null; multi: boolean; spec: string; variants: GisVariants | null; variantsErr: string; variantsBusy: boolean }
  roof: { on: boolean; model: string; layer: string; step: string; models: TnavModel[]; note: string; grid: RoofRaster | null }
  onChange: (p: { pack?: string; metric?: string; season?: string; against?: string; pins?: Record<string, string>; iso?: boolean; isoStep?: string; isoReach?: string; source?: 'fact' | 'model' | 'delta'; roofOn?: boolean; roofModel?: string; roofLayer?: string; roofStep?: string; gwcOn?: boolean; gwcMode?: 'unified' | 'plane' | 'idw'; gwcPar?: Partial<GwcParams>; gwcToggle?: string; gwcReset?: boolean; awOn?: boolean; awModel?: string; awDate?: string; awMode?: AwMode; awDepth?: AwDepth; awPreset?: string; awMulti?: boolean; awSpec?: string; awOutlier?: string; awToggle?: string; awReset?: boolean }) => void
}
/** Растр кровли в координатах карты (Y вниз): z по строкам, NaN — нет значения. */
export interface ModelsPanel { picker: ModelPickerProps; paint: PaintData | null }
export interface MapHandle { toPng: () => Promise<Blob>; fit: () => void; focus: (well: number) => void }
interface Props {
  g: GspData; calc: SeasonCalc; kind: string; season: string; a: number; b: number
  options: MapOptions; onOptions: (o: Partial<MapOptions>) => void; selected: number | null; onSelect: (w: number | null) => void; group: number[]; onGroup: (ws: number[]) => void; title: string
  /** Параметр Атласа: только на странице карты. */
  atlas?: AtlasPicker
  gis?: GisPicker
  models?: ModelsPanel
  /** Режим сравнения: общий масштаб кругов и общий вид (зум/сдвиг) у двух карт. */
  /** Куда выводить подсказку: элемент вне карты (тогда она не закрывает скважины) или null — рядом с курсором. */
  tipHost?: HTMLElement | null; tipTag?: string; stickyTip?: boolean
  /** Сезоны для раскраски «Ввод» и «Обводнённость»: выбор периода показывается в панели «Вид карты», только если передан. */
  multi?: { seasons: SeasonInfo[]; calcs: Map<string, SeasonCalc> }
  compact?: boolean; scaleMax?: number; view?: View; onView?: (v: View) => void
}
export interface View { k: number; tx: number; ty: number }
interface Tip { x: number; y: number; well: number }

const EMPTY: never[] = []
const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** Цвета карты берутся из темы и передаются числами: так они попадают и в PNG, где CSS-переменных нет. */
interface Pal { surface: string; bg: string; grid: string; ink: string; muted: string; line: string; accent: string; water: string; gas: string }
const readPal = (): Pal => ({
  surface: css('--surface') || '#fff', bg: css('--map-bg') || '#f7f9f9', grid: css('--map-grid') || '#e3e9ea', ink: css('--ink') || '#1b2a31',
  muted: css('--muted') || '#5f7178', line: css('--line') || '#dbe3e5', accent: css('--accent') || '#149ba5', water: css('--map-water') || WATER, gas: css('--map-gas') || GAS,
})

const Glyph = memo(function Glyph(p: {
  well: number; x: number; y: number; r: number; rmax: number; total: number; share: number; months: number[]; order: number[]; monthColors: string[]
  sectors: boolean; paint?: { color: string; label: string } | null; water: { factor: number | null; flow: number | null; color: string }[]; maxFlow: number; showShare: boolean
  selected: boolean; label: string; dim: boolean; hot?: boolean; gcolor?: string; pal: Pal
}) {
  const { x, y, rmax, pal } = p
  const idle = p.paint === undefined ? !(p.total > 0) : !p.paint
  const r = p.paint !== undefined ? (p.paint ? rmax * 0.62 : rmax * 0.24) : idle ? rmax * 0.24 : p.r
  const ring = rmax * 0.05
  const els: React.ReactNode[] = []
  if (idle) {
    els.push(<circle key="c" cx={x} cy={y} r={r} fill={pal.surface} stroke={pal.muted} strokeWidth={rmax * 0.04} strokeDasharray={`${rmax * 0.09} ${rmax * 0.07}`} />)
  } else if (p.paint) {
    els.push(<circle key="c" cx={x} cy={y} r={r} fill={p.paint.color} stroke={p.gcolor || pal.surface} strokeWidth={p.gcolor ? ring * 2.2 : ring} />)
  } else if (!p.sectors || p.gcolor) {
    els.push(<circle key="c" cx={x} cy={y} r={r} fill={p.gcolor || pal.gas} stroke={pal.surface} strokeWidth={ring} />)
  } else {
    const sum = p.months.reduce((s, v) => s + v, 0) || 1
    const parts = p.order.filter(m => p.months[m] > 0)
    if (parts.length <= 1) els.push(<circle key="c" cx={x} cy={y} r={r} fill={p.monthColors[parts[0] ?? 0] || pal.gas} stroke={pal.surface} strokeWidth={ring} />)
    else {
      let a0 = 0
      for (const m of parts) {
        const a1 = a0 + (p.months[m] / sum) * Math.PI * 2
        els.push(<path key={m} d={sectorPath(x, y, r, a0, a1)} fill={p.monthColors[m]} stroke={pal.surface} strokeWidth={rmax * 0.03} strokeLinejoin="round" />)
        a0 = a1
      }
      els.push(<circle key="o" cx={x} cy={y} r={r} fill="none" stroke={pal.surface} strokeWidth={ring} />)
    }
  }
  // вода: по кольцу на каждый месяц с водой, снаружи друг от друга (раньше — ближе к кругу), цвет — месяц, толщина ∝ л/ч; водный фактор — кружок на внешнем кольце
  const ws = p.water.filter(w => (w.flow ?? 0) > 0)
  if (ws.length && !idle) {
    let r0 = r + rmax * 0.07
    ws.forEach((w, i) => {
      const t = rmax * 0.12 * (0.4 + 0.6 * Math.sqrt((w.flow ?? 0) / (p.maxFlow || 1)))
      els.push(<circle key={'w' + i} cx={x} cy={y} r={r0 + t / 2} fill="none" stroke={w.color} strokeWidth={t} />)
      r0 += t + rmax * 0.02
    })
    const wf = Math.max(...ws.map(w => w.factor ?? 0))
    if (wf > 0) {
      const t = String(Math.round(wf)), br = rmax * (t.length > 2 ? 0.27 : 0.22), ang = Math.PI / 4, rr = r0 + rmax * 0.02
      const bx = x + rr * Math.sin(ang), by = y - rr * Math.cos(ang)
      els.push(<g key="wf"><circle cx={bx} cy={by} r={br} fill={ws[ws.length - 1].color} stroke={pal.surface} strokeWidth={rmax * 0.035} />
        <text x={bx} y={by} fontSize={br * (t.length > 2 ? 0.95 : 1.15)} textAnchor="middle" dominantBaseline="central" fill="#fff" fontWeight={700}>{t}</text></g>)
    }
  }
  // подпись: внутри крупного круга — белым, у мелкого — рядом, цветом текста с ореолом фона
  const two = p.paint ? p.paint.label : ''
  const fs = rmax * (p.label.length > 4 ? 0.3 : p.label.length > 3 ? 0.36 : 0.42)
  const inside = !idle && r >= fs * (p.label.length > 3 ? 1.5 : 1.1)
  const share = !idle && p.paint === undefined && p.showShare && p.share >= 0.02 ? (p.share * 100).toFixed(p.share >= 0.1 ? 0 : 1).replace('.', ',') + ' %' : ''
  const lx = inside ? x : x + r + rmax * 0.1, ly = y
  return (
    <g className="glyph" data-well={p.well} opacity={p.dim ? 0.22 : 1}>
      {p.hot && !p.selected && <circle cx={x} cy={y} r={r + rmax * 0.18} fill="none" stroke={pal.accent} strokeWidth={rmax * 0.07} />}
      {p.selected && <circle cx={x} cy={y} r={r + rmax * 0.26} fill={pal.accent} fillOpacity={0.16} stroke={pal.accent} strokeWidth={rmax * 0.06} />}
      {els}
      {p.label && (inside
        ? <text x={lx} y={ly - (two || (share && r > fs * 2) ? fs * 0.38 : 0)} fontSize={fs} textAnchor="middle" dominantBaseline="central" fontWeight={700} fill="#fff"
            stroke="rgba(30,8,12,.45)" strokeWidth={fs * 0.14} paintOrder="stroke" strokeLinejoin="round">{p.label}</text>
        : <text x={lx} y={ly} fontSize={fs * 0.9} dominantBaseline="central" fontWeight={700} fill={idle ? pal.muted : pal.ink}
            stroke={pal.bg} strokeWidth={fs * 0.28} paintOrder="stroke" strokeLinejoin="round">{p.label}{share && <tspan fontWeight={400} fill={pal.muted}> · {share}</tspan>}</text>)}
      {inside && (two || (share && r > fs * 2)) && <text x={x} y={y + fs * 0.62} fontSize={fs * 0.62} textAnchor="middle" dominantBaseline="central" fill="#fff" fillOpacity={0.92}
        stroke="rgba(30,8,12,.4)" strokeWidth={fs * 0.08} paintOrder="stroke">{two || share}</text>}
    </g>
  )
})

/** Скважина в режиме «Опорная сетка»: опорная — крупный круг цвета своей группы с номером, остальные — мелкие нейтральные точки. */
const RefGlyph = memo(function RefGlyph(p: { well: number; x: number; y: number; r: number; color?: string; label: string; selected: boolean; hot: boolean; pal: Pal }) {
  const { x, y, r, pal } = p
  const fs = r * (p.label.length > 3 ? 0.55 : p.label.length > 2 ? 0.66 : 0.8)
  return (
    <g className="glyph" data-well={p.well}>
      {p.hot && !p.selected && <circle cx={x} cy={y} r={r * 1.2} fill="none" stroke={pal.accent} strokeWidth={r * 0.1} />}
      {p.selected && <circle cx={x} cy={y} r={r * 1.3} fill={pal.accent} fillOpacity={0.16} stroke={pal.accent} strokeWidth={r * 0.08} />}
      {p.color
        ? <><circle cx={x} cy={y} r={r} fill={p.color} stroke={pal.surface} strokeWidth={r * 0.12} />
          <text x={x} y={y} fontSize={fs} textAnchor="middle" dominantBaseline="central" fontWeight={700} fill="#fff" stroke="rgba(30,8,12,.45)" strokeWidth={fs * 0.14} paintOrder="stroke" strokeLinejoin="round">{p.label}</text></>
        : <circle cx={x} cy={y} r={r} fill={pal.line} stroke={pal.muted} strokeWidth={r * 0.18} strokeOpacity={0.6} />}
    </g>
  )
})

const ClusterGlyph = memo(function ClusterGlyph(p: { id: number; x: number; y: number; r: number; rd: number; count: number; fill: string; ring?: string; title: string; pal: Pal }) {
  const { x, y, r, rd, pal } = p
  return (
    <g className="cluster" data-cluster={p.id} style={{ cursor: 'zoom-in' }}>
      <title>{p.title}</title>
      <circle cx={x} cy={y} r={r + rd * 0.2} fill={pal.surface} fillOpacity={0.55} stroke={p.ring || p.fill} strokeWidth={rd * 0.07} strokeDasharray={`${rd * 0.2} ${rd * 0.14}`} />
      <circle cx={x} cy={y} r={r} fill={p.fill} fillOpacity={0.88} stroke={pal.surface} strokeWidth={rd * 0.06} />
      <text x={x} y={y} fontSize={Math.min(r * 0.95, rd * 0.78)} textAnchor="middle" dominantBaseline="central" fontWeight={700} fill="#fff" stroke="rgba(30,8,12,.4)" strokeWidth={rd * 0.07} paintOrder="stroke" strokeLinejoin="round">{p.count}</text>
    </g>
  )
})

function niceCoord(v: number) { return Math.round(v).toLocaleString('ru-RU') }

/** Показанные на карте наблюдательные (◆) и геофизические (▲) скважины: фонд задаётся в Атласе, здесь только показ. */
function shownFunds(obs: GisPicker['obs']) {
  return (obs.data?.wells ?? []).filter(o => (o.fund === 'geophysical' ? obs.geoOn : obs.on))
}
function ObserverControls({ obs }: { obs: GisPicker['obs'] }) {
  const d = obs.data
  const count = (fund: string) => d ? [...d.wells, ...d.missing].filter(o => o.fund === fund).length : 0
  const missing = d?.missing.filter(o => (o.fund === 'geophysical' ? obs.geoOn : obs.on)) ?? []
  return <>
    <label className="check"><input type="checkbox" checked={obs.on} onChange={e => obs.onToggle(e.target.checked)} /> Наблюдательные скважины (◆){d ? ` · ${count('observation')}` : ''}</label>
    <label className="check"><input type="checkbox" checked={obs.geoOn} onChange={e => obs.onToggleGeo(e.target.checked)} /> Геофизические скважины (▲){d ? ` · ${count('geophysical')}` : ''}</label>
    {(obs.on || obs.geoOn) && d && <div className="gis-pin">
      <span className="muted">{d.note || 'Фонд скважин (эксплуатационная, наблюдательная, геофизическая) настраивается в Атласе, вкладка «Фонды скважин». Подсказка программы показывает причину, решение за вами.'}</span>
      {missing.length > 0 && <span className="muted" title="Нет X, Y в проекте Атласа">Нет координат: {missing.map(m => m.well).join(', ')}</span>}
    </div>}
  </>
}
function GisControls({ gwcShares, catalog, pack, metric, season, against, pins, options, dates, iso, isoNote, obs, source, modelInfo, roof, gwc, gwcNote, allWells: aw, awNote, error, onChange }: GisPicker & { gwcNote: string; gwcShares: GwcUnified['shares']; awNote: string }) {
  const [well, setWell] = useState('')
  if (!catalog) return error ? <p className="note warning">{error}</p> : <p className="muted">Читаю базу ГИС…</p>
  if (!catalog.packs.length) return <p className="muted">{catalog.note || 'В проекте Атласа нет базы ГИС.'}</p>
  const multi = Object.keys(options).sort((a, b) => Number(a) - Number(b))
  const w = multi.includes(well) ? well : multi[0] ?? ''
  const cur = pins[w] || (dates[w] ?? '')
  return <>
    {error && <p className="note warning">{error}</p>}
    <select value={source} onChange={e => onChange({ source: e.target.value as 'fact' | 'model' | 'delta' })} aria-label="Источник значений">
      <option value="fact">Факт ГИС</option><option value="model">ГВК модели (из ГДМ)</option><option value="delta">Модель − факт (из ГДМ)</option></select>
    <select value={pack} onChange={e => onChange({ pack: e.target.value })} aria-label="Пачка">
      {catalog.packs.map(p => <option key={p} value={p}>Пачка: {p}</option>)}</select>
    {source === 'fact' && <select value={metric} onChange={e => onChange({ metric: e.target.value })} aria-label="Показатель ГИС">
      {catalog.metrics.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}</select>}
    <select value={season} onChange={e => onChange({ season: e.target.value })} aria-label="Сезон замера">
      {catalog.seasons.map(s => <option key={s.key} value={s.key}>{s.key} · скважин {s.wells}</option>)}</select>
    {source === 'fact' ? <select value={against} onChange={e => onChange({ against: e.target.value })} aria-label="Сравнить с сезоном">
      <option value="">Без сравнения</option>
      {catalog.seasons.filter(s => s.key !== season).map(s => <option key={s.key} value={s.key}>Изменение к: {s.key}</option>)}</select>
      : <span className="muted">{modelInfo || 'Берётся последнее сравнение из «Планшета ГВК» в ГДМ.'} Исключённые там пары не показываются.</span>}
    <label className="check"><input type="checkbox" checked={iso.on} onChange={e => onChange({ iso: e.target.checked })} /> Изолинии по скважинам</label>
    {iso.on && <div className="gis-pin">
      <select value={iso.step} onChange={e => onChange({ isoStep: e.target.value })} aria-label="Шаг изолиний">
        <option value="">Шаг: подобрать</option>{['0.1', '0.5', '1', '2', '5', '10', '20'].map(s => <option key={s} value={s}>Шаг {s}</option>)}</select>
      <select value={iso.reach} onChange={e => onChange({ isoReach: e.target.value })} aria-label="Радиус доверия">
        {[['1', 'Радиус доверия: 1 расстояние между скважинами'], ['1.5', 'Радиус доверия: 1,5'], ['2.5', 'Радиус доверия: 2,5'], ['4', 'Радиус доверия: 4']].map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
      <span className="muted">За краем области скважин изолинии не строятся; чем дальше от скважин, тем бледнее заливка.{isoNote ? ' ' + isoNote : ''}</span>
    </div>}
    <label className="check"><input type="checkbox" checked={aw.on} onChange={e => onChange({ awOn: e.target.checked })} /> ГВК по всем скважинам модели</label>
    {aw.on && <div className="gis-pin">
      <select value={aw.model} onChange={e => onChange({ awModel: e.target.value })} aria-label="Модель для ГВК по всем скважинам">
        <option value="">Выберите модель…</option>{aw.models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
      <select value={aw.date} onChange={e => onChange({ awDate: e.target.value })} aria-label="Срез модели">
        {(aw.dates.length ? aw.dates : [aw.date]).filter(Boolean).map(d => <option key={d} value={d}>Срез модели: {d}</option>)}</select>
      <select value={aw.mode} onChange={e => onChange({ awMode: e.target.value as AwMode })} aria-label="Способ ГВК">{AW_MODES.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
      <select value={aw.depth} onChange={e => onChange({ awDepth: e.target.value as AwDepth })} aria-label="Глубина ГВК">{AW_DEPTHS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
      <select value={aw.preset} onChange={e => onChange({ awPreset: e.target.value })} aria-label="Критерий газа">
        {aw.presets.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select>
      <label className="muted">Подсказка о выбросе, м от соседей <input type="number" min={0} value={aw.outlier} onChange={e => onChange({ awOutlier: e.target.value })} aria-label="Порог выброса" style={{ width: 64 }} /></label>
      <label className="check"><input type="checkbox" checked={aw.multi} onChange={e => onChange({ awMulti: e.target.checked })} /> Несколько вариантов критерия</label>
      <button type="button" onClick={() => onChange({ awMulti: true, awSpec: ALL_CRITERION_SPEC })} title={'Все пресеты критерия с несколькими значениями: ' + ALL_CRITERION_SPEC}>Посчитать по всем опциям</button>
      {aw.multi && <>
        <input type="text" value={aw.spec} onChange={e => onChange({ awSpec: e.target.value })} aria-label="Варианты критерия" style={{ width: 260 }} placeholder="sg_sgcr:0;0,1" />
        <span className="muted">Пресет и значения запаса через запятую, варианты через «;». Не больше 12. {aw.variantsBusy ? 'Считаю варианты…' : aw.variantsErr ? 'Ошибка: ' + aw.variantsErr : ''}</span>
        {aw.variants && !aw.variantsBusy && <ul className="muted" style={{ margin: 0, paddingLeft: 18 }}>{aw.variants.variants.map((v, i) => <li key={v.label}><span aria-hidden="true" style={{ color: AW_COLORS[i % AW_COLORS.length], fontWeight: 700 }}>━━ </span>{v.label}: точек {v.points.length}, без газа {v.no_gas.length}</li>)}</ul>}</>}
      {aw.excl.size > 0 && <button type="button" onClick={() => onChange({ awReset: true })}>Вернуть исключённые ({aw.excl.size})</button>}
      <span className="muted">{awNote}</span>
    </div>}
    <ObserverControls obs={obs} />
    <label className="check"><input type="checkbox" checked={roof.on} onChange={e => onChange({ roofOn: e.target.checked })} /> Кровля пласта из модели</label>
    {roof.on && <div className="gis-pin">
      <select value={roof.model} onChange={e => onChange({ roofModel: e.target.value })} aria-label="Модель для кровли">
        <option value="">Выберите модель…</option>{roof.models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
      <label className="muted">Слой ячеек (0 — верхний активный) <input type="number" min={0} value={roof.layer} onChange={e => onChange({ roofLayer: e.target.value })} aria-label="Слой кровли" style={{ width: 64 }} /></label>
      <select value={roof.step} onChange={e => onChange({ roofStep: e.target.value })} aria-label="Шаг изолиний кровли">
        <option value="">Шаг кровли: подобрать</option>{['2', '5', '10', '20', '50', '100'].map(s => <option key={s} value={s}>Шаг {s} м</option>)}</select>
      <span className="muted">{roof.note || 'Кровля — верх ячеек выбранного слоя модели: слой задаёте вы.'}</span>
      <label className="check"><input type="checkbox" checked={gwc.on} onChange={e => onChange({ gwcOn: e.target.checked })} /> Контур ГВК по кровле</label>
      {gwc.on && <>
        <select value={gwc.mode} onChange={e => onChange({ gwcMode: e.target.value as 'unified' | 'plane' | 'idw' })} aria-label="Поверхность ГВК">
          <option value="unified">Единый контур залежи (как на рис. 5.40)</option>
          <option value="plane">Вокруг скважин: плоскость по скважинам</option><option value="idw">Вокруг скважин: по скважинам как есть</option></select>
        {gwc.mode === 'unified' && <div className="gis-pin">
          {([['sigma', 'σ, м', 'Насколько ГВК скважины может отличаться от кровли в ней, чтобы скважина влияла на контур: дальше — почти не влияет'], ['power', 'Степень', 'Чем больше, тем сильнее вес близких скважин'], ['smooth', 'Сглаживание', 'В средних расстояниях между скважинами: больше — глаже поверхность ГВК'], ['reach', 'Радиус влияния', 'В средних расстояниях: линии дальше этого от скважин с вкладом не рисуются']] as const).map(([k, t, hint]) =>
            <label key={k} className="muted" title={hint}>{t} <input key={String(gwc.par[k])} type="text" inputMode="decimal" defaultValue={String(gwc.par[k])} style={{ width: 52 }} aria-label={t}
              onBlur={e => { const v = Number(e.target.value.replace(',', '.')); if (Number.isFinite(v) && v !== gwc.par[k]) onChange({ gwcPar: { [k]: v } }) }}
              onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} /></label>)}
          <button type="button" className="quiet" onClick={() => onChange({ gwcPar: { sigma: 15, power: 2, smooth: 0.5, reach: 3 } })}>Параметры по умолчанию</button></div>}
        {gwc.mode === 'unified' && gwcShares.length > 0 && <div className="gis-pin" aria-label="Вклад скважин в контур">
          <span className="muted">Вклад скважин (клик — исключить):</span>
          {gwcShares.slice(0, 12).map(s => <button key={s.w} type="button" className="quiet" title={s.delta === null ? 'Кровли в точке скважины нет' : `Кровля в скважине выше ГВК на ${s.delta.toFixed(1)} м`} onClick={() => onChange({ gwcToggle: s.w })}>{s.w} {(s.share * 100).toFixed(0)}%</button>)}
          {gwcShares.length > 12 && <span className="muted">и ещё {gwcShares.length - 12} с малым вкладом</span>}</div>}
        {gwc.mode === 'unified' && gwc.excl.size > 0 && <div className="gis-pin"><span className="muted">Исключены: </span>{[...gwc.excl].map(w => <button key={w} type="button" className="quiet" title="Вернуть в расчёт" onClick={() => onChange({ gwcToggle: w })}>{w} ↩</button>)}
          <button type="button" className="quiet" onClick={() => onChange({ gwcReset: true })}>Вернуть все</button></div>}
        <span className="muted">{gwc.mode === 'unified' ? 'Контур — линия, где кровля пласта пересекает гладкую поверхность ГВК по всем замерам; газ внутри. Обведены скважины, давшие вклад.' : 'Контур — где кровля пересекает ГВК замерных скважин, в радиусе доверия из настройки изолиний.'} {gwcNote}</span></>}
    </div>}
    {source === 'fact' && multi.length > 0 && !against && <div className="gis-pin">
      <span className="muted">В сезоне несколько замеров: по умолчанию последний, другой можно выбрать.</span>
      <select value={w} onChange={e => setWell(e.target.value)} aria-label="Скважина с несколькими замерами">
        {multi.map(x => <option key={x} value={x}>Скважина {x}{pins[x] ? ' (выбран вручную)' : ''}</option>)}</select>
      <select value={cur} onChange={e => onChange({ pins: { ...pins, [w]: e.target.value } })} aria-label="Замер скважины">
        {options[w].map(d => <option key={d} value={d}>{d}</option>)}</select>
      {Object.keys(pins).length > 0 && <button type="button" className="quiet" onClick={() => onChange({ pins: {} })}>Сбросить выбор замеров</button>}
    </div>}
  </>
}

const MapView = forwardRef<MapHandle, Props>(function MapView({ g, calc, kind, season, a, b, options, onOptions, selected, onSelect, group, onGroup, title, tipHost, tipTag, multi, stickyTip = true, compact, scaleMax, view: viewProp, onView, atlas, gis, models }, ref) {
  const wrap = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 800, h: 560 })
  const [viewOwn, setViewOwn] = useState<View>({ k: 1, tx: 0, ty: 0 })
  const view = viewProp || viewOwn
  const viewNow = useRef(view); viewNow.current = view
  const setView = useCallback((u: View | ((v: View) => View)) => {
    const n = typeof u === 'function' ? u(viewNow.current) : u
    viewNow.current = n; setViewOwn(n); onView?.(n)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onView])
  const [tip, setTip] = useState<Tip | null>(null)
  const [fpos, setFpos] = useState<{ x: number; y: number } | null>(null)
  const drag = useRef<{ x: number; y: number; moved: boolean; box?: boolean; x0?: number; y0?: number } | null>(null)
  const panAcc = useRef({ x: 0, y: 0 })
  const panRaf = useRef(0)
  const [box, setBox] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null)

  useLayoutEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setSize({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  const spread = usePref(spreadWells)
  const geo = useMemo(() => place(g, calc, spread), [g, calc, spread])
  const [frameAll, setFrameAll] = useState(false)
  const [layersOpen, setLayersOpen] = useState(false)
  const { placed, spacing, far } = geo
  const obsBox = frameAll && gis && (gis.obs.on || gis.obs.geoOn) && !spread ? shownFunds(gis.obs).filter(o => o.x !== undefined) : []
  const bounds = useMemo(() => {
    const b = frameAll ? geo.boundsAll : geo.bounds
    if (!obsBox.length) return b
    const xs = obsBox.map(o => o.x!), ys = obsBox.map(o => -o.y!)
    return { x0: Math.min(b.x0, ...xs), x1: Math.max(b.x1, ...xs), y0: Math.min(b.y0, ...ys), y1: Math.max(b.y1, ...ys) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frameAll, geo, gis?.obs.data, gis?.obs.on, gis?.obs.geoOn, spread])
  const rmax = useMemo(() => {
    if (geo.unit) return geo.unit
    const span = Math.max(bounds.x1 - bounds.x0, bounds.y1 - bounds.y0, 1)
    // в плотных кустах медианный шаг крошечный: круг не меньше 2,2 % размаха карты (перекрытие лечат зум и порядок отрисовки)
    return Math.min(Math.max(spacing * 0.58, span * 0.022), span * 0.09)
  }, [spacing, bounds, geo.unit])

  // подгонка карты под окно
  const M = 64, top = 64
  const bw = bounds.x1 - bounds.x0 + rmax * 4, bh = bounds.y1 - bounds.y0 + rmax * 4
  const s0 = Math.min((size.w - 2 * M) / bw, (size.h - top - M) / bh)
  const fit = { s: s0, ox: size.w / 2 - s0 * ((bounds.x0 + bounds.x1) / 2), oy: top + (size.h - top - M * 0.5) / 2 - s0 * ((bounds.y0 + bounds.y1) / 2) }
  const resetView = useCallback(() => setView({ k: 1, tx: 0, ty: 0 }), [])
  useEffect(resetView, [g, resetView, frameAll])
  useEffect(() => setFrameAll(false), [g])

  // итоги окна
  const win = useMemo(() => {
    const stats = placed.map(p => calc.stat(p.i, a, b))
    const sumAll = stats.reduce((s, v) => s + (v.total > 0 ? v.total : 0), 0)
    const maxWin = Math.max(1, ...stats.map(v => v.total))
    const maxSeason = Math.max(1, ...placed.map(p => calc.stat(p.i, 0, calc.nd - 1).total))
    const first = monthOf(calc.days[a])
    const order = Array.from({ length: 12 }, (_, i) => (first + i) % 12)
    const months = options.sectors === 'months' ? placed.map(p => calc.monthly(p.i, a, b)) : []
    return { stats, sumAll, scaleMax: scaleMax || (options.fixed ? maxSeason : maxWin), order, months }
  }, [placed, calc, a, b, options.sectors, options.fixed, scaleMax])

  const water = useMemo(() => waterByWell(g.water, kind, season, calc.days[a], calc.days[b]), [g.water, kind, season, calc, a, b])
  const scopeMode = usePref(seasonScope), picked = usePref(pickedSeasons)
  const scope: Scope | undefined = useMemo(() => {
    if (!multi) return undefined
    const keys = scopeKeys(scopeMode, picked, multi.seasons, season)
    return { mode: keys.length === 1 && keys[0] === season ? 'one' : scopeMode, keys, calcs: multi.calcs }
  }, [multi, scopeMode, picked, season])
  const calcPaint: PaintData | null = useMemo(() => paintFor(options.paint, g, calc, kind, season, a, b, options.paint === 'entry' || options.paint === 'wf' ? scope : undefined), [options.paint, g, calc, kind, season, a, b, scope])
  const paintData: PaintData | null = options.paint === 'atlas' ? atlas?.paint ?? null : options.paint === 'model' ? models?.paint ?? null : options.paint === 'gis' ? gis?.paint ?? null : calcPaint
  const wm = useMemo(() => waterMonths(water), [water])
  // кольца воды скважины: один месяц — одно кольцо (замеры месяца сводятся к максимуму)
  const rings = useMemo(() => {
    const out = new Map<number, { factor: number | null; flow: number | null; color: string }[]>()
    for (const [w, pts] of water) {
      const by = new Map<number, { factor: number | null; flow: number | null; color: string }>()
      for (const q of pts) {
        const ym = q.year * 12 + q.month, c = by.get(ym)
        if (!(q.flow && q.flow > 0)) continue
        by.set(ym, { factor: Math.max(q.factor ?? 0, c?.factor ?? 0) || null, flow: Math.max(q.flow, c?.flow ?? 0), color: wm.color.get(ym) || WATER })
      }
      out.set(w, [...by.entries()].sort((p, q) => p[0] - q[0]).map(e => e[1]))
    }
    return out
  }, [water, wm])
  const maxFlow = useMemo(() => Math.max(1, ...[...water.values()].flat().map(w => w.flow ?? 0)), [water])
  const usedMonths = useMemo(() => {
    const s = new Set<number>()
    win.months.forEach(m => m.forEach((v, i) => { if (v > 0) s.add(i) }))
    return win.order.filter(m => s.has(m))
  }, [win])

  useImperativeHandle(ref, () => ({
    fit: resetView,
    focus: (w: number) => {
      const p = placed.find(q => q.well === w)
      if (!p) return
      const k = 2.6
      setView({ k, tx: size.w / 2 - k * (fit.s * p.x + fit.ox), ty: size.h / 2 - k * (fit.s * p.y + fit.oy) })
    },
    toPng: async () => {
      const el = svg.current!
      const clone = el.cloneNode(true) as SVGSVGElement
      clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
      clone.setAttribute('width', String(size.w * 2)); clone.setAttribute('height', String(size.h * 2))
      clone.querySelectorAll('.no-export').forEach(n => n.remove())
      const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(clone))
      const img = new Image()
      await new Promise<void>((ok, fail) => { img.onload = () => ok(); img.onerror = () => fail(new Error('Не удалось собрать картинку')); img.src = url })
      const cv = document.createElement('canvas'); cv.width = size.w * 2; cv.height = size.h * 2
      cv.getContext('2d')!.drawImage(img, 0, 0)
      return await new Promise<Blob>((ok, fail) => cv.toBlob(bl => (bl ? ok(bl) : fail(new Error('Пустая картинка'))), 'image/png'))
    },
  }), [placed, size, fit.s, fit.ox, fit.oy, resetView])

  // колесо мыши — масштаб к курсору (слушатель не пассивный, чтобы страница не прокручивалась)
  useEffect(() => {
    const el = svg.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top
      setView(v => {
        const k = Math.max(0.4, Math.min(24, v.k * Math.exp(-e.deltaY * 0.0015)))
        return { k, tx: px - ((px - v.tx) / v.k) * k, ty: py - ((py - v.ty) / v.k) * k }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const themeKey = document.documentElement.dataset.theme || ''
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const pal = useMemo(readPal, [themeKey])
  const zoomBy = (f: number) => setView(v => {
    const px = size.w / 2, py = size.h / 2, k = Math.max(0.4, Math.min(24, v.k * f))
    return { k, tx: px - ((px - v.tx) / v.k) * k, ty: py - ((py - v.ty) / v.k) * k }
  })
  // месяцы окна: цвет по порядку внутри сезона (раньше — светлее)
  const monthColors = useMemo(() => {
    const c: string[] = Array(12).fill(pal.gas)
    const stops = themeKey === 'dark' ? SEASON_STOPS_DARK : SEASON_STOPS
    usedMonths.forEach((m, i) => { c[m] = rampColor(stops, usedMonths.length > 1 ? i / (usedMonths.length - 1) : 0.5) })
    return c
  }, [usedMonths, pal.gas, themeKey])

  const unit = g.layout.mode === 'xy' && !spread ? 'м' : ''
  const K = fit.s * view.k
  // изолинии показателя ГИС: только на карте в координатах (не на схеме с разнесёнными скважинами)
  // ГВК по всем скважинам модели: колонны модели в координатах карты (Y с минусом, как у кровли); исключённые — вне изолиний
  const awAll = useMemo((): AwPoint[] => (gis?.allWells.on && gis.allWells.data ? gis.allWells.data.points.map(p => ({ w: p.w, n: p.n, x: p.x, y: -p.y, v: awValue(p, gis.allWells.mode, gis.allWells.depth), torn: p.torn })) : []),
    [gis?.allWells.on, gis?.allWells.data, gis?.allWells.mode, gis?.allWells.depth])
  const awOk = useMemo(() => awAll.filter(p => !gis?.allWells.excl.has(p.w)), [awAll, gis?.allWells.excl])
  const awRad = Math.max((Number(gis?.iso.reach) || 1.5) * spacing, 1e-9)
  const awDev = useMemo(() => awDeviation(awOk, awRad), [awOk, awRad])
  const awOut = Math.max(0, Number(gis?.allWells.outlier) || 0)
  const awRes = useMemo(() => awResidual(awOk, gis?.allWells.fact ?? null), [awOk, gis?.allWells.fact])
  const awOutN = awOk.filter(p => !p.torn && awDev.has(p.w) && Math.abs(awDev.get(p.w) as number) > awOut).length
  const awTornN = awOk.filter(p => p.torn).length
  // несколько вариантов: изолинии каждого критерия своим цветом, подпись — вариант; исключения и способ/глубина — общие
  const awMultiIso = useMemo(() => {
    if (!gis?.allWells.on || !gis.allWells.multi || !gis.allWells.variants || gis.allWells.variantsBusy) return []
    const v = gis.allWells.variants.variants
    const all = v.flatMap(x => x.points.map(p => awValue(p, gis.allWells.mode, gis.allWells.depth)))
    if (!all.length) return []
    const step = Number(gis.iso.step) || niceLevelStep((Math.max(...all) - Math.min(...all)) || 1)
    return v.map((x, i) => {
      const pts = x.points.filter(p => !gis.allWells.excl.has(p.w)).map(p => ({ x: p.x, y: -p.y, v: awValue(p, gis.allWells.mode, gis.allWells.depth) }))
      const res = pts.length >= 3 ? isolines(pts, spacing, step, Number(gis.iso.reach) || 1.5) : null
      return { label: x.label, color: AW_COLORS[i % AW_COLORS.length], res }
    })
  }, [gis?.allWells.on, gis?.allWells.multi, gis?.allWells.variants, gis?.allWells.variantsBusy, gis?.allWells.mode, gis?.allWells.depth, gis?.allWells.excl, gis?.iso.step, gis?.iso.reach, spacing])
  // подписи уровней всех вариантов: жадно, пропуская подпись, если рядом (в пределах двух шагов сетки) уже стоит другая
  const awLabels = useMemo(() => {
    const kept: { x: number; y: number; t: string; c: string }[] = []
    for (const m of awMultiIso) for (const l of m.res?.lines ?? []) {
      const [x, y] = l.at
      if (kept.every(k => Math.hypot(k.x - x, k.y - y) >= spacing * 2)) kept.push({ x, y, t: fmt1(l.level), c: m.color })
    }
    return kept
  }, [awMultiIso, spacing])
  const awNote = !gis?.allWells.on ? '' : gis.allWells.err ? 'ГВК по всем скважинам не получен: ' + gis.allWells.err
    : !gis.allWells.data ? 'Выберите модель: точки строятся по колоннам всех скважин модели.'
    : [`Точек с газом ${awAll.length}, без газа ${gis.allWells.data.no_gas.length}, исключено ${awAll.length - awOk.length}. ${gis.allWells.data.criterion}; критическая величина из ${gis.allWells.data.sgr_source}.`,
      awRes.n ? `Невязка к ГИС (${awRes.n} скв.): медиана ${fmt1(awRes.median ?? 0)} м, средний модуль ${fmt1(awRes.mae ?? 0)} м.` : 'Невязки к ГИС нет: нет совпавших скважин или не выбран показатель ГВК.',
      `Подсказки: разрыв контакта ${awTornN}, резкий выброс ${awOutN}. Клик по скважине исключает её из изолиний.`].join(' ')
  // изолинии показателя ГИС: только на карте в координатах (не на схеме с разнесёнными скважинами)
  const obsPts = useMemo(() => (options.paint === 'gis' && gis && !spread ? shownFunds(gis.obs).filter(o => o.x !== undefined && o.y !== undefined) : []), [options.paint, gis?.obs.on, gis?.obs.geoOn, gis?.obs.data, spread])
  // точки значений для изолиний и контура: скважины карты со значением и наблюдательные (◆) и геофизические (▲) скважины ГИС, если они показаны
  const gisPts = useMemo(() => {
    const vals = gis?.paint?.vals
    if (!vals) return { pts: [] as { w: string; x: number; y: number; v: number }[], nVals: 0, nPlaced: 0, nObs: 0 }
    const pts = placed.filter(p => vals.has(p.well)).map(p => ({ w: String(p.well), x: p.x, y: p.y, v: vals.get(p.well)!.v }))
    const nPlaced = pts.length, have = new Set(pts.map(p => p.w))
    for (const o of obsPts) if (vals.has(o.well) && !have.has(String(o.well))) pts.push({ w: String(o.well), x: o.x!, y: -o.y!, v: vals.get(o.well)!.v })
    return { pts, nVals: vals.size, nPlaced, nObs: pts.length - nPlaced }
  }, [gis?.paint, placed, obsPts])
  const gisPtsNote = (n: number) => `Изолиний нет: из ${gisPts.nVals} скважин со значением на карте ${gisPts.nPlaced} эксплуатационных${gis?.obs.on || gis?.obs.geoOn ? ` и ${gisPts.nObs} наблюдательных и геофизических` : ' (наблюдательные и геофизические выключены: включите «Наблюдательные скважины (◆)» и «Геофизические скважины (▲)»)'}, всего ${n}, нужно не меньше трёх. Остальные скважины не на карте: выберите группу или «Весь объект» либо проверьте координаты.`
  const iso = useMemo((): IsoResult | null => {
    if (options.paint !== 'gis' || !gis?.iso.on) return null
    const note = (text: string): IsoResult => ({ lines: [], conf: [], step: 0, note: text })
    if (gis.allWells.on) {
      if (gis.allWells.multi) return note('Изолинии строятся по вариантам критерия (ниже подписаны цветом).')
      if (spread) return note('На схеме с разнесёнными скважинами изолинии не строятся: выключите «Разнести скважины».')
      if (awOk.length < 3) return note(`Изолиний нет: у модели после исключений ${awOk.length} скважин с газом (нужно не меньше трёх).`)
      const vs = awOk.map(p => p.v)
      const step = Number(gis.iso.step) || niceLevelStep((Math.max(...vs) - Math.min(...vs)) || 1)
      try {
        return isolines(awOk.map(p => ({ x: p.x, y: p.y, v: p.v })), spacing, step, Number(gis.iso.reach) || 1.5)
      } catch (e) {
        return note('Изолинии не построены из-за ошибки: ' + String((e as Error)?.message || e))
      }
    }
    if (!gis.paint) return note('Изолиний нет: для выбранной пачки, показателя и сезона нет значений по скважинам.')
    if (spread) return note('На схеме с разнесёнными скважинами изолинии не строятся: выключите «Разнести скважины».')
    try {
      const pts = gisPts.pts
      if (pts.length < 3) return note(gisPtsNote(pts.length))
      const vs = pts.map(p => p.v)
      const step = Number(gis.iso.step) || niceLevelStep((Math.max(...vs) - Math.min(...vs)) || 1)
      return isolines(pts, spacing, step, Number(gis.iso.reach) || 1.5)
    } catch (e) {
      return note('Изолинии не построены из-за ошибки: ' + String((e as Error)?.message || e))
    }
  }, [options.paint, gis?.iso.on, gis?.iso.step, gis?.iso.reach, gis?.paint, gis?.allWells.on, awOk, gisPts, spacing, spread])
  // изолинии кровли из модели: тонкие линии под скважинами, шаг подбирается или задаётся; любой исход объясняется на экране
  const roofRes = useMemo((): { lines: ReturnType<typeof contourLines> | null; fill: { d: string; c: string }[]; step: number; warn: string } => {
    const r0 = gis?.roof.grid
    if (options.paint !== 'gis' || !gis?.roof.on || !r0) return { lines: null, fill: [], step: 0, warn: '' }
    const r = fillRoofGaps(r0)
    try {
      const v = Array.from(r.z).filter(Number.isFinite)
      if (!v.length) return { lines: null, fill: [], step: 0, warn: 'Кровля: в выбранном слое нет ячеек — укажите другой слой.' }
      const lo = Math.min(...v), hi = Math.max(...v)
      const rx1 = r.x0 + (r.nx - 1) * r.dx, ry1 = r.y0 + (r.ny - 1) * r.dy
      const wx = placed.map(p => p.x), wy = placed.map(p => p.y)
      let warn = ''
      if (placed.length && (Math.max(...wx) < r.x0 - r.dx || Math.min(...wx) > rx1 + r.dx || Math.max(...wy) < r.y0 - r.dy || Math.min(...wy) > ry1 + r.dy)) {
        warn = `Кровля лежит вне карты скважин: модель X ${Math.round(r.x0)}…${Math.round(rx1)}, Y ${Math.round(-ry1)}…${Math.round(-r.y0)}; скважины X ${Math.round(Math.min(...wx))}…${Math.round(Math.max(...wx))}, Y ${Math.round(-Math.max(...wy))}…${Math.round(-Math.min(...wy))}. Координаты скважин и сетки модели в разных системах (проверьте MAPAXES и источник XY).`
      } else if (g.layout.mode !== 'xy') warn = 'Скважины стоят по сетке листа Excel, а не по координатам XY: кровля модели не совместится с ними. Загрузите координаты tNavigator в Атласе.'
      const step = Number(gis.roof.step) || niceLevelStep((hi - lo) || 1)
      const lines = contourLines(r.z, r.nx, r.ny, r.x0, r.y0, r.dx, r.dy, step, lo, hi)
      if (!warn && !lines.length) warn = `Кровля построена, но изолиний нет: отметки ${fmt1(lo)}…${fmt1(hi)} м почти не меняются при шаге ${step} м — уменьшите шаг или выберите другой слой.`
      // заливка по глубине: чем глубже кровля, тем синее; 24 ступени цвета, ячейки одной ступени — один путь
      const bands: string[] = new Array(24).fill('')
      for (let j = 0; j < r.ny; j++) for (let i = 0; i < r.nx; i++) {
        const z = r.z[j * r.nx + i]
        if (!Number.isFinite(z)) continue
        const b = Math.min(23, Math.floor(((z - lo) / ((hi - lo) || 1)) * 24))
        bands[b] += `M${(r.x0 + (i - 0.5) * r.dx).toFixed(1)} ${(r.y0 + (j - 0.5) * r.dy).toFixed(1)}h${r.dx.toFixed(1)}v${r.dy.toFixed(1)}h${(-r.dx).toFixed(1)}z`
      }
      const fill = bands.map((d, b) => ({ d, c: rampColor(ROOF_STOPS, (b + 0.5) / 24) })).filter(x => x.d)
      return { lines, fill, step, warn }
    } catch (e) {
      return { lines: null, fill: [], step: 0, warn: 'Кровля не нарисована из-за ошибки: ' + String((e as Error)?.message || e) }
    }
  }, [options.paint, gis?.roof.on, gis?.roof.step, gis?.roof.grid, placed, g.layout.mode])
  const roofLines = roofRes.lines
  // контур ГВК по кровле: только для значений ГВК (факт ГИС без сравнения сезонов или ГВК модели)
  const gwc = useMemo(() => {
    if (options.paint !== 'gis' || !gis?.gwc.on || !gis.roof.on) return null
    const r = gis.roof.grid
    const miss = (note: string) => ({ d: '', at: null, note, surface: '', shares: [] as GwcUnified['shares'], excluded: [] as string[] })
    if (!r) return miss('Нужна кровля из модели: включите её и выберите модель и слой.')
    if (gis.allWells.on && gis.allWells.multi) return miss('Контуры вариантов критерия показаны каждый своим цветом (список вариантов ниже).')
    if (!gis.allWells.on && (gis.source === 'delta' || (gis.source === 'fact' && (gis.metric !== 'gvk_abs_m' || gis.against)))) return miss('Контур строится по значениям ГВК: выберите показатель «ГВК, м а.о.» без сравнения сезонов или «ГВК модели».')
    if (spread) return miss('На схеме с разнесёнными скважинами контур не строится.')
    if (!gis.allWells.on && !gisPts.pts.length) return miss(`Контур не построен: ${gisPtsNote(0).replace('Изолиний нет: ', '').replace(', нужно не меньше трёх', '')}`)
    if (gis.gwc.mode === 'unified') {
      if (gis.allWells.on) {
        const res = gwcUnified(awOk.map(p => ({ w: p.w, x: p.x, y: p.y, v: p.v })), r, spacing, gis.gwc.par)
        return { ...res, note: res.note || `${res.surface}. Линий: ${res.closed} замкнутых${res.open ? `, ${res.open} незамкнутых` : ''}. Точки — все скважины модели; исключить скважину — клик по ней на карте.`, shares: [] as GwcUnified['shares'], excluded: [] as string[] }
      }
      const all = gisPts.pts
      const res = gwcUnified(all.filter(p => !gis.gwc.excl.has(p.w)), r, spacing, gis.gwc.par)
      return { ...res, note: res.note || `${res.surface}. Линий: ${res.closed} замкнутых${res.open ? `, ${res.open} незамкнутых (упираются в край кровли)` : ''}.`, shares: res.shares, excluded: all.filter(p => gis.gwc.excl.has(p.w)).map(p => p.w) }
    }
    const pts = gisPts.pts
    const res = gwcContour(pts, r, spacing, Number(gis.iso.reach) || 1.5, gis.gwc.mode)
    return { ...res, note: res.note || res.surface + '.', shares: [] as GwcUnified['shares'], excluded: [] as string[] }
  }, [options.paint, gis?.gwc.on, gis?.gwc.mode, gis?.gwc.par, gis?.gwc.excl, gis?.allWells.on, gis?.allWells.multi, awOk, gis?.roof.on, gis?.roof.grid, gis?.source, gis?.metric, gis?.against, gis?.paint, gis?.iso.reach, gisPts, spacing, spread])
  // варианты критерия: единый контур каждого варианта своим цветом (те же цвета, что у изолиний вариантов)
  const gwcMulti = useMemo(() => {
    if (options.paint !== 'gis' || !gis?.gwc.on || !gis.roof.on || !gis.roof.grid || spread || gis.gwc.mode !== 'unified' || !gis.allWells.on || !gis.allWells.multi || !gis.allWells.variants || gis.allWells.variantsBusy) return []
    const r = gis.roof.grid
    return gis.allWells.variants.variants.map((x, i) => {
      const pts = x.points.filter(p => !gis.allWells.excl.has(p.w)).map(p => ({ w: p.w, x: p.x, y: -p.y, v: awValue(p, gis.allWells.mode, gis.allWells.depth) }))
      return { label: x.label, color: AW_COLORS[i % AW_COLORS.length], res: gwcUnified(pts, r, spacing, gis.gwc.par) }
    })
  }, [options.paint, gis?.gwc.on, gis?.gwc.mode, gis?.gwc.par, gis?.roof.on, gis?.roof.grid, gis?.allWells.on, gis?.allWells.multi, gis?.allWells.variants, gis?.allWells.variantsBusy, gis?.allWells.mode, gis?.allWells.depth, gis?.allWells.excl, spread, spacing])
  const gwcWarn = gwc && !gwc.d ? gwc.note : ''
  useEffect(() => { if (gwcWarn) reportIssue('контур ГВК', gwcWarn) }, [gwcWarn])
  const roofWarn = roofRes.warn
  // то, что на экране «ничего нет», пишется и в лог программы
  useEffect(() => { if (roofWarn) reportIssue('кровля', roofWarn) }, [roofWarn])
  const isoWarn = iso && !iso.lines.length ? iso.note : ''
  useEffect(() => { if (isoWarn) reportIssue('изолинии ГИС и ГВК', isoWarn) }, [isoWarn])
  const sx = (mx: number) => view.k * (fit.s * mx + fit.ox) + view.tx, sy = (my: number) => view.k * (fit.s * my + fit.oy) + view.ty
  const bar = niceStep(140 / K)
  // в режиме группировки круги имеют постоянный размер на экране (как значки на веб-картах), поэтому при приближении близкие скважины расходятся
  const clusterPref = usePref(clusterWells)
  const isRef = options.paint === 'ref'
  const useCluster = clusterPref && !isRef
  const refList = usePref(refWells), refK = usePref(refSize)
  const refNums = useMemo(() => parseRefWells(refList), [refList])
  const paints = useMemo(() => {
    if (!paintData) return null
    const m = new Map<number, { color: string; label: string }>()
    paintData.vals.forEach((v, well) => m.set(well, { color: rampColor(paintData.stops, (v.v - paintData.lo) / (paintData.hi - paintData.lo)), label: v.label }))
    return m
  }, [paintData])
  const groupsOn = usePref(groupColoring)
  const multiG = !!g.groups && g.groups.length > 1
  const byGroup = multiG && groupsOn
  const gcol = (well: number) => (byGroup ? groupColor(g.groupOf![String(well)]) : undefined)
  const rpx0 = Math.max(12, Math.min(22, rmax * fit.s))
  const rd = useCluster ? rpx0 / K : rmax
  const items = useMemo(() => {
    const vis: number[] = []
    placed.forEach((q, n) => {
      const t = win.stats[n].total
      const hidden = !paintData && !isRef && ((options.hideIdle && !(t > 0)) || (options.minValue > 0 && t < options.minValue * 1e6))
      if (!hidden || selected === q.well || group.includes(q.well)) vis.push(n)
    })
    vis.sort((u, v) => win.stats[v].total - win.stats[u].total)
    type Cl = { id: number; x: number; y: number; idx: number[]; total: number }
    const out: { single?: number; cl?: Cl }[] = []
    if (!useCluster || view.k >= 10) { vis.forEach(n => out.push({ single: n })); return out }
    const thr = 2.2 * rd * options.scale, cell = thr
    const grid = new Map<string, number[]>()
    const key = (x: number, y: number) => Math.floor(x / cell) + ',' + Math.floor(y / cell)
    const taken = new Set<number>()
    const pinned = (n: number) => selected === placed[n].well || group.includes(placed[n].well)
    vis.forEach(n => { const k = key(placed[n].x, placed[n].y); const a = grid.get(k); if (a) a.push(n); else grid.set(k, [n]) })
    let id = 0
    for (const n of vis) {
      if (taken.has(n)) continue
      taken.add(n)
      if (pinned(n)) { out.push({ single: n }); continue }
      const q = placed[n], gx = Math.floor(q.x / cell), gy = Math.floor(q.y / cell), mem = [n]
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (const o of grid.get((gx + dx) + ',' + (gy + dy)) || []) {
        if (taken.has(o) || pinned(o)) continue
        if (Math.hypot(placed[o].x - q.x, placed[o].y - q.y) < thr) { taken.add(o); mem.push(o) }
      }
      if (mem.length === 1) { out.push({ single: n }); continue }
      let sw = 0, cx = 0, cy = 0, total = 0
      for (const o of mem) { const w = Math.max(win.stats[o].total, 1); sw += w; cx += placed[o].x * w; cy += placed[o].y * w; total += Math.max(win.stats[o].total, 0) }
      out.push({ cl: { id: id++, x: cx / sw, y: cy / sw, idx: mem, total } })
    }
    return out
  }, [placed, win, paintData, isRef, options.hideIdle, options.minValue, options.scale, selected, group, useCluster, view.k, rd])
  const zoomTo = (idx: number[]) => {
    const xs = idx.map(n => placed[n].x), ys = idx.map(n => placed[n].y)
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
    const w = Math.max((x1 - x0) * fit.s, 1), h = Math.max((y1 - y0) * fit.s, 1)
    const k = Math.max(view.k * 1.7, Math.min(24, (size.w * 0.55) / w, (size.h * 0.55) / h))
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2
    setView({ k: Math.min(24, k), tx: size.w / 2 - Math.min(24, k) * (fit.s * cx + fit.ox), ty: size.h / 2 - Math.min(24, k) * (fit.s * cy + fit.oy) })
  }
  const clustersRef = useRef<number[][]>([])
  // координатная сетка (только для настоящих координат XY)
  const gridOn = usePref(mapGrid)
  // многоугольники из файла: контур в координатах карты (Y отражён, как у скважин), маркеры по вершинам
  const polyData = usePolygons()
  const polyOver = usePref(polyStyles)
  const alignPts = usePref(polyAlign)
  const align = useMemo(() => alignTransform(alignPts, placed), [alignPts, placed])
  // фото или растр на фон: показываем, только когда привязка по трём точкам задана
  const bgPts = usePref(bgAlign), bgOn = usePref(bgShow), bgOp = usePref(bgOpacity), bgUrl = useBgUrl()
  const bgT = useMemo(() => alignTransform(bgPts, placed).t, [bgPts, placed])
  const polyShown = useMemo(() => {
    const T = align.t
    return polyData.polys.map((p, i) => ({ p, st: styleOf(p.name, i, polyOver) })).filter(x => x.st.show)
      .map(x => ({ ...x, xy: x.p.pts.map(([X, Y]) => (T ? applyAffine(T, X, Y) : applyAffine(FLIP_Y, X, Y))) }))
  }, [polyData.polys, polyOver, align])
  const grid = useMemo(() => {
    if (!gridOn || !unit || !placed.length) return null
    const mx0 = ((0 - view.tx) / view.k - fit.ox) / fit.s, mx1 = ((size.w - view.tx) / view.k - fit.ox) / fit.s
    const my0 = ((0 - view.ty) / view.k - fit.oy) / fit.s, my1 = ((size.h - view.ty) / view.k - fit.oy) / fit.s
    const st = niceStep(Math.max(mx1 - mx0, my1 - my0), 7)
    const xs: number[] = [], ys: number[] = []
    for (let v = Math.ceil(mx0 / st) * st; v <= mx1; v += st) xs.push(v)
    for (let v = Math.ceil(my0 / st) * st; v <= my1; v += st) ys.push(v)
    return { xs, ys }
  }, [gridOn, unit, placed.length, view, fit.s, fit.ox, fit.oy, size])
  // «пятно» месторождения: объединение мягких кругов вокруг скважин
  const halo = useCluster ? rd * 1.7 : Math.max(rmax * 1.5, spacing * 0.9)

  // легенда размеров: вложенные круги того же масштаба, что на карте (не крупнее 30 px)
  const Rpx = rd * options.scale * K
  const vTop = (() => {
    const raw = win.scaleMax * Math.min(1, (30 / Math.max(Rpx, 1e-6)) ** 2), q = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / q
    return (f >= 5 ? 5 : f >= 2 ? 2 : 1) * q
  })()
  const refs = [1, 0.4, 0.1].map(f => ({ v: vTop * f, r: Math.max(2.5, Rpx * Math.sqrt((vTop * f) / win.scaleMax)) }))
  const R0 = refs[0].r
  // подписи легенды не налезают друг на друга: не ближе 14 px по вертикали
  const labY: number[] = []
  refs.forEach((c, i) => { const want = 34 + 2 * R0 - 2 * c.r; labY.push(i ? Math.max(want, labY[i - 1] + 14) : want) })
  const sizeH = Math.max(2 * R0, labY[labY.length - 1] - 34 + 6)
  // по умолчанию легенда маленькая: только размеры кругов; месяцы и вода раскрываются по кнопке
  const legendExpanded = usePref(legendOpen)
  const small = !!compact || !legendExpanded
  const LW = paintData ? 270 : small ? 124 : 248
  const legH = 46 + sizeH + (!paintData && !small && !byGroup && usedMonths.length > 1 ? 44 : 0) + (!paintData && !small && options.water ? (wm.list.length > 1 ? 52 : 26) : 0)
  // без наведения подсказка остаётся на выбранной скважине (только в панели); при наведении следует за курсором
  const tipId = tip ? tip.well : stickyTip && selected !== null ? selected : null
  const tipWell = tipId !== null ? placed.find(q => q.well === tipId) : null
  const tipIdx = tipWell ? placed.indexOf(tipWell) : -1
  const [t1, t2] = [title.split(' · ').slice(0, 2).join(' · '), paintData?.scopeNote || title.split(' · ')[2] || '']

  // опорные скважины по группам (для легенды) и те из списка, которых нет на карте
  const refInfo = useMemo(() => {
    if (!isRef) return { groups: [] as { name: string; wells: number[] }[], missing: [] as number[] }
    const onMap = new Set(placed.map(q => q.well)), by = new Map<string, number[]>(), missing: number[] = []
    for (const w of refNums) { if (!onMap.has(w)) { missing.push(w); continue } const gn = g.groupOf?.[String(w)] || g.gsp; by.set(gn, [...(by.get(gn) || []), w]) }
    return { groups: sortLabels([...by.entries()], e => e[0]).map(([name, wells]) => ({ name, wells })), missing }
  }, [isRef, refNums, placed, g])

  const layer = useMemo(() => {
    clustersRef.current = items.filter(it => it.cl).map(it => it.cl!.idx)
    if (isRef) {
      const set = new Set(refNums), mk = (n: number, big: boolean) => { const q = placed[n]; return <RefGlyph key={q.well} well={q.well} x={q.x} y={q.y} r={big ? rd * 0.5 * refK : rd * 0.2} color={big ? groupColor(g.groupOf?.[String(q.well)] || g.gsp) : undefined} label={String(q.well)} selected={selected === q.well || group.includes(q.well)} hot={tip?.well === q.well} pal={pal} /> }
      return <>{placed.map((q, n) => (set.has(q.well) ? null : mk(n, false)))}{placed.map((q, n) => (set.has(q.well) ? mk(n, true) : null))}</>
    }
    return (
      <>
        {items.map(it => {
              if (it.cl) {
                const c = it.cl
                let ci = 0
                const rr = rd * options.scale * Math.min(1.9, 1 + 0.22 * Math.log2(c.idx.length))
                let fill = pal.gas, ringC: string | undefined
                const cnt = new Map<string, number>()
                if (byGroup) { for (const n of c.idx) { const gn = g.groupOf![String(placed[n].well)]; cnt.set(gn, (cnt.get(gn) || 0) + 1) } const top = [...cnt.entries()].sort((u, v) => v[1] - u[1])[0]; ringC = groupColor(top[0]); fill = ringC }
                if (paintData) {
                  const vs = c.idx.map(n => paintData.vals.get(placed[n].well)?.v).filter((v): v is number => v !== undefined)
                  fill = vs.length ? rampColor(paintData.stops, (vs.reduce((p2, q2) => p2 + q2, 0) / vs.length - paintData.lo) / (paintData.hi - paintData.lo)) : pal.muted
                }
                const wet = c.idx.filter(n => (water.get(placed[n].well) || []).some(w => (w.flow ?? 0) > 0)).length
                const title = `${c.idx.length} скв. рядом: ${fmtMln(c.total)} млн м³` + (win.sumAll > 0 ? ` (${fmtPct(c.total / win.sumAll)})` : '') + (wet ? `, с водой: ${wet}` : '') + (byGroup ? ' · ' + [...cnt.entries()].sort((u, v) => v[1] - u[1]).map(e => e[0] + ': ' + e[1]).join(', ') : '') + ' · нажмите или приблизьте карту'
                ci = clustersRef.current.findIndex(x => x === c.idx)
                return <ClusterGlyph key={'c' + c.idx.map(n => placed[n].well).join('-')} id={ci} x={c.x} y={c.y} r={rr} rd={rd} count={c.idx.length} fill={fill} ring={paintData ? ringC : undefined} title={title} pal={pal} />
              }
              const n = it.single!, q = placed[n]
              return (
              <Glyph key={q.well} well={q.well} x={q.x} y={q.y} rmax={rd} total={win.stats[n].total} pal={pal}
                r={win.stats[n].total > 0 ? Math.max(rd * 0.45 * options.scale, rd * options.scale * Math.sqrt(win.stats[n].total / win.scaleMax)) : rd * 0.25}
                share={win.stats[n].total > 0 ? win.stats[n].total / win.sumAll : 0}
                months={win.months[n] || EMPTY} order={win.order} monthColors={monthColors} sectors={options.sectors === 'months'}
                paint={paints ? paints.get(q.well) ?? null : undefined}
                water={options.water ? rings.get(q.well) || EMPTY : EMPTY} maxFlow={maxFlow} showShare={options.share}
                selected={selected === q.well || group.includes(q.well)} dim={false} hot={tip?.well === q.well} gcolor={gcol(q.well)} label={options.labels === 'none' ? '' : options.labels === 'val' && win.stats[n].total > 0 ? fmtMln(win.stats[n].total) : String(q.well)} />
              )
            })}
      </>
    )
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, rd, isRef, refNums, refK, options, paintData, paints, win, rings, water, maxFlow, monthColors, pal, selected, group, byGroup, g, placed, tip?.well])
  // наблюдательные (ромб) и геофизические (треугольник) скважины вне групп: в координатах карты; при «схеме» положения условные, поэтому они не рисуются
  const obsLayer = obsPts.length ? <g aria-label="Наблюдательные и геофизические скважины">
    {obsPts.map(o => {
      const pv = paintData?.vals.get(o.well), r = rd * 0.5, x = o.x!, y = -o.y!, geo = o.fund === 'geophysical'
      const fill = pv && paintData ? rampColor(paintData.stops, (pv.v - paintData.lo) / (paintData.hi - paintData.lo)) : pal.surface
      return <g key={o.well}>
        <path d={geo ? `M${x},${y - r}L${x + r},${y + r * 0.8}L${x - r},${y + r * 0.8}Z` : `M${x},${y - r}L${x + r},${y}L${x},${y + r}L${x - r},${y}Z`} fill={fill} stroke={pal.ink} strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
        <text x={x} y={y - r - 3 / K} fontSize={10 / K} textAnchor="middle" fill={pal.ink} stroke={pal.bg} strokeWidth={3 / K} paintOrder="stroke">{o.well}{pv ? ' · ' + pv.label : ''}</text>
        <title>{`${geo ? 'Геофизическая' : 'Наблюдательная'} скважина ${o.well} (${o.why.join(', ')}${o.manual ? ', решение инженера' : ''})${pv ? '\n' + pv.tip : '\nНет данных ГИС для этой раскраски'}`}</title>
      </g>
    })}
  </g> : null
  const tipNode = useMemo(() => {
    if (!tipWell) return null
        const st = win.stats[tipIdx], share = st.total > 0 && win.sumAll > 0 ? st.total / win.sumAll : 0
        const row = calc.flow[calc.index.get(tipWell.well) ?? 0] || []
        const ws = water.get(tipWell.well) || []
        const W = 252, fp = fpos || { x: Math.max(8, size.w - W - 14), y: 64 }
        const node = (
          <div className={'tip' + (tipHost ? ' docked' : '')} style={tipHost ? undefined : { left: Math.max(0, Math.min(fp.x, size.w - W)), top: Math.max(0, Math.min(fp.y, size.h - 120)) }}>
            {tipTag && <div className="tip-tag">{tipTag}</div>}
            <div className={'tip-head' + (tipHost ? '' : ' grab')} title={tipHost ? undefined : 'Потяните, чтобы перенести подсказку'}
              onPointerDown={tipHost ? undefined : e => {
                e.preventDefault()
                const el = e.currentTarget, x0 = e.clientX, y0 = e.clientY, p0 = fp
                el.setPointerCapture(e.pointerId)
                const move = (ev: PointerEvent) => setFpos({ x: p0.x + ev.clientX - x0, y: p0.y + ev.clientY - y0 })
                const up = () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up) }
                el.addEventListener('pointermove', move); el.addEventListener('pointerup', up)
              }}><b>№ {tipWell.well}</b>{tipWell.dir && <span className="tip-dir">{tipWell.dir}</span>}{multiG && g.groupOf?.[String(tipWell.well)] && <span className="tip-dir">{g.groupOf[String(tipWell.well)]}</span>}</div>
            {paintData && <div className="tip-paint"><i style={{ background: paintData.vals.has(tipWell.well) ? rampColor(paintData.stops, (paintData.vals.get(tipWell.well)!.v - paintData.lo) / (paintData.hi - paintData.lo)) : 'transparent' }} />{paintData.vals.get(tipWell.well)?.tip || 'Нет данных для этой раскраски'}</div>}
            <div className="tip-hero">{st.total > 0 ? fmtMln(st.total) : '0'}<small> млн м³ за окно</small></div>
            <div className="tip-share"><span><i style={{ width: Math.min(100, share * 100 * 4) + '%' }} /></span>{share > 0 ? fmtPct(share) + ' ГСП' : 'не работала'}</div>
            <Chart days={calc.days} mode="bars" win={[a, b]} compact interactive fmt={fmtTh} unit="тыс. м³/сут" height={104} label="Суточный расход скважины"
              series={[{ key: 'd', label: 'Расход', color: pal.gas, y: row.map(v => Math.max(0, v)) }]} />
            <div className="tip-kpis"><div><span>в среднем</span><b>{fmtTh(st.mean)}</b><small>тыс. м³/сут</small></div><div><span>дней с расходом</span><b>{st.days}</b><small>из {b - a + 1}</small></div></div>
            {ws.length > 0 && <div className="tip-water">{ws.map((w, i) => (
              <div key={i}><i style={{ background: wm.color.get(w.year * 12 + w.month) }} />{MONTH_NAME[w.month]} {w.year}<span>{w.note !== 'Ок' ? w.note : fmt1(w.flow ?? 0) + ' л/ч · ВФ ' + Math.round(w.factor ?? 0)}</span></div>))}</div>}
          </div>
        )
        return node
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tipWell, tipIdx, win, calc, water, paintData, pal, a, b, fpos, size.w, size.h, tipHost, tipTag, multiG, g, wm])

  return (
    <div className="map-wrap" ref={wrap}>
      <svg ref={svg} width="100%" height="100%" viewBox={`0 0 ${size.w} ${size.h}`} fontFamily="'PT Sans','Segoe UI',sans-serif"
        onPointerDown={e => {
          const r = wrap.current!.getBoundingClientRect(), bx = e.clientX - r.left, by = e.clientY - r.top
          drag.current = { x: e.clientX, y: e.clientY, moved: false, box: e.shiftKey, x0: bx, y0: by };
          (e.currentTarget as Element).setPointerCapture(e.pointerId)
        }}
        onPointerMove={e => {
          const d = drag.current
          if (d) {
            const dx = e.clientX - d.x, dy = e.clientY - d.y
            if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true
            if (d.moved && d.box) { const r = wrap.current!.getBoundingClientRect(); setBox({ x0: d.x0!, y0: d.y0!, x1: e.clientX - r.left, y1: e.clientY - r.top }); setTip(null) }
            else if (d.moved) {
              d.x = e.clientX; d.y = e.clientY
              panAcc.current.x += dx; panAcc.current.y += dy
              if (!panRaf.current) panRaf.current = requestAnimationFrame(() => {
                panRaf.current = 0
                const { x, y } = panAcc.current; panAcc.current = { x: 0, y: 0 }
                setView(v => ({ ...v, tx: v.tx + x, ty: v.ty + y }))
              })
              setTip(t => (t ? null : t))
            }
          } else {
            const t = (e.target as Element).closest('[data-well]')
            if (t) {
              const r = wrap.current!.getBoundingClientRect(), well = Number(t.getAttribute('data-well')), x = e.clientX - r.left, y = e.clientY - r.top
              setTip(p => (p && p.well === well ? p : { x, y, well }))
            } else setTip(p => (p ? null : p))
          }
        }}
        onPointerUp={e => {
          const d = drag.current, moved = d?.moved
          drag.current = null
          if (moved && d?.box && box) {
            const xa = Math.min(box.x0, box.x1), xb = Math.max(box.x0, box.x1), ya = Math.min(box.y0, box.y1), yb = Math.max(box.y0, box.y1)
            const inside = placed.filter(q => { const X = sx(q.x), Y = sy(q.y); return X >= xa && X <= xb && Y >= ya && Y <= yb }).map(q => q.well)
            const base = e.ctrlKey || e.metaKey ? group : []
            onGroup(Array.from(new Set([...base, ...inside])))
            if (inside.length === 1 && !base.length) onSelect(inside[0])
          } else if (!moved) {
            const hit = document.elementFromPoint(e.clientX, e.clientY)
            const cl = hit?.closest('[data-cluster]')
            if (cl) { const idx = clustersRef.current[Number(cl.getAttribute('data-cluster'))]; if (idx) zoomTo(idx); setBox(null); return }
            const t = hit?.closest('[data-well]')
            const w = t ? Number(t.getAttribute('data-well')) : null
            if (w !== null && (e.ctrlKey || e.metaKey || e.shiftKey)) {
              const cur = group.length ? group : selected !== null ? [selected] : []
              onGroup(cur.includes(w) ? cur.filter(x => x !== w) : [...cur, w])
            } else onSelect(w)
          }
          setBox(null)
        }}
        onPointerLeave={() => setTip(null)}>
        <defs>
          <filter id="mapShadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="4" floodColor="#0b1418" floodOpacity="0.14" /></filter>
        </defs>
        <rect width={size.w} height={size.h} fill={pal.bg} className="map-bg" />
        {grid && <g className="map-grid">
          {grid.xs.map(v => <line key={'x' + v} x1={sx(v)} x2={sx(v)} y1={0} y2={size.h} stroke={pal.grid} strokeWidth={1} />)}
          {grid.ys.map(v => <line key={'y' + v} y1={sy(v)} y2={sy(v)} x1={0} x2={size.w} stroke={pal.grid} strokeWidth={1} />)}
          {grid.xs.filter(v => sx(v) > LW + 30 && sx(v) < size.w - 120).map(v => <text key={'tx' + v} x={sx(v) + 4} y={size.h - 6} fontSize={10} fill={pal.muted} opacity={0.75}>{niceCoord(v)}</text>)}
          {grid.ys.filter(v => sy(v) > 70 && sy(v) < size.h - 150).map(v => <text key={'ty' + v} x={size.w - 6} y={sy(v) - 4} fontSize={10} fill={pal.muted} opacity={0.75} textAnchor="end">{niceCoord(-v)}</text>)}
        </g>}
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
          <g transform={`translate(${fit.ox} ${fit.oy}) scale(${fit.s})`}>
            {bgT && bgOn && <image href={bgUrl} transform={`matrix(${bgT.a} ${bgT.d} ${bgT.b} ${bgT.e} ${bgT.c} ${bgT.f})`} opacity={bgOp} pointerEvents="none" />}
            <g opacity={0.07} fill={pal.accent}>{placed.map(q => <circle key={q.well} cx={q.x} cy={q.y} r={halo} />)}</g>
            {polyShown.length > 0 && <g aria-label="Многоугольники" pointerEvents="none">
              {polyShown.map(({ p, st, xy }) => { const K0 = Math.max(K, 1e-9); return <g key={p.name}>
                <path d={'M' + xy.map(([x, y]) => `${x},${y}`).join('L') + 'Z'} fill={st.fill} fillOpacity={st.fillOpacity} stroke={st.stroke} strokeWidth={st.width} strokeDasharray={st.dash ? '6 4' : undefined} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                {st.marker !== 'none' && xy.map(([X, Y], j) => { const r = st.markerSize / K0
                  return st.marker === 'circle' ? <circle key={j} cx={X} cy={Y} r={r} fill={st.markerColor} />
                    : st.marker === 'square' ? <rect key={j} x={X - r} y={Y - r} width={2 * r} height={2 * r} fill={st.markerColor} />
                    : <path key={j} d={`M${X - r},${Y}H${X + r}M${X},${Y - r}V${Y + r}`} stroke={st.markerColor} strokeWidth={2} vectorEffect="non-scaling-stroke" /> })}
              </g> })}
            </g>}
            {roofLines && <g aria-label="Кровля пласта">
              {roofRes.fill.map((f, k) => <path key={'f' + k} d={f.d} fill={f.c} opacity={0.55} stroke={f.c} strokeWidth={0.6} vectorEffect="non-scaling-stroke" />)}
              {roofLines.map(l => { const idx = Math.round(l.level / (roofRes.step || 1)) % 5 === 0; return <g key={l.level}><path d={l.d} fill="none" stroke={pal.ink} strokeWidth={idx ? 1.7 : 1} opacity={idx ? 0.85 : 0.55} vectorEffect="non-scaling-stroke" />
                <text x={l.at[0]} y={l.at[1]} fontSize={(idx ? 12 : 11) / K} fontWeight={idx ? 700 : 500} textAnchor="middle" fill={pal.ink} stroke={pal.bg} strokeWidth={3 / K} paintOrder="stroke">{fmt1(l.level)}</text></g> })}
            </g>}
            {gwc?.d && <g aria-label="Контур ГВК по кровле">
              {gis?.gwc.mode === 'unified' && <path d={gwc.d} fill="none" stroke={pal.bg} strokeWidth={6} strokeLinejoin="round" opacity={0.85} vectorEffect="non-scaling-stroke" />}
              <path d={gwc.d} fill="none" stroke={gis?.gwc.mode === 'unified' ? '#d9480f' : pal.accent} strokeWidth={3} strokeDasharray={gis?.gwc.mode === 'unified' ? undefined : '7 4'} strokeLinejoin="round" vectorEffect="non-scaling-stroke" strokeLinecap="round" />
              {gwc.shares.length > 0 && gwc.shares.map(s => { const q = placed.find(z => String(z.well) === s.w); return q && s.share >= 0.03 ? <circle key={s.w} cx={q.x} cy={q.y} r={halo * (0.5 + 2.5 * Math.sqrt(s.share))} fill="none" stroke={pal.accent} strokeWidth={1.4} opacity={0.9} vectorEffect="non-scaling-stroke"><title>{`Скв. ${s.w}: вклад в контур ${(s.share * 100).toFixed(0)}%`}</title></circle> : null })}
              {gwc.at && <text x={gwc.at[0]} y={gwc.at[1]} fontSize={12 / K} fontWeight={700} textAnchor="middle" fill={gis?.gwc.mode === 'unified' ? '#d9480f' : pal.accent} stroke={pal.bg} strokeWidth={3.5 / K} paintOrder="stroke">ГВК</text>}
            </g>}
            {iso && <g aria-label="Изолинии">
              {iso.conf.map((c, i) => <path key={'c' + i} d={c.d} fill={pal.accent} opacity={c.a} stroke="none" />)}
              {iso.lines.map(l => <g key={l.level}><path d={l.d} fill="none" stroke={pal.ink} strokeWidth={1.4} vectorEffect="non-scaling-stroke" strokeLinecap="round" />
                <text x={l.at[0]} y={l.at[1]} fontSize={11 / K} textAnchor="middle" fill={pal.ink} stroke={pal.bg} strokeWidth={3 / K} paintOrder="stroke">{fmt1(l.level)}</text></g>)}
            </g>}
            {gis?.allWells.on && awAll.length > 0 && <g aria-label="Скважины модели с ГВК">
              {awAll.map(p => {
                const ex = gis.allWells.excl.has(p.w), dev = awDev.get(p.w), bad = !ex && (p.torn || (dev !== undefined && Math.abs(dev) > awOut))
                const tag = ex ? ' · исключена' : p.torn ? ' · разрыв контакта' : dev !== undefined && bad ? ` · ${dev > 0 ? '+' : ''}${fmt1(dev)} м от соседей` : ''
                return <g key={p.w} style={{ cursor: 'pointer' }} onClick={e => { e.stopPropagation(); gis.onChange({ awToggle: p.w }) }}>
                  <title>{`${p.w}: ${fmt1(p.v)} м${tag}. Клик — исключить или вернуть`}</title>
                  <circle cx={p.x} cy={p.y} r={4 / K} fill={ex ? pal.muted : bad ? pal.accent : pal.ink} opacity={ex ? 0.35 : 1} stroke={pal.bg} strokeWidth={1 / K} />
                  {(bad || ex) && <text x={p.x} y={p.y - 7 / K} fontSize={10 / K} textAnchor="middle" fill={pal.ink} stroke={pal.bg} strokeWidth={3 / K} paintOrder="stroke">{p.w}{tag}</text>}
                </g>
              })}
            </g>}
            {gwcMulti.length > 0 && <g aria-label="Контуры ГВК по вариантам критерия">
              {gwcMulti.map(m => m.res.d && <g key={m.label}>
                <path d={m.res.d} fill="none" stroke={pal.bg} strokeWidth={6} strokeLinejoin="round" opacity={0.85} vectorEffect="non-scaling-stroke" />
                <path d={m.res.d} fill="none" stroke={m.color} strokeWidth={3} strokeLinejoin="round" vectorEffect="non-scaling-stroke"><title>{m.label}</title></path>
                {m.res.at && <text x={m.res.at[0]} y={m.res.at[1]} fontSize={11 / K} fontWeight={700} textAnchor="middle" fill={m.color} stroke={pal.bg} strokeWidth={3.5 / K} paintOrder="stroke">{m.label}</text>}</g>)}
            </g>}
            {awMultiIso.length > 0 && !gwcMulti.some(m => m.res.d) && <g aria-label="Изолинии по вариантам критерия">
              {awMultiIso.map(m => m.res && <g key={m.label}>
                {m.res.conf.map((c, i) => <path key={'c' + i} d={c.d} fill={m.color} opacity={c.a * 0.3} stroke="none" />)}
                {m.res.lines.map(l => <g key={l.level}><path d={l.d} fill="none" stroke={m.color} strokeWidth={1.6} vectorEffect="non-scaling-stroke" strokeLinecap="round" />
                  </g>)}
              </g>)}
              {awLabels.map((l, i) => <text key={i} x={l.x} y={l.y} fontSize={10 / K} textAnchor="middle" fill={l.c} stroke={pal.bg} strokeWidth={3 / K} paintOrder="stroke">{l.t}</text>)}
            </g>}
            {layer}
            {obsLayer}
          </g>
        </g>
        {/* заголовок и легенда рисуются в координатах экрана, поэтому попадают и в PNG */}
        <text x={18} y={32} fontSize={compact ? 15 : 18} fontWeight={700} fill={pal.ink} stroke={pal.bg} strokeWidth={5} paintOrder="stroke" strokeLinejoin="round">{t1}</text>
        <text x={18} y={compact ? 49 : 51} fontSize={compact ? 12 : 13} fill={pal.muted} stroke={pal.bg} strokeWidth={4} paintOrder="stroke" strokeLinejoin="round">{t2}</text>
        {isRef ? <g transform={`translate(14 ${size.h - 14 - (40 + 20 * refInfo.groups.length)})`}>
          <rect width={250} height={40 + 20 * refInfo.groups.length} rx={10} fill={pal.surface} fillOpacity={0.96} stroke={pal.line} filter="url(#mapShadow)" />
          <text x={14} y={22} fontSize={12.5} fontWeight={700} fill={pal.ink}>Опорная сетка · {refNums.length - refInfo.missing.length} скв.</text>
          {refInfo.groups.map((r, i) => <g key={r.name} transform={`translate(14 ${40 + 20 * i})`}><circle r={6} fill={groupColor(r.name)} /><text x={14} fontSize={11.5} dominantBaseline="central" fill={pal.ink}>{r.name}: {r.wells.join(', ')}</text></g>)}
        </g> : <g transform={`translate(14 ${size.h - 14 - (paintData ? 92 : legH)})`}>
          <rect width={LW} height={paintData ? 92 : legH} rx={10} fill={pal.surface} fillOpacity={0.96} stroke={pal.line} filter="url(#mapShadow)" />
          {paintData ? <>
            <text x={14} y={22} fontSize={12.5} fontWeight={700} fill={pal.ink}>{paintData.title}</text>
            <defs><linearGradient id="paintramp" x1="0" x2="1">{[0, 0.25, 0.5, 0.75, 1].map(t => <stop key={t} offset={t} stopColor={rampColor(paintData.stops, t)} />)}</linearGradient></defs>
            <rect x={14} y={32} width={LW - 28} height={10} rx={5} fill="url(#paintramp)" />
            <text x={14} y={57} fontSize={11} fill={pal.muted}>{paintData.fmt(paintData.lo)}</text>
            {paintData.mid && <text x={LW / 2} y={57} fontSize={11} fill={pal.muted} textAnchor="middle">{paintData.fmt((paintData.lo + paintData.hi) / 2)}</text>}
            <text x={LW - 14} y={57} fontSize={11} fill={pal.muted} textAnchor="end">{paintData.fmt(paintData.hi)}</text>
            <circle cx={19} cy={75} r={4.5} fill={pal.surface} stroke={pal.muted} strokeDasharray="2 1.6" /><text x={30} y={79} fontSize={11} fill={pal.muted}>нет данных · {paintData.note}</text>
          </> : <>
            {small ? <text x={14} y={22} fontSize={11.5} fill={pal.muted}><tspan fontWeight={700} fill={pal.ink}>млн м³</tspan></text>
              : <><text x={14} y={22} fontSize={12.5} fontWeight={700} fill={pal.ink}>Расход газа</text>
                <text x={LW - 34} y={22} fontSize={11} fill={pal.muted} textAnchor="end">млн м³ · {options.fixed ? 'шкала сезона' : 'шкала окна'}</text></>}
            {!compact && <g className="no-export" style={{ cursor: 'pointer' }} onPointerDown={e => e.stopPropagation()} onClick={() => legendOpen.set(!legendExpanded)}>
              <title>{legendExpanded ? 'Свернуть легенду' : 'Показать месяцы и воду'}</title>
              <rect x={LW - 26} y={6} width={20} height={20} rx={6} fill={pal.bg} stroke={pal.line} />
              <path d={legendExpanded ? 'M{x1} 17 l4 -3 l4 3'.replace('{x1}', String(LW - 20)) : 'M{x1} 14 l4 3 l4 -3'.replace('{x1}', String(LW - 20))} fill="none" stroke={pal.muted} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
            </g>}
            {refs.map((c, i) => (
              <g key={i}>
                <circle cx={14 + R0} cy={34 + 2 * R0 - c.r} r={c.r} fill={pal.gas} fillOpacity={0.1 + i * 0.12} stroke={pal.gas} strokeWidth={1} />
                <polyline points={`${14 + R0},${34 + 2 * R0 - 2 * c.r} ${14 + 2 * R0 + 6},${34 + 2 * R0 - 2 * c.r} ${14 + 2 * R0 + 14},${labY[i]}`} fill="none" stroke={pal.muted} strokeWidth={0.8} strokeDasharray="2 2" />
                <text x={14 + 2 * R0 + 18} y={labY[i]} fontSize={11} fill={pal.ink} dominantBaseline="central">{fmtMln(c.v)}</text>
              </g>
            ))}
            {!small && !byGroup && usedMonths.length > 1 && <g transform={`translate(14 ${46 + sizeH})`}>
              <text y={0} fontSize={11} fill={pal.muted}>Секторы — месяцы окна, раньше светлее</text>
              {usedMonths.map((m, i) => {
                const w = (LW - 28) / usedMonths.length
                return <g key={m} transform={`translate(${i * w} 8)`}><rect width={w - 2} height={10} rx={3} fill={monthColors[m]} /><text x={(w - 2) / 2} y={25} fontSize={10.5} fill={pal.ink} textAnchor="middle">{MONTH_SHORT[m]}</text></g>
              })}
            </g>}
            {!small && options.water && <g transform={`translate(14 ${legH - (wm.list.length > 1 ? 40 : 14)})`}>
              <circle cx={8} cy={-4} r={7} fill="none" stroke={wm.color.get(wm.list[0]) || pal.water} strokeWidth={2.5} /><circle cx={16} cy={-9} r={4.5} fill={pal.water} />
              <text x={26} y={0} fontSize={11} fill={pal.muted}>вода: кольцо на месяц, толщина — л/ч, кружок — ВФ</text>
              {wm.list.length > 1 && wm.list.map((ym, i) => {
                const w = (LW - 28) / wm.list.length
                return <g key={ym} transform={`translate(${i * w} 8)`}><rect width={w - 2} height={10} rx={3} fill={wm.color.get(ym)} /><text x={(w - 2) / 2} y={25} fontSize={10.5} fill={pal.ink} textAnchor="middle">{MONTH_SHORT[ym % 12]}</text></g>
              })}
            </g>}
          </>}
        </g>}
        {unit && <g transform={`translate(${size.w - 64 - bar * K} ${size.h - 24})`}>
          <rect x={-6} y={-20} width={bar * K + 12} height={26} rx={6} fill={pal.surface} fillOpacity={0.85} />
          <path d={`M0,-2V0H${bar * K}V-2`} fill="none" stroke={pal.ink} strokeWidth={1.5} />
          <rect x={0} y={-2} width={(bar * K) / 2} height={2} fill={pal.ink} />
          <text x={(bar * K) / 2} y={-7} fontSize={11} fill={pal.ink} textAnchor="middle">{bar >= 1000 ? fmt1(bar / 1000) + ' км' : bar + ' м'}</text></g>}
        <g transform={`translate(${size.w - 34} 34)`} className="no-export-keep">
          <circle r={15} fill={pal.surface} stroke={pal.line} filter="url(#mapShadow)" />
          <path d="M0,-10 L4.5,4 L0,1.5 L-4.5,4Z" fill={pal.gas} /><path d="M0,10 L4.5,4 L0,1.5 L-4.5,4Z" fill={pal.muted} opacity={0.5} />
          <text y={-19} textAnchor="middle" fontSize={10} fontWeight={700} fill={pal.muted} stroke={pal.bg} strokeWidth={3} paintOrder="stroke">С</text>
        </g>
      </svg>
      <div className="map-view-ctl no-export">
        <button type="button" className={'view-btn' + (layersOpen ? ' on' : '')} onClick={() => setLayersOpen(v => !v)} aria-expanded={layersOpen} title="Как показывать скважины">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2 1.5 5.5 8 9l6.5-3.5L8 2ZM1.5 8.5 8 12l6.5-3.5M1.5 11.5 8 15l6.5-3.5" /></svg><span className="view-label">Вид карты</span></button>
        {layersOpen && <div className="layers" role="dialog" aria-label="Вид карты">
          <section><h4>Цвет</h4>
            <select value={options.paint} onChange={e => onOptions({ paint: e.target.value as Paint })} aria-label="Раскраска">{PAINTS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
            {options.paint === 'atlas' && atlas && <>
              <select value={atlas.pick} onChange={e => atlas.onPick(e.target.value, atlas.agg)} aria-label="Параметр Атласа">
                <option value="">Выберите параметр…</option>
                {atlas.items.map(i => <option key={i.table + '|' + i.column} value={i.table + '|' + i.column}>{i.title} · {i.label}</option>)}
              </select>
              <select value={atlas.agg} onChange={e => atlas.onPick(atlas.pick, e.target.value)} aria-label="Агрегация">
                {ATLAS_AGGS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
              </select>
            </>}
            {options.paint === 'gis' && gis && <GisControls {...gis} isoNote={iso?.note ?? gis.isoNote} gwcNote={gwc?.note ?? ''} gwcShares={gwc?.shares ?? []} awNote={awNote} roof={{ ...gis.roof, note: [gis.roof.note, roofWarn].filter(Boolean).join(' ') }} />}
            {options.paint === 'model' && models && <ModelPicker {...models.picker} />}
            {options.paint === 'ref' && <>
              <label className="row" style={{ display: 'block' }} title="Номера скважин через запятую, пробел или с новой строки"><span>Опорные скважины</span>
                <textarea rows={3} value={refList} onChange={e => refWells.set(e.target.value)} spellCheck={false} style={{ width: '100%', marginTop: 4 }} aria-label="Список опорных скважин" /></label>
              <label className="row"><span>Размер маркера</span><input type="range" min={1} max={8} step={0.5} value={refK} onChange={e => refSize.set(Number(e.target.value))} /></label>
              <button type="button" onClick={() => refWells.set(REF_PRESET_AN2025)} title="Скв. 56, 83, 220, 182, 237, 264, 437, 520 (ГСП 1, 2, 3, 3, 4, 5, 8, 9)">Таблица 1.2 АН-2025</button>
              <p className="muted small">Цвет маркера — группа скважины в проекте Атласа, остальные скважины — фон. Список — решение инженера.</p>
            </>}
            {!paintData && !isRef && <div className="segmented" role="radiogroup" aria-label="Секторы на круге">
              <button type="button" role="radio" aria-checked={options.sectors === 'months'} onClick={() => onOptions({ sectors: 'months' })} title="Круг разделён на секторы по месяцам">По месяцам</button>
              <button type="button" role="radio" aria-checked={options.sectors === 'plain'} onClick={() => onOptions({ sectors: 'plain' })}>Один цвет</button></div>}
          </section>
          <section><h4>Фон</h4>
            {unit && <label className="check" title="Квадратная сетка с подписями координат; выключена — на карте остаётся только фон"><input type="checkbox" checked={gridOn} onChange={e => mapGrid.set(e.target.checked)} />Координатная сетка</label>}
            <BgPanel placed={placed} align={bgPts} />
          </section>
          {polyData.polys.length > 0 && <section><h4>Многоугольники</h4>
            <PolyPanel polys={polyData.polys} overrides={polyOver} warnings={polyData.warnings} placed={placed} align={alignPts} />
          </section>}
          {!isRef && <section><h4>Круги</h4>
            <label className="row"><span>Размер</span><input type="range" min={0.4} max={2.5} step={0.1} value={options.scale} onChange={e => onOptions({ scale: Number(e.target.value) })} /></label>
            <label className="row"><span>Подпись</span><select value={options.labels} onChange={e => onOptions({ labels: e.target.value as 'num' | 'val' | 'none' })}><option value="num">номер</option><option value="val">расход</option><option value="none">нет</option></select></label>
            {multiG && <label className="check" title="Круг скважины окрашивается цветом её группы (при раскраске по значению цвет группы — обводка)"><input type="checkbox" checked={groupsOn} onChange={e => groupColoring.set(e.target.checked)} />Красить по группам</label>}
            <label className="check" title="Близкие скважины объединяются в один круг со счётчиком, при приближении карты они расходятся"><input type="checkbox" checked={useCluster} onChange={e => clusterWells.set(e.target.checked)} />Группировать близкие скважины</label>
            <label className="check" title="Раздвинуть скважины, чтобы круги не налезали друг на друга; расстояния на карте становятся условными"><input type="checkbox" checked={spread} onChange={e => spreadWells.set(e.target.checked)} />Разнести скважины (схема)</label>
            {!paintData && <label className="check" title="Размер кругов считается от максимума всего сезона, а не выбранного окна"><input type="checkbox" checked={options.fixed} onChange={e => onOptions({ fixed: e.target.checked })} />Шкала по всему сезону</label>}
          </section>}
          {multi && (options.paint === 'entry' || options.paint === 'wf') && <section><h4>Сезоны</h4>
            <div className="segmented" role="radiogroup" aria-label="За какие сезоны">
              {([['one', 'Один'], ['pick', 'Выбрать'], ['all', 'Все, среднее']] as [SeasonScope, string][]).map(([k, t]) => (
                <button key={k} type="button" role="radio" aria-checked={scopeMode === k} onClick={() => seasonScope.set(k)}>{t}</button>))}</div>
            {scopeMode === 'pick' && <div className="season-pick">{multi.seasons.map(sn => (
              <label key={sn.key} className="check"><input type="checkbox" checked={picked.includes(sn.key)}
                onChange={e => pickedSeasons.set(e.target.checked ? [...picked, sn.key] : picked.filter(x => x !== sn.key))} />{sn.key}</label>))}</div>}
            {scopeMode !== 'one' && multi.seasons.length > 1 && scope?.keys.some(k => k !== season && !multi.calcs.has(k)) && options.paint === 'entry' && <p className="muted small">Загружаю сезоны…</p>}
          </section>}
          {!paintData && <section><h4>Показывать</h4>
            <label className="check"><input type="checkbox" checked={options.hideIdle} onChange={e => onOptions({ hideIdle: e.target.checked })} />Только работающие</label>
            <label className="row" title="Скрыть скважины с расходом ниже порога"><span>Порог, млн м³</span><input type="number" min={0} step={0.5} className="thr" value={options.minValue} onChange={e => onOptions({ minValue: Math.max(0, Number(e.target.value) || 0) })} /></label>
            <label className="check"><input type="checkbox" checked={options.water} onChange={e => onOptions({ water: e.target.checked })} />Вынос воды</label>
            <label className="check"><input type="checkbox" checked={options.share} onChange={e => onOptions({ share: e.target.checked })} />Доля ГСП у подписи</label>
          </section>}
        </div>}
      </div>
      {box && <div className="selbox no-export" style={{ left: Math.min(box.x0, box.x1), top: Math.min(box.y0, box.y1), width: Math.abs(box.x1 - box.x0), height: Math.abs(box.y1 - box.y0) }} />}
      <div className="map-chips no-export">
        {group.length > 1 && <span className="map-chip accent">Выбрано скважин: {group.length}<button type="button" onClick={() => onGroup([])} aria-label="Сбросить выбор">×</button></span>}
        {isRef && refInfo.missing.length > 0 && <span className="map-chip warn" title="Этих скважин из списка нет на карте выбранных групп">Не на карте: {refInfo.missing.join(', ')}{multiG ? '' : ' (выберите «Весь объект»)'}</span>}
        {multiG && !isRef && sortLabels(g.groups!, n => n).map(n => <span key={n} className="map-chip" title={byGroup ? 'Цвет круга — группа' : n}><i className="gdot" style={{ background: groupColor(n) }} />{n}</span>)}
        {far.length > 0 && <span className="map-chip" title={'Далёкие скважины: ' + far.join(', ')}>{frameAll ? 'Показаны все скважины' : `За кадром: ${far.length} скв.`}<button type="button" onClick={() => setFrameAll(v => !v)}>{frameAll ? 'Основная группа' : 'Показать'}</button></span>}
        {spread && placed.length > 1 && <span className="map-chip" title="Скважины разнесены для читаемости: взаимное расположение сохранено, расстояния условные">Схема, расстояния условные</span>}
        {options.paint === 'gis' && gis && [gis.error, isoWarn && gis.iso.on ? isoWarn : '', gis.roof.on && !roofLines?.length ? [gis.roof.grid ? '' : gis.roof.note, roofWarn].filter(Boolean).join(' ') : ''].filter(Boolean).map((t, k) =>
          <span key={'gw' + k} className="map-chip warn" role="alert" style={{ whiteSpace: 'normal', maxWidth: 520 }}>{t}</span>)}
        {geo.unplaced.length > 0 && <span className="map-chip warn" title={geo.unplaced.join(', ')}>Без координат: {geo.unplaced.length} скв.</span>}
      </div>
      <div className="map-tools no-export">
        <button type="button" title="Приблизить" onClick={() => zoomBy(1.5)}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg></button>
        <button type="button" title="Отдалить" onClick={() => zoomBy(1 / 1.5)}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10" /></svg></button>
        <button type="button" title="Показать всю карту" onClick={resetView}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" /></svg></button>
      </div>
      {tipNode && (tipHost ? createPortal(tipNode, tipHost) : tipNode)}
      {!placed.length && <div className="empty-map">Для этого ГСП нет положений скважин. Задайте карту-сетку или файл XY в разделе «Данные».</div>}
      <span className="sr-only">{fmtDay(calc.days[a])} — {fmtDay(calc.days[b])}</span>
    </div>
  )
})
export default MapView
