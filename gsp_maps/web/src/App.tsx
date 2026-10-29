import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GroupColorsButton } from '../../../pxg_core/web-ui/GroupColorsButton'
import { refreshBackground } from './background'
import { refreshPolygons } from './polygons'
import { exportExcel, getGsp, getGis, getObservers, type Observers, getGisModel, getGisModelWells, getGisModelWellsVariants, getRoof, reportIssue, type RoofGrid, getGisValues, type GisModel, getParam, getParams, type GisCatalog, type GisValues, getSeason, getState, getModels, getModelKeywords, getModelValues, selectModels, setModelFolders, pickPath, type ModelKeyword, type ModelsView, type ModelValues, type ParamItem, type ParamValues, groupsOf, locateWell, isMulti, nameOf, saveImage, setAllGroups, groupColor, ALL_GSP, type AppState, type GspData } from './api'
import Compare from './Compare'
import Inspector from './Inspector'
import SideGrip from './SideGrip'
import MapView, { type MapHandle } from './MapView'
import { ATLAS_AGGS, SeasonCalc, atlasPaint, gisPaint, dayDate, fmtDay, scopeKeys } from './model'
import { parseExcl, parseSpec, type GisModelWells, type GisVariants } from './allWells'
import SharesPage from './SharesPage'
import WellsPage from './WellsPage'
import WorkPage from './WorkPage'
import { DataPage, PressurePage, TablePage, TrendsPage } from './Pages'
import { bubbleScale, hideIdle, minValue, labelMode, paintMode, atlasParam, atlasAgg, gisPack, gisMetric, gisSeason, gisAgainst, gisPins, gisSource, gisGwc, gisGwcMode, gisGwcPar, gisGwcExcl, gisRoof, gisRoofModel, gisAllOn, gisAllModel, gisAllMulti, gisAllSpec, gisAllDate, gisAllMode, gisAllDepth, gisAllPreset, gisAllOutlier, gisAllExcl, gisRoofLayer, gisRoofStep, gisIso, gisObservers, gisGeophys, gisIsoStep, gisIsoReach, modelKeyword, modelAgg, fixedScale, inspectorOpen, tipMode, lastGsp, pickedSeasons, seasonScope, lastKind, posMode, sectors, showShare, showWater, sidebarCollapsed, theme, usePref, type Theme } from './prefs'
import Timeline from './Timeline'

