import { useEffect, useState } from 'react'
import PageHead from './PageHead'
import { FactWell, ModelEntry, WellProfile, getModels, getPlanshetFact, getSources, getWellProfile, pickFile, pickFolder, setSources } from './api'

const fmt = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const tail = (path: string) => path.split(/[\\/]/).filter(Boolean).slice(-2).join('/')

/** ГВК модели по колонне: низ газовой пачки от кровли газа (первый переход газ → не газ), Sg выше порога. */
export function modelGwc(cells: WellProfile['cells'], thr: number): number | null {
  const i = cells.findIndex(c => c.sg > thr)
  if (i < 0) return null
  let k = i
  while (k + 1 < cells.length && cells[k + 1].sg > thr && Math.abs(cells[k + 1].top - cells[k].bottom) < 0.5) k++
  return cells[k].bottom
}

interface Track { title: string; sub: string; gwc: { label: string; z: number | null }[]; bars: { top: number; bottom: number; v: number }[]; note?: string }

const W = 150, PAD = 8, AXIS = 56, HEAD = 46

/** Одна скважина: ось глубины (а.о., вниз — меньше) и треки с общей шкалой 0…1; перфорация — полоса слева. */
function WellLog({ name, tracks, perf, zMin, zMax, h }: { name: string; tracks: Track[]; perf: { top: number | null; bottom: number | null } | null; zMin: number; zMax: number; h: number }) {
  const y = (z: number) => HEAD + ((zMax - z) / (zMax - zMin)) * h
  const step = [1, 2, 5, 10, 20, 50, 100].find(s => (zMax - zMin) / s <= 14) || 100
  const ticks: number[] = []
  for (let z = Math.ceil(zMin / step) * step; z <= zMax; z += step) ticks.push(z)
  const width = AXIS + 16 + tracks.length * (W + PAD)
  return (
    <svg width={width} height={HEAD + h + 8} role="img" aria-label={'Планшет скважины ' + name} style={{ background: 'var(--chart-surface)', border: '1px solid var(--line)', borderRadius: 6 }}>
      <text x={6} y={14} fill="var(--chart-ink)" fontWeight={700} fontSize={13}>Скв. {name}</text>
      {ticks.map(z => <g key={z}><line x1={AXIS} x2={width} y1={y(z)} y2={y(z)} stroke="var(--chart-grid)" /><text x={AXIS - 6} y={y(z) + 4} textAnchor="end" fontSize={11} fill="var(--chart-muted)">{z}</text></g>)}
      <text x={6} y={HEAD - 6} fontSize={10} fill="var(--chart-muted)">м, а.о.</text>
      {perf && perf.top !== null && perf.bottom !== null && <g>
        <rect x={AXIS + 2} width={9} y={y(Math.max(perf.top, perf.bottom))} height={Math.max(2, Math.abs(y(perf.top) - y(perf.bottom)))} fill="var(--chart-accent)" opacity={0.85}>
          <title>{'Перфорация: ' + fmt(perf.top) + ' … ' + fmt(perf.bottom) + ' м'}</title></rect></g>}
      {tracks.map((t, i) => {
        const x0 = AXIS + 16 + i * (W + PAD)
        return <g key={i}>
          <text x={x0} y={HEAD - 20} fontSize={11} fontWeight={700} fill="var(--chart-ink)">{t.title}</text>
          <text x={x0} y={HEAD - 8} fontSize={10} fill="var(--chart-muted)">{t.sub}</text>
          <rect x={x0} y={HEAD} width={W} height={h} fill="none" stroke="var(--chart-axis)" />
          {t.bars.map((b, k) => <rect key={k} x={x0} width={Math.max(0, Math.min(1, b.v)) * W} y={y(b.top)} height={Math.max(1, y(b.bottom) - y(b.top))} fill="var(--map-gas)" opacity={0.8} stroke="var(--chart-surface)" strokeWidth={0.5}>
            <title>{fmt(b.top) + ' … ' + fmt(b.bottom) + ' м: ' + fmt(b.v, 2)}</title></rect>)}
          {t.gwc.map((g, k) => g.z === null ? null : <g key={k}>
            <line x1={x0} x2={x0 + W} y1={y(g.z)} y2={y(g.z)} stroke="var(--map-water)" strokeWidth={2.5} strokeDasharray={k ? '5 3' : undefined} />
            <text x={x0 + W - 3} y={y(g.z) - 3} textAnchor="end" fontSize={10} fill="var(--chart-ink)">{g.label + ' ' + fmt(g.z)}</text></g>)}
          {t.note && <text x={x0 + 4} y={HEAD + 14} fontSize={10} fill="var(--chart-muted)">{t.note}</text>}
        </g>
      })}
    </svg>
  )
}

export default function Planshet() {
  const [gisFolder, setGisFolder] = useState('')
  const [perfFile, setPerfFile] = useState('')
  const [well, setWell] = useState('')
  const [date, setDate] = useState('')
  const [thr, setThr] = useState('0.01')
  const [models, setModels] = useState<ModelEntry[]>([])
  const [fact, setFact] = useState<FactWell | null>(null)
  const [profiles, setProfiles] = useState<{ model: ModelEntry; p: WellProfile | null; stepDate: string; err?: string }[]>([])
  const [zFrom, setZFrom] = useState('')
  const [zTo, setZTo] = useState('')
  const [notes, setNotes] = useState<string[]>([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getSources().then(v => { setGisFolder(v.sources.gis?.folder || ''); setPerfFile(v.sources.gis?.perf_file || '') }).catch(() => undefined)
    getModels().then(v => setModels(v.models.filter(m => m.selected))).catch(e => setMsg((e as Error).message))
  }, [])
  const guard = async (f: () => Promise<void>) => { setBusy(true); setMsg(''); try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) } }
  const saveGis = (folder: string, perf: string) => guard(async () => { await setSources({ gis: { folder, perf_file: perf } }); setGisFolder(folder); setPerfFile(perf) })
  const pickGis = async () => { const f = await pickFolder(gisFolder); if (f) await saveGis(f, perfFile) }
  const pickPerf = async () => { const r = await pickFile(perfFile); if (r.path) await saveGis(gisFolder, r.path) }

  const build = (d: string) => guard(async () => {
    const w = well.trim()
    if (!w) throw new Error('Введите номер скважины')
    const f = await getPlanshetFact([w], d)
    const row = f.rows[0]
    setFact(row); setNotes([...f.notes, ...row.notes])
    if (!d && row.date) setDate(row.date)
    const out: typeof profiles = []
    for (const m of models) {
      try {
        const r = await getWellProfile(m.id, [w], row.date || d)
        out.push({ model: m, p: r.rows[0] || null, stepDate: r.step_date })
      } catch (e) { out.push({ model: m, p: null, stepDate: '', err: (e as Error).message }) }
    }
    setProfiles(out)
  })

  const th = Number(thr.replace(',', '.')) || 0.01
  const tracks: Track[] = []
  if (fact) {
    tracks.push({ title: 'ГИС, факт', sub: 'Кг по интервалам' + (fact.date ? ' · ' + fact.date : ''),
      bars: fact.intervals.filter(i => i.kg !== null).map(i => ({ top: i.top, bottom: i.bottom, v: i.kg as number })),
      gwc: fact.packs.map(p => ({ label: 'ГВК', z: p.gvk })), note: fact.intervals.length ? undefined : 'нет интервалов' })
  }
  profiles.forEach(({ model, p, stepDate, err }) => tracks.push({
    title: model.name, sub: err ? 'ошибка' : 'Sg · шаг ' + (stepDate || '—'),
    bars: (p?.cells || []).map(c => ({ top: c.top, bottom: c.bottom, v: c.sg })),
    gwc: p ? [{ label: 'ГВК', z: modelGwc(p.cells, th) }] : [], note: err ? err.slice(0, 28) : p ? undefined : 'нет ячеек скважины' }))
  const zs = tracks.flatMap(t => [...t.bars.flatMap(b => [b.top, b.bottom]), ...t.gwc.map(g => g.z).filter((z): z is number => z !== null)])
    .concat(fact?.perforation ? [fact.perforation.top, fact.perforation.bottom].filter((z): z is number => z !== null) : [])
  const auto: [number, number] = zs.length ? [Math.floor(Math.min(...zs) / 10) * 10 - 10, Math.ceil(Math.max(...zs) / 10) * 10 + 10] : [-1000, 0]
  const zMin = zFrom !== '' && !isNaN(Number(zFrom)) ? Number(zFrom) : auto[0]
  const zMax = zTo !== '' && !isNaN(Number(zTo)) ? Number(zTo) : auto[1]

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
        <p className="muted small">Модели: {models.length ? models.map(m => m.name).join(', ') : 'не отмечены — планшет покажет только факт'}</p>
      </section>
      <section className="card">
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <input style={{ width: 140 }} placeholder="скважина" value={well} onChange={e => setWell(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') build('') }} />
          <button className="primary" disabled={busy || !gisFolder} onClick={() => build('')}>Построить</button>
          {fact && fact.dates.length > 0 && <><span className="muted small">Замер:</span>
            <select value={date} onChange={e => { setDate(e.target.value); build(e.target.value) }}>{fact.dates.map(d => <option key={d}>{d}</option>)}</select></>}
          <span className="muted small">Порог Sg:</span><input style={{ width: 60 }} value={thr} onChange={e => setThr(e.target.value)} />
          <span className="muted small">Шкала, м от:</span><input style={{ width: 70 }} placeholder="авто" value={zFrom} onChange={e => setZFrom(e.target.value)} />
          <span className="muted small">до:</span><input style={{ width: 70 }} placeholder="авто" value={zTo} onChange={e => setZTo(e.target.value)} />
        </div>
        {msg && <p className="note warn">{msg}</p>}
        {notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {fact && tracks.length > 0 && <div style={{ overflowX: 'auto', marginTop: 12 }}>
          <WellLog name={fact.well} tracks={tracks} perf={fact.perforation} zMin={zMin} zMax={zMax} h={560} />
          <p className="muted small">Глубины — абсолютные отметки, вниз — меньше (со знаком минус). Узкая полоса слева — перфорация. Линия цвета воды — ГВК: у факта по пачкам из базы ГИС, у модели — низ газовой пачки от кровли газа при Sg выше порога.
            {fact.altitude !== null ? ' Альтитуда ' + fmt(fact.altitude) + ' м.' : ''}</p>
        </div>}
      </section>
    </main>
  )
}