const PAGES = [
  { id: 'map', title: 'Карта', icon: 'M8 1.5a4.5 4.5 0 0 1 4.5 4.5c0 3-4.5 8.5-4.5 8.5S3.5 9 3.5 6A4.5 4.5 0 0 1 8 1.5Zm0 3a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Z' },
  { id: 'compare', title: 'Сравнение', icon: 'M2 3h5v10H2zM9 3h5v10H9zM4.5 6v4M11.5 6v4' },
  { id: 'wells', title: 'Скважины', icon: 'M3 13V9M7 13V4M11 13V7M15 13V2M2 13.5h13' },
  { id: 'work', title: 'Работа скважин', icon: 'M2 3h12M2 8h12M2 13h12M4 3v0M7 8v0M10 13v0M3 5.5h5M6 10.5h7' },
  { id: 'shares', title: 'Доли', icon: 'M8 2a6 6 0 1 0 6 6H8zM9.5 1.5A5 5 0 0 1 14.5 6.5H9.5z' },
  { id: 'table', title: 'Таблица', icon: 'M2 3h12v10H2zM2 6.5h12M2 10h12M6 3v10' },
  { id: 'pressure', title: 'Давление', icon: 'M2 13V3M2 13h12M4 10l3-3 2 2 4-5' },
  { id: 'trends', title: 'Тренды', icon: 'M2 12l4-4 3 2 5-6M10 4h4v4' },
  { id: 'data', title: 'Данные', icon: 'M3 3h10v3H3zM3 8h10v3H3zM5 4.5h.01M5 9.5h.01M3 13h10' },
] as const
type PageId = (typeof PAGES)[number]['id']
const routeOf = (): PageId => { const r = location.hash.replace(/^#\/?/, '').split('?')[0]; return (PAGES.find(p => p.id === r)?.id || 'map') }
/** Адрес карты: #/map?gsp=ГСП-1&well=123&kind=Отбор&season=2022-2023 — выбирает группу, скважину, вид и сезон. */
const addressOf = (): { gsp: string; well: number; kind: string; season: string } | null => {
  if (!/^#\/?map\?/.test(location.hash)) return null
  const q = new URLSearchParams(location.hash.split('?')[1] || '')
  const well = Number(q.get('well'))
  if (!Number.isInteger(well) || well <= 0) return null
  return { gsp: q.get('gsp') || '', well, kind: q.get('kind') || '', season: q.get('season') || '' }
}

function Issues({ notes, warnings }: { notes: string[]; warnings: string[] }) {
  const [open, setOpen] = useState(false)
  const all = [...notes, ...warnings]
  if (!all.length) return null
  return (
    <div className="issues">
      <button type="button" className="quiet warn" aria-expanded={open} onClick={() => setOpen(o => !o)} title="Замечания по файлам и положению скважин">⚠ {all.length}</button>
      {open && <div className="issues-pop" role="dialog" aria-label="Замечания">{all.map((t, i) => <p key={i}>{t}</p>)}</div>}
    </div>
  )
}

export default function App() {
  const [app, setApp] = useState<AppState | null>(null)
  const [, setColorTick] = useState(0)       // смена цвета группы вручную: перерисовать карту и подписи
  const [error, setError] = useState('')
  const [page, setPage] = useState<PageId>(routeOf())
  const [addr, setAddr] = useState(addressOf)
  const [want, setWant] = useState<{ gsp: string; well: number } | null>(null)
  const collapsed = usePref(sidebarCollapsed), currentTheme = usePref(theme)
  const mode = usePref(posMode), kind = usePref(lastKind), gspPref = usePref(lastGsp)
  const sec = usePref(sectors), water = usePref(showWater), share = usePref(showShare), fixed = usePref(fixedScale), paint = usePref(paintMode), bscale = usePref(bubbleScale), labels = usePref(labelMode), idleOff = usePref(hideIdle), minV = usePref(minValue), insp = usePref(inspectorOpen), tmode = usePref(tipMode)
  const [g, setG] = useState<GspData | null>(null)
  const [gErr, setGErr] = useState('')
  const [seasonKey, setSeasonKey] = useState('')
  const [calc, setCalc] = useState<SeasonCalc | null>(null)
  const [calcKey, setCalcKey] = useState('')
  const [prev, setPrev] = useState<SeasonCalc | null>(null)
  const [batch, setBatch] = useState<{ keys: string[]; i: number } | null>(null)
  const [win, setWin] = useState<[number, number]>([0, 0])
  const [selected, setSelected] = useState<number | null>(null)
  const [group, setGroup] = useState<number[]>([])
  const pick = useCallback((w: number | null) => { setSelected(w); setGroup([]) }, [])
  const [find, setFind] = useState('')
  const [note, setNote] = useState('')
  const [tipDock, setTipDock] = useState<HTMLElement | null>(null)
  const map = useRef<MapHandle>(null)

  const refresh = useCallback(() => getState().then(setApp).catch(e => setError(String(e.message || e))), [])
  useEffect(() => { refresh() }, [refresh])
  useEffect(() => {
    if (app?.state !== 'loading') return
    const t = setInterval(refresh, 500)
    return () => clearInterval(t)
  }, [app?.state, refresh])
  useEffect(() => {
    const onHash = () => { setPage(routeOf()); setAddr(addressOf()) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const ready = app?.state === 'ready'
  // «Весь объект» — все ГСП на одной карте; пункт есть, если групп больше одной
  if (ready) setAllGroups(app!.gsps)
  const withMap = ready ? app!.gsps.find(x => app!.gspMeta[x]?.grid || app!.gspMeta[x]?.xy) : undefined
  const prefOk = ready && !!gspPref && groupsOf(gspPref).every(n => app!.gsps.includes(n))
  const gsp = ready ? (prefOk ? gspPref : withMap || app!.gsps[0] || '') : ''
  const selGroups = ready ? groupsOf(gsp) : []
  const wholeField = ready && isMulti(gsp)
  useEffect(() => {
    const close = (e: PointerEvent) => { const d = groupRef.current; if (d?.open && !d.contains(e.target as Node)) d.removeAttribute('open') }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [])
  const toggleGroup = (n: string) => {
    const has = selGroups.includes(n)
    if (has && selGroups.length === 1) return
    lastGsp.set(nameOf(has ? selGroups.filter(x => x !== n) : [...selGroups, n]))
  }
  useEffect(() => {
    if (!ready || !gsp) return
    let live = true
    setGErr('')
    getGsp(gsp, mode).then(d => { if (live) { setG(d); setSelected(null) } }).catch(e => live && setGErr(String(e.message || e)))
    return () => { live = false }
  }, [ready, gsp, mode])

  // параметры Атласа: каталог — при загрузке проекта; значения — при выборе параметра на карте
  const [atlasItems, setAtlasItems] = useState<ParamItem[]>([])
  const [atlasVals, setAtlasVals] = useState<ParamValues | null>(null)
  const atlasPick = usePref(atlasParam), atlasAggV = usePref(atlasAgg)
  useEffect(() => {
    if (!ready) return
    getParams().then(r => setAtlasItems(r.items)).catch(() => setAtlasItems([]))
  }, [ready])
  useEffect(() => {
    if (!ready || paint !== 'atlas' || !atlasPick.includes('|')) { setAtlasVals(null); return }
    let live = true
    const [table, column] = atlasPick.split('|')
    getParam(table, column, atlasAggV).then(r => live && setAtlasVals(r)).catch(() => live && setAtlasVals(null))
    return () => { live = false }
  }, [ready, paint, atlasPick, atlasAggV])
  const atlasData = useMemo(() => {
    if (!atlasVals) return null
    const item = atlasItems.find(i => i.table === atlasVals.table && i.column === atlasVals.column)
    return atlasPaint(atlasVals.values, (item ? item.title + ' · ' + item.label : atlasVals.column) + ' · ' + (atlasVals.agg === 'mean' ? 'среднее' : atlasVals.agg), atlasVals.warnings)
  }, [atlasVals, atlasItems])

  // ГИС и ГВК: каталог базы ГИС — при загрузке проекта; значения — при выборе в режиме «ГИС и ГВК»
  const [gisCat, setGisCat] = useState<GisCatalog | null>(null)
  const [obs, setObs] = useState<Observers | null>(null)
  const obsOn = usePref(gisObservers), geoOn = usePref(gisGeophys)
  const [gisVals, setGisVals] = useState<GisValues | null>(null)
  const [gisErr, setGisErr] = useState(''), [gisModErr, setGisModErr] = useState('')
  const gPack = usePref(gisPack), gMetric = usePref(gisMetric), gSeason = usePref(gisSeason), gAgainst = usePref(gisAgainst), gPinsRaw = usePref(gisPins), isoOn = usePref(gisIso), isoStep = usePref(gisIsoStep), isoReach = usePref(gisIsoReach)
  const gPins = useMemo(() => Object.fromEntries(gPinsRaw.split(',').filter(x => x.includes(':')).map(x => x.split(':') as [string, string])), [gPinsRaw])
  useEffect(() => {
    if (!ready) return
    getGis().then(r => { setGisCat(r); setGisErr('') }).catch(e => { setGisCat(null); setGisErr('База ГИС не прочитана: ' + String(e.message || e)); reportIssue('ГИС: каталог', String(e.message || e)) })
  }, [ready])
  // выбор по умолчанию — подсказка: пачка с наибольшим числом замеров не определяется, берём первую и последний сезон; инженер меняет вручную
  useEffect(() => {
    if (!ready || paint !== 'gis') return
    let live = true
    getObservers().then(r => live && setObs(r)).catch(() => live && setObs(null))
    return () => { live = false }
  }, [ready, paint])
  const gisPackUse = gisCat?.packs.includes(gPack) ? gPack : gisCat?.packs[0] ?? ''
  const gisSeasonUse = gisCat?.seasons.some(s => s.key === gSeason) ? gSeason : gisCat?.seasons[gisCat.seasons.length - 1]?.key ?? ''
  const gisAgainstUse = gisCat?.seasons.some(s => s.key === gAgainst) && gAgainst !== gisSeasonUse ? gAgainst : ''
  useEffect(() => {
    if (!ready || paint !== 'gis' || !gisPackUse || !gisSeasonUse) { setGisVals(null); return }
    let live = true
    getGisValues(gisPackUse, gMetric, gisSeasonUse, gisAgainstUse, gisAgainstUse ? {} : gPins).then(r => { if (live) { setGisVals(r); setGisErr('') } }).catch(e => { if (live) { setGisVals(null); setGisErr('Значения ГИС и ГВК не получены: ' + String(e.message || e)); reportIssue('ГИС: значения', String(e.message || e)) } })
    return () => { live = false }
  }, [ready, paint, gisPackUse, gMetric, gisSeasonUse, gisAgainstUse, gPins])
  const gwcOn = usePref(gisGwc), gwcMode = usePref(gisGwcMode), gwcPar = usePref(gisGwcPar), gwcExclRaw = usePref(gisGwcExcl)
  const gSource = usePref(gisSource)
  const [gisMod, setGisMod] = useState<GisModel | null>(null)
  useEffect(() => {
    if (!ready || paint !== 'gis' || gSource === 'fact' || !gisPackUse || !gisSeasonUse) { setGisMod(null); return }
    let live = true
    getGisModel(gisPackUse, gisSeasonUse).then(r => { if (live) { setGisMod(r); setGisModErr('') } }).catch(e => { if (live) { setGisMod(null); setGisModErr(String(e.message || e)); reportIssue('ГИС: ГВК модели', String(e.message || e)) } })
    return () => { live = false }
  }, [ready, paint, gSource, gisPackUse, gisSeasonUse])
  const gisData = useMemo(() => (gSource !== 'fact' ? (gisMod ? gisPaint(gSource === 'delta' ? gisMod.delta : gisMod.model, gisMod.dates, (gSource === 'delta' ? 'Δ ГВК модель − факт' : 'ГВК модели') + ' · ' + gisPackUse + ' · ' + gisSeasonUse, gisMod.warnings, gSource === 'delta') : null) : gisVals ? gisPaint(gisVals.values, gisVals.dates, gisVals.title, gisVals.warnings, !!gisAgainstUse) : null), [gisVals, gisAgainstUse, gSource, gisMod, gisPackUse, gisSeasonUse])

  // адрес из ссылки: сначала группа и вид/сезон, выбор скважины — когда загрузится нужная группа
  useEffect(() => {
    if (!ready || !addr) return
    const a = addr
    setAddr(null)
    locateWell(a.gsp, a.well).then(r => {
      if (!r.groups.length) return flash(`Скважины ${a.well} нет в базе расходов`)
      const target = r.groups.includes(r.gsp) ? r.gsp : r.groups[0]
      if (a.kind === 'Отбор' || a.kind === 'Закачка') lastKind.set(a.kind)
      if (a.season) setSeasonKey(a.season)
      lastGsp.set(target)
      setWant({ gsp: target, well: a.well })
    }).catch(e => flash(String(e.message || e)))
  }, [ready, addr])
  useEffect(() => {
    if (!want || !g || g.gsp !== want.gsp) return
    setSelected(g.wells.includes(want.well) ? want.well : null)
    setWant(null)
  }, [want, g])

  const seasons = g ? g.seasons[kind as 'Отбор' | 'Закачка'] || [] : []
  const season = seasons.find(s => s.key === seasonKey) ? seasonKey : seasons.length ? seasons[seasons.length - 1].key : ''
  useEffect(() => {
    if (!g || !season) { setCalc(null); return }
    let live = true
    getSeason(g.gsp, kind, season).then(d => {
      if (!live) return
      const c = new SeasonCalc(d)
      setCalc(c); setCalcKey(season); setWin([0, Math.max(0, c.nd - 1)])
    }).catch(e => live && setGErr(String(e.message || e)))
    return () => { live = false }
  }, [g, kind, season])

  const prevKey = (() => { const i = seasons.findIndex(s => s.key === season); return i > 0 ? seasons[i - 1].key : '' })()
  useEffect(() => {
    setPrev(null)
    if (!g || !prevKey) return
    let live = true
    getSeason(g.gsp, kind, prevKey).then(d => { if (live) setPrev(new SeasonCalc(d)) }).catch(() => { /* сравнение необязательно */ })
    return () => { live = false }
  }, [g, kind, prevKey])

  // сезоны для раскраски «Ввод» по нескольким сезонам: догружаются по мере надобности
  const scope = usePref(seasonScope), picked = usePref(pickedSeasons)
  const [extra, setExtra] = useState<Map<string, SeasonCalc>>(new Map())
  const extraOwner = useRef('')
  const wantKeys = g && paint === 'entry' && scope !== 'one' ? scopeKeys(scope, picked, seasons, season).filter(k => k !== season) : []
  const wantSig = wantKeys.join('|')
  useEffect(() => {
    if (!g) return
    const owner = g.gsp + '|' + kind
    if (extraOwner.current !== owner) { extraOwner.current = owner; setExtra(new Map()) }
    const need = wantKeys.filter(k => !(extraOwner.current === owner && extra.has(k)))
    if (!need.length) return
    let live = true
    Promise.all(need.map(k => getSeason(g.gsp, kind, k).then(d => [k, new SeasonCalc(d)] as const))).then(r => {
      if (live) setExtra(m => { const n = new Map(extraOwner.current === owner ? m : []); r.forEach(([k, c]) => n.set(k, c)); return n })
    }).catch(() => { /* остальные сезоны необязательны */ })
    return () => { live = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [g, kind, wantSig])
  const multi = useMemo(() => ({ seasons, calcs: extra }), [seasons, extra])

  const setWindow = useCallback((a: number, b: number) => setWin([a, b]), [])
  const [a, b] = calc ? calc.clampWindow(win[0], win[1]) : [0, 0]
  // модели tNavigator: общий список папок и отмеченных моделей, вектор и значения по окну дат (раскраска «Модели tNavigator»)
  const [modelView, setModelView] = useState<ModelsView | null>(null)
  const [modelKws, setModelKws] = useState<ModelKeyword[]>([])
  const [modelVals, setModelVals] = useState<ModelValues | null>(null)
  const [modelErr, setModelErr] = useState('')
  const modelKw = usePref(modelKeyword), modelAggV = usePref(modelAgg)
  useEffect(() => {
    if (!ready || (paint !== 'model' && paint !== 'gis')) return
    getModels().then(setModelView).catch(e => setModelErr(String(e.message || e)))
  }, [ready, paint])
  const pair = (modelView?.selected ?? []).slice(0, 2)
  const pairKey = pair.join('|')
  // многоугольники из файла: перечитываются при готовности данных и смене файла
  useEffect(() => { if (ready) refreshPolygons() }, [ready, app?.paths.polygons])
  useEffect(() => { if (ready) refreshBackground() }, [ready, app?.paths.background])
  const roofOn = usePref(gisRoof), roofModel = usePref(gisRoofModel), roofLayer = usePref(gisRoofLayer), roofStep = usePref(gisRoofStep)
  const [roofGrid, setRoofGrid] = useState<RoofGrid | null>(null)
  const [roofErr, setRoofErr] = useState('')
  const roofPath = roofModel || modelView?.selected[0] || ''
  useEffect(() => {
    if (!ready || paint !== 'gis' || !roofOn || !roofPath) { setRoofGrid(null); setRoofErr(''); return }
    let live = true
    setRoofErr('')
    getRoof(roofPath, Math.max(0, Math.floor(Number(roofLayer) || 0))).then(r => live && setRoofGrid(r)).catch(e => { if (live) { setRoofGrid(null); setRoofErr(String(e.message || e)); reportIssue('кровля: запрос', String(e.message || e)) } })
    return () => { live = false }
  }, [ready, paint, roofOn, roofPath, roofLayer])
  // ГВК по всем скважинам модели (выключено по умолчанию): точки считает сервер на шаге рестарта у даты (пусто — последний)
  const awOn = usePref(gisAllOn), awModelPref = usePref(gisAllModel), awDatePref = usePref(gisAllDate), awMode = usePref(gisAllMode), awDepth = usePref(gisAllDepth)
  const awPreset = usePref(gisAllPreset), awOutlier = usePref(gisAllOutlier), awExclRaw = usePref(gisAllExcl)
  const [awData, setAwData] = useState<GisModelWells | null>(null)
  const [awErr, setAwErr] = useState('')
  const awModels = (modelView?.models ?? []).filter(m => m.files.includes('EGRID'))
  const awModel = awModels.some(m => m.id === awModelPref) ? awModelPref : awModels[0]?.id ?? ''
  useEffect(() => {
    if (!ready || paint !== 'gis' || !awOn || !awModel) { setAwData(null); setAwErr(''); return }
    let live = true
    setAwErr('')
    getGisModelWells(awModel, awDatePref, awPreset).then(r => { if (live) setAwData(r) }).catch(e => { if (live) { setAwData(null); setAwErr(String(e.message || e)); reportIssue('ГВК по всем скважинам', String(e.message || e)) } })
    return () => { live = false }
  }, [ready, paint, awOn, awModel, awDatePref, awPreset])
  // несколько вариантов критерия: отдельный запрос, изолинии каждого варианта рисуются разным цветом
  const awMultiOn = usePref(gisAllMulti), awSpecRaw = usePref(gisAllSpec)
  const [awVars, setAwVars] = useState<GisVariants | null>(null)
  const [awVarsErr, setAwVarsErr] = useState('')
  const [awVarsBusy, setAwVarsBusy] = useState(false)
  useEffect(() => {
    if (!ready || paint !== 'gis' || !awOn || !awMultiOn || !awModel) { setAwVars(null); setAwVarsErr(''); setAwVarsBusy(false); return }
    let spec: [string, number[]][]
    try { spec = parseSpec(awSpecRaw) } catch (e) { setAwVars(null); setAwVarsErr(String((e as Error).message)); return }
    let live = true
    setAwVarsErr(''); setAwVarsBusy(true)
    getGisModelWellsVariants(awModel, awDatePref, spec).then(r => { if (live) { setAwVars(r); setAwVarsBusy(false) } }).catch(e => { if (live) { setAwVars(null); setAwVarsBusy(false); setAwVarsErr(String(e.message || e)); reportIssue('ГВК по вариантам критерия', String(e.message || e)) } })
    return () => { live = false }
  }, [ready, paint, awOn, awMultiOn, awModel, awDatePref, awSpecRaw])
  // координаты карты идут вниз по Y: строки растра переворачиваются, чтобы изолинии легли на скважины
  const roofRaster = useMemo(() => {
    if (!roofGrid || !roofGrid.nx) return null
    const z = new Float64Array(roofGrid.nx * roofGrid.ny).fill(NaN)
    roofGrid.z.forEach((row, j) => row.forEach((v, i) => { if (v !== null) z[(roofGrid.ny - 1 - j) * roofGrid.nx + i] = v }))
    return { z, nx: roofGrid.nx, ny: roofGrid.ny, x0: roofGrid.x0, y0: -(roofGrid.y0 + (roofGrid.ny - 1) * roofGrid.dy), dx: roofGrid.dx, dy: roofGrid.dy }
  }, [roofGrid])
  useEffect(() => {
    if (!ready || paint !== 'model' || !pairKey) { setModelKws([]); return }
    let live = true
    getModelKeywords(pairKey.split('|')[0]).then(r => {
      if (!live) return
      setModelKws(r.items)
      if (r.items.length && !r.items.some(k => k.keyword === modelKw.trim())) modelKeyword.set(r.items[0].keyword)
    }).catch(() => live && setModelKws([]))
    return () => { live = false }
  }, [ready, paint, pairKey])
  const winStart = calc && calc.nd ? dayDate(calc.days[a]).toISOString().slice(0, 10) : ''
  const winEnd = calc && calc.nd ? dayDate(calc.days[b]).toISOString().slice(0, 10) : ''
  useEffect(() => {
    if (!ready || paint !== 'model' || !pairKey || !modelKw.trim() || !winStart) { setModelVals(null); return }
    let live = true
    getModelValues(modelKw.trim(), winStart, winEnd, modelAggV, pairKey.split('|')).then(r => {
      if (live) { setModelVals(r); setModelErr('') }
    }).catch(e => { if (live) { setModelVals(null); setModelErr(String(e.message || e)) } })
    return () => { live = false }
  }, [ready, paint, modelKw, modelAggV, winStart, winEnd, pairKey])
  const modelName = (id: string) => modelView?.models.find(m => m.id === id)?.name ?? id
  const modelData = useMemo(() => {
    if (!modelVals) return null
    const ids = pairKey.split('|').filter(id => modelVals.models[id])
    const ok = ids.filter(id => modelVals.models[id].values)
    const errs = ids.filter(id => modelVals.models[id].error).map(id => modelName(id) + ': ' + modelVals.models[id].error)
    if (!ok.length) return { paint: null, note: errs.join(' ') }
    const aggLabel = ATLAS_AGGS.find(([k]) => k === modelVals.agg)?.[1] ?? modelVals.agg
    const unit = modelVals.models[ok[0]].unit ? ', ' + modelVals.models[ok[0]].unit : ''
    let values: Record<string, number> = {}, title = modelName(ok[0])
    if (ok.length === 1) values = modelVals.models[ok[0]].values ?? {}
    else {
      const va = modelVals.models[ok[0]].values ?? {}, vb = modelVals.models[ok[1]].values ?? {}
      for (const w of Object.keys(va)) if (w in vb) values[w] = vb[w] - va[w]
      title = modelName(ok[1]) + ' − ' + modelName(ok[0])
    }
    const note = (ok.length >= 2 ? 'Разность по скважинам, которые есть в обеих моделях.' : '') + (ok.length >= 2 && modelView && modelView.selected.length > 2 ? ' Показаны первые две отмеченные модели.' : '')
    return { paint: atlasPaint(values, title + ' · ' + modelKw + ' · ' + aggLabel + unit, errs), note: [note, ...errs].filter(Boolean).join(' ') }
  }, [modelVals, pairKey, modelView, modelKw])

  const title = g && calc ? `${g.gsp} · ${kind} ${season} · ${fmtDay(calc.days[a])} — ${fmtDay(calc.days[b])}` : ''
  useEffect(() => { document.title = 'Карты' + (gsp ? ' · ' + gsp : '') }, [gsp])

  const flash = (t: string) => { setNote(t); setTimeout(() => setNote(''), 6000) }
  const png = async () => {
    try {
      const blob = await map.current!.toPng()
      const name = `Карта_${gsp.replace(/\s/g, '_')}_${kind}_${season}.png`
      try { const r = await saveImage(name, blob); flash('Картинка сохранена: ' + r.path) } catch {
        const u = URL.createObjectURL(blob), el = document.createElement('a'); el.href = u; el.download = name; el.click(); URL.revokeObjectURL(u)
      }
    } catch (e) { flash(String((e as Error).message || e)) }
  }
  const savePng = async (name: string) => {
    const blob = await map.current!.toPng()
    try { await saveImage(name, blob) } catch {
      const u = URL.createObjectURL(blob), el = document.createElement('a'); el.href = u; el.download = name; el.click(); URL.revokeObjectURL(u)
    }
  }
  const pngAll = () => { if (seasons.length) setBatch({ keys: seasons.map(s => s.key), i: 0 }) }
  useEffect(() => {
    if (!batch) return
    const key = batch.keys[batch.i]
    if (season !== key) { setSeasonKey(key); return }
    if (calcKey !== key || !calc) return
    let live = true
    const t = setTimeout(async () => {
      try { await savePng(`Карта_${gsp.replace(/\s/g, '_')}_${kind}_${key}.png`) } catch (e) { if (live) { flash(String((e as Error).message || e)); setBatch(null) } return }
      if (!live) return
      if (batch.i + 1 < batch.keys.length) setBatch({ keys: batch.keys, i: batch.i + 1 })
      else { setBatch(null); flash(`Сохранено картинок: ${batch.keys.length} (папка результатов)`) }
    }, 400)
    return () => { live = false; clearTimeout(t) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch, season, calcKey, calc])
  const exportRef = useRef<HTMLDetailsElement>(null)
  const groupRef = useRef<HTMLDetailsElement>(null)
  const excel = async () => {
    if (wholeField) { flash('Excel считается по одному ГСП: выберите ГСП вверху'); return }
    try { const r = await exportExcel(gsp, mode); flash('Excel сохранён: ' + r.path) } catch (e) { flash(String((e as Error).message || e)) } }
  const goFind = (v: string) => {
    setFind(v)
    const n = Number(v)
    if (calc && calc.index.has(n)) { setSelected(n); map.current?.focus(n) }
  }

  const groupedNav = useMemo(() => PAGES, [])
  if (error) return <div className="fatal"><h1>Карты</h1><p>{error}</p></div>
  const body = () => {
    if (!app) return <p className="muted">Загрузка…</p>
    if (page === 'data') return <DataPage app={app} setApp={setApp} mode={mode} setMode={posMode.set} gsp={gsp} onReload={refresh} />
    if (app.state === 'loading') return (
      <section className="card loading"><div className="spinner" aria-hidden="true" /><div><h2>Загружаю данные из проекта Атласа</h2>
        <pre className="log">{app.log.join('\n') || 'Подготовка…'}</pre>
        <p className="muted">Первый раз это может занять до минуты; дальше данные открываются из кэша быстрее.</p></div></section>)
    if (app.state !== 'ready') return (
      <section className="card"><h2>{app.state === 'error' ? 'База не загрузилась' : 'Сначала подключите данные'}</h2>
        {app.state === 'error' && <pre className="log">{app.log.join('\n')}</pre>}
        <p className="muted">Откройте раздел «Данные»: выберите проект Газового Атласа (расходы, давления, вода и координаты загружаются в Атласе).</p>
        <p><a className="primary linkbtn" href="#/data">Перейти к данным</a></p></section>)
    if (g && page === 'compare') return (
      <Compare g={g} kind={kind} inspector={insp} options={{ sectors: sec, water, share, fixed, paint, scale: bscale, labels, hideIdle: idleOff, minValue: minV }}
        onOptions={o => { if (o.sectors) sectors.set(o.sectors); if (o.water !== undefined) showWater.set(o.water); if (o.share !== undefined) showShare.set(o.share); if (o.fixed !== undefined) fixedScale.set(o.fixed); if (o.paint) paintMode.set(o.paint); if (o.scale !== undefined) bubbleScale.set(o.scale); if (o.labels) labelMode.set(o.labels); if (o.hideIdle !== undefined) hideIdle.set(o.hideIdle); if (o.minValue !== undefined) minValue.set(o.minValue) }} />)
    if (!g || !calc) return gErr ? <div className="note warning">{gErr}</div> : <p className="muted">Считаю…</p>
    if (wholeField && ['table', 'work', 'shares'].includes(page)) return <section className="card"><h2>Нужна одна группа</h2><p className="muted">Эта страница считается по одному ГСП. Выберите ГСП вверху: «Весь объект» работает на картах, в сравнении и в разделе «Скважины».</p></section>
    if (page === 'table') return <TablePage g={g} calc={calc} kind={kind} season={season} a={a} b={b} mode={mode} />
    if (page === 'pressure') return <PressurePage g={g} kind={kind} season={season} range={[calc.days[a], calc.days[b]]} />
    if (page === 'wells') return <WellsPage g={g} calc={calc} kind={kind} season={season} a={a} b={b} selected={selected} onSelect={setSelected} group={group} />
    if (page === 'work') return <WorkPage g={g} calc={calc} kind={kind} season={season} selected={selected} onSelect={setSelected} />
    if (page === 'shares') return <SharesPage g={g} kind={kind} selected={selected} onSelect={setSelected} />
    if (page === 'trends') return <TrendsPage g={g} />
    return (
      <div className={'map-page' + (insp ? '' : ' no-insp')}>
        <div className="map-main">
          <MapView ref={map} models={{ paint: modelData?.paint ?? null, picker: { view: modelView, keywords: modelKws, keyword: modelKw, agg: modelAggV, note: modelErr || modelData?.note || (pair.length ? '' : 'Отметьте модели, которые нужно показать на карте.'), onKeyword: k => modelKeyword.set(k), onAgg: v => modelAgg.set(v), onSelect: ids => selectModels(ids).then(setModelView).catch(e => setModelErr(String(e.message || e))), onFolders: fs => setModelFolders(fs).then(setModelView).catch(e => setModelErr(String(e.message || e))), onAddFolder: () => pickPath('folder', '').then(r => { if (r.path) setModelFolders([...(modelView?.folders ?? []), r.path]).then(setModelView) }).catch(e => setModelErr(String(e.message || e))) } }} gis={{ catalog: gisCat, pack: gisPackUse, metric: gMetric, season: gisSeasonUse, against: gisAgainstUse, pins: gPins, options: gisVals?.options ?? {}, dates: gisVals?.dates ?? {}, paint: gisData, iso: { on: isoOn, step: isoStep, reach: isoReach }, isoNote: '', obs: { on: obsOn, geoOn, data: obs, onToggle: v => gisObservers.set(v), onToggleGeo: v => gisGeophys.set(v) }, gwc: { on: gwcOn, mode: gwcMode, par: gwcPar, excl: parseExcl(gwcExclRaw) }, allWells: { on: awOn, model: awModel, models: awModels, date: awData?.date ?? awDatePref, dates: awData?.dates ?? [], mode: awMode, depth: awDepth, preset: awPreset, presets: awData?.presets ?? [], outlier: awOutlier, excl: parseExcl(awExclRaw), data: awData, err: awErr, multi: awMultiOn, spec: awSpecRaw, variants: awVars, variantsErr: awVarsErr, variantsBusy: awVarsBusy, fact: gSource === 'fact' && gMetric === 'gvk_abs_m' && !gisAgainstUse ? gisVals?.values ?? null : null }, roof: { on: roofOn, model: roofPath, layer: roofLayer, step: roofStep, models: (modelView?.models ?? []).filter(m => m.files.includes('EGRID')), note: roofErr || roofGrid?.note || (roofOn && !(modelView?.models ?? []).some(m => m.files.includes('EGRID')) ? 'Нет моделей с файлом сетки EGRID: добавьте папку с результатами tNavigator в режиме «Модели tNavigator».' : roofOn && !roofPath ? 'Выберите модель для кровли.' : ''), grid: roofRaster }, source: gSource, modelInfo: gisModErr ? 'ГВК модели не прочитан: ' + gisModErr : gisMod?.info ?? gisMod?.warnings[0] ?? '', error: gisErr,
            onChange: p => { if (p.pack !== undefined) gisPack.set(p.pack); if (p.metric !== undefined) gisMetric.set(p.metric); if (p.season !== undefined) gisSeason.set(p.season); if (p.against !== undefined) gisAgainst.set(p.against); if (p.gwcOn !== undefined) gisGwc.set(p.gwcOn); if (p.gwcMode) gisGwcMode.set(p.gwcMode); if (p.gwcPar) gisGwcPar.set({ ...gwcPar, ...p.gwcPar }); if (p.gwcReset) gisGwcExcl.set(''); if (p.gwcToggle !== undefined) { const ex = parseExcl(gwcExclRaw); if (ex.has(p.gwcToggle)) ex.delete(p.gwcToggle); else ex.add(p.gwcToggle); gisGwcExcl.set([...ex].join(',')) } if (p.roofOn !== undefined) gisRoof.set(p.roofOn); if (p.roofModel !== undefined) gisRoofModel.set(p.roofModel); if (p.roofLayer !== undefined) gisRoofLayer.set(p.roofLayer); if (p.roofStep !== undefined) gisRoofStep.set(p.roofStep); if (p.source !== undefined) gisSource.set(p.source); if (p.iso !== undefined) gisIso.set(p.iso); if (p.isoStep !== undefined) gisIsoStep.set(p.isoStep); if (p.isoReach !== undefined) gisIsoReach.set(p.isoReach); if (p.awOn !== undefined) gisAllOn.set(p.awOn); if (p.awModel !== undefined) gisAllModel.set(p.awModel); if (p.awDate !== undefined) gisAllDate.set(p.awDate); if (p.awMode) gisAllMode.set(p.awMode); if (p.awDepth) gisAllDepth.set(p.awDepth); if (p.awPreset !== undefined) gisAllPreset.set(p.awPreset); if (p.awMulti !== undefined) gisAllMulti.set(p.awMulti); if (p.awSpec !== undefined) gisAllSpec.set(p.awSpec); if (p.awOutlier !== undefined) gisAllOutlier.set(p.awOutlier); if (p.awReset) gisAllExcl.set(''); if (p.awToggle !== undefined) { const ex = parseExcl(awExclRaw); if (ex.has(p.awToggle)) ex.delete(p.awToggle); else ex.add(p.awToggle); gisAllExcl.set([...ex].join(',')) } if (p.pins) gisPins.set(Object.entries(p.pins).map(([w, d]) => `${w}:${d}`).join(',')) } }} atlas={{ items: atlasItems, pick: atlasPick, agg: atlasAggV, paint: atlasData, onPick: (p, ag) => { atlasParam.set(p); atlasAgg.set(ag) } }} g={g} calc={calc} kind={kind} season={season} a={a} b={b} selected={selected} onSelect={pick} group={group} onGroup={setGroup} title={title} tipHost={insp && tmode === 'dock' ? tipDock : null} multi={multi}
            options={{ sectors: sec, water, share, fixed, paint, scale: bscale, labels, hideIdle: idleOff, minValue: minV }}
            onOptions={o => { if (o.sectors) sectors.set(o.sectors); if (o.water !== undefined) showWater.set(o.water); if (o.share !== undefined) showShare.set(o.share); if (o.fixed !== undefined) fixedScale.set(o.fixed); if (o.paint) { paintMode.set(o.paint); if (o.paint === 'ref' && app && app.gsps.length > 1) lastGsp.set(ALL_GSP) }; if (o.scale !== undefined) bubbleScale.set(o.scale); if (o.labels) labelMode.set(o.labels); if (o.hideIdle !== undefined) hideIdle.set(o.hideIdle); if (o.minValue !== undefined) minValue.set(o.minValue) }} />
          <Timeline g={g} calc={calc} a={a} b={b} setWindow={setWindow} />
        </div>
        {insp && <div className="side-col"><SideGrip />{tmode === 'dock' && <div className="tip-dock" ref={setTipDock} aria-live="polite" />}<Inspector g={g} calc={calc} prev={prev} prevKey={prevKey} kind={kind} season={season} a={a} b={b} selected={selected} onSelect={pick} group={group} onGroup={setGroup} onFocus={w => map.current?.focus(w)} /></div>}
      </div>)
  }
  const showBar = ready && !!g && page !== 'data'
  return (
    <div className={'shell' + (collapsed ? ' collapsed' : '')}>
      <aside className="sidebar">
        <div className="brand">
          <a href="#/" className="brand-link"><span className="brand-mark" aria-hidden="true" /><span className="brand-name">Карты</span></a>
          <button type="button" className="side-toggle" onClick={() => sidebarCollapsed.set(!collapsed)} aria-expanded={!collapsed} title={collapsed ? 'Показать меню' : 'Свернуть меню'}>
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d={collapsed ? 'M6 3.5 10.5 8 6 12.5' : 'M10 3.5 5.5 8 10 12.5'} /></svg></button>
        </div>
        <nav aria-label="Разделы"><ul>{groupedNav.map(p => (
          <li key={p.id}><a href={'#/' + p.id} aria-current={p.id === page ? 'page' : undefined} title={p.title}>
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d={p.icon} /></svg><span className="side-label">{p.title}</span></a></li>))}</ul></nav>
        <div className="theme-switch segmented" role="radiogroup" aria-label="Тема">
          {([['light', 'Светлая'], ['dark', 'Тёмная'], ['system', 'Авто']] as [Theme, string][]).map(([t, label]) => (
            <button key={t} type="button" role="radio" aria-checked={currentTheme === t} onClick={() => theme.set(t)} title={t === 'system' ? 'Как в системе' : label + ' тема'}>
              {t === 'light' ? <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" /></svg>
                : t === 'dark' ? <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5Z" /></svg>
                : <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="3" width="12" height="8" rx="1" /><path d="M6 13.5h4" /></svg>}
              <span className="side-label">{label}</span></button>))}
        </div>
      </aside>
      <main className={'workspace' + (page === 'map' || page === 'compare' ? ' wide' : '')}>
        {showBar && (
          <div className="topbar">
            <details className="sel group-pick" ref={groupRef}>
              <summary><span>ГСП</span><b>{wholeField ? (selGroups.length === app!.gsps.length ? 'Весь объект' : selGroups.join(', ')) : gsp}</b></summary>
              <div className="group-menu" role="group" aria-label="Группы">
                {app!.gsps.map(n => (
                  <label key={n} className="check"><input type="checkbox" checked={selGroups.includes(n)} onChange={() => toggleGroup(n)} />
                    {wholeField && <i className="gdot" style={{ background: groupColor(n) }} />}{n}{!app!.gspMeta[n]?.grid && !app!.gspMeta[n]?.xy ? ' · нет карты' : ''}</label>))}
                {app!.gsps.length > 1 && <div className="group-menu-row"><button type="button" className="quiet" onClick={() => lastGsp.set(nameOf(app!.gsps))}>Все группы</button>
                  <button type="button" className="quiet" onClick={() => lastGsp.set(selGroups[0])} disabled={selGroups.length < 2}>Только первая</button></div>}
              </div>
            </details>
            {app!.gsps.length > 1 && <GroupColorsButton groups={app!.gsps} onChange={() => setColorTick(n => n + 1)} />}
            <div className="segmented" role="radiogroup" aria-label="Вид">
              {['Отбор', 'Закачка'].map(k => <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => lastKind.set(k)}>{k}</button>)}</div>
            {page !== 'compare' && <label className="sel"><span>Сезон</span>
              <select value={season} onChange={e => setSeasonKey(e.target.value)}>{seasons.map(s => <option key={s.key}>{s.key}</option>)}</select></label>}
            {page === 'compare' && <><span className="spacer" /><button type="button" className="quiet" onClick={() => tipMode.set(tmode === 'dock' ? 'float' : 'dock')} title="Подсказка при наведении: в панели сведений или плавающая у курсора">{tmode === 'dock' ? 'Подсказка: в панели' : 'Подсказка: плавающая'}</button><button type="button" className="quiet" onClick={() => inspectorOpen.set(!insp)} aria-pressed={insp} title="Панель сравнения">Сведения</button></>}
            {page === 'map' && <>
              <input className="find" inputMode="numeric" placeholder="Скважина №" aria-label="Найти скважину" value={find} onChange={e => goFind(e.target.value)} />
              <span className="spacer" />
              {g && <Issues notes={g.layout.notes} warnings={g.warnings} />}
              <details className="export-menu" ref={exportRef}>
                <summary><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v8M4.5 6.5 8 10l3.5-3.5M2.5 11v2.5h11V11" /></svg>{batch ? `PNG ${batch.i + 1}/${batch.keys.length}` : 'Выгрузка'}</summary>
                <div className="menu" onClick={() => exportRef.current?.removeAttribute('open')}>
                  <button type="button" onClick={excel}>Excel<small>Таблицы сезона, доли, давление</small></button>
                  <button type="button" onClick={png}>Картинка карты<small>PNG текущего вида</small></button>
                  <button type="button" onClick={pngAll} disabled={!!batch}>Картинки всех сезонов<small>PNG по каждому сезону вида</small></button>
                </div>
              </details>
              <button type="button" className="quiet" onClick={() => tipMode.set(tmode === 'dock' ? 'float' : 'dock')} title="Подсказка при наведении: в панели сведений или плавающая у курсора">{tmode === 'dock' ? 'Подсказка: в панели' : 'Подсказка: плавающая'}</button>
              <button type="button" className="quiet" onClick={() => inspectorOpen.set(!insp)} aria-pressed={insp} title="Панель сведений">Сведения</button>
            </>}
          </div>)}
        {note && <div className="note info" role="status">{note}</div>}
        {body()}
      </main>
    </div>
  )
}
