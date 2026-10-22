import { useEffect, useRef, useState } from 'react'
import PageHead from './PageHead'
import GwcCompare from './GwcCompare'
import { FactWell, ModelEntry, WellProfile, getModels, getPlanshetFact, getSources, getWellProfile, pickFile, pickFolder, setSources } from './api'

const fmt = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const tail = (path: string) => path.split(/[\\/]/).filter(Boolean).slice(-2).join('/')

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

interface WellOut { fact: FactWell; profiles: { model: ModelEntry; p: WellProfile | null; stepDate: string; err?: string }[] }

export default function Planshet() {
  const [gisFolder, setGisFolder] = useState('')
  const [perfFile, setPerfFile] = useState('')
  const [well, setWell] = useState('')
  const [date, setDate] = useState('')
  const [thr, setThr] = useState('0.01')
  const [models, setModels] = useState<ModelEntry[]>([])
  const [wellsOut, setWellsOut] = useState<WellOut[]>([])
  const [zFrom, setZFrom] = useState('')
  const [zTo, setZTo] = useState('')
  const [alts, setAlts] = useState<Record<string, string>>({})      // альтитуда вручную по скважинам
  const [hand, setHand] = useState<Record<string, string>>({})      // свой ГВК вручную по скважинам, м а.о.
  const [hidden, setHidden] = useState<string[]>([])                // скрытые модели
  const boxRef = useRef<HTMLDivElement>(null)
  const [dates, setDates] = useState<string[]>([])
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
    const ws = Array.from(new Set(well.split(/[;,|\s]+/).map(x => x.trim()).filter(Boolean)))
    if (!ws.length) throw new Error('Введите номера скважин через запятую')
    const f = await getPlanshetFact(ws, d, alts)
    setNotes([...f.notes, ...f.rows.flatMap(r => r.notes.map(n => 'Скв. ' + r.well + ': ' + n))])
    const all = Array.from(new Set(f.rows.flatMap(r => r.dates))).sort()
    setDates(all)
    // профили моделей: один запрос на модель и дату среза сразу для всех скважин этой даты (сетка читается один раз)
    const out: WellOut[] = f.rows.map(row => ({ fact: row, profiles: [] }))
    const byDate: Record<string, WellOut[]> = {}
    out.forEach(o => { (byDate[o.fact.date || d] = byDate[o.fact.date || d] || []).push(o) })
    for (const m of models) {
      for (const [day, group] of Object.entries(byDate)) {
        try {
          const r = await getWellProfile(m.id, group.map(g => g.fact.well), day, thr.replace(',', '.'))
          group.forEach(g => g.profiles.push({ model: m, p: r.rows.find(x => x.well === g.fact.well) || null, stepDate: r.step_date }))
        } catch (e) { group.forEach(g => g.profiles.push({ model: m, p: null, stepDate: '', err: (e as Error).message })) }
      }
    }
    setWellsOut(out)
  })

  const handGwc = (w: string) => { const z = Number((hand[w] || '').replace(',', '.')); return hand[w] && !isNaN(z) ? [{ label: 'ручн.', z }] : [] }
  const tracksOf = ({ fact, profiles }: WellOut): Track[] => {
    const tr: Track[] = [{ title: 'ГИС, факт', sub: 'Кг по интервалам' + (fact.date ? ' · ' + fact.date : ''),
      bars: fact.intervals.filter(i => i.kg !== null).map(i => ({ top: i.top, bottom: i.bottom, v: i.kg as number })),
      gwc: [...fact.packs.map(p => ({ label: 'ГВК', z: p.gvk })), ...handGwc(fact.well)], note: fact.intervals.length ? undefined : 'нет интервалов' }]
    profiles.filter(x => !hidden.includes(x.model.id)).forEach(({ model, p, stepDate, err }) => tr.push({
      title: model.name, sub: err ? 'ошибка' : 'Sg · шаг ' + (stepDate || '—'),
      bars: (p?.cells || []).map(c => ({ top: c.top, bottom: c.bottom, v: c.sg })),
      gwc: p?.gwc ? [{ label: 'ГВК', z: p.gwc.cell }, { label: 'ГВК инт.', z: p.gwc.interp }] : [], note: err ? err.slice(0, 28) : p ? undefined : 'нет ячеек скважины' }))
    return tr
  }
  const trackSets = wellsOut.map(tracksOf)
  // одна шкала глубины на все скважины: по общему диапазону данных и перфораций, если не задана вручную
  const zs = trackSets.flatMap(ts => ts.flatMap(t => [...t.bars.flatMap(b => [b.top, b.bottom]), ...t.gwc.map(g => g.z).filter((z): z is number => z !== null)]))
    .concat(wellsOut.flatMap(o => (o.fact.perforation ? [o.fact.perforation.top, o.fact.perforation.bottom].filter((z): z is number => z !== null) : [])))
  const auto: [number, number] = zs.length ? [Math.floor(Math.min(...zs) / 10) * 10 - 10, Math.ceil(Math.max(...zs) / 10) * 10 + 10] : [-1000, 0]
  const zMin = zFrom !== '' && !isNaN(Number(zFrom)) ? Number(zFrom) : auto[0]
  const zMax = zTo !== '' && !isNaN(Number(zTo)) ? Number(zTo) : auto[1]
  const gwcOf = (t: Track) => t.gwc.map(g => g.z).filter((z): z is number => z !== null)

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
          <input style={{ width: 240 }} placeholder="скважины через запятую" value={well} onChange={e => setWell(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') build('') }} />
          <button className="primary" disabled={busy || !gisFolder} onClick={() => build('')}>Построить</button>
          {dates.length > 0 && <><span className="muted small">Замер:</span>
            <select value={date} onChange={e => { setDate(e.target.value); build(e.target.value) }}>
              <option value="">последний у каждой скважины</option>{dates.map(d => <option key={d}>{d}</option>)}</select></>}
          <span className="muted small">Порог Sg:</span><input style={{ width: 60 }} value={thr} onChange={e => setThr(e.target.value)} />
          <span className="muted small">Шкала, м от:</span><input style={{ width: 70 }} placeholder="авто" value={zFrom} onChange={e => setZFrom(e.target.value)} />
          <span className="muted small">до:</span><input style={{ width: 70 }} placeholder="авто" value={zTo} onChange={e => setZTo(e.target.value)} />
        </div>
        {msg && <p className="note warn">{msg}</p>}
        {notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
        {wellsOut.length > 0 && <div style={{ overflowX: 'auto', marginTop: 12 }}>
          <div className="row small" style={{ flexWrap: 'wrap' }}>
            <span className="muted">Вручную (последнее слово за инженером):</span>
            {wellsOut.map(o => <span key={o.fact.well}>Скв. {o.fact.well}: альтитуда <input style={{ width: 70 }} placeholder={fmt(o.fact.altitude)} value={alts[o.fact.well] || ''} onChange={e => setAlts({ ...alts, [o.fact.well]: e.target.value })} />
              {' '}свой ГВК <input style={{ width: 70 }} placeholder="м а.о." value={hand[o.fact.well] || ''} onChange={e => setHand({ ...hand, [o.fact.well]: e.target.value })} /></span>)}
            <button disabled={busy} onClick={() => build(date)} title="Пересчитать отметки с заданными альтитудами">Применить альтитуды</button>
            {models.map(m => <label key={m.id}><input type="checkbox" checked={!hidden.includes(m.id)} onChange={() => setHidden(hidden.includes(m.id) ? hidden.filter(x => x !== m.id) : [...hidden, m.id])} /> {m.name}</label>)}
            <button onClick={() => savePng(boxRef.current, 'планшет_ГВК')}>Сохранить PNG</button>
          </div>
          <div ref={boxRef} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            {wellsOut.map((o, i) => <WellLog key={o.fact.well} name={o.fact.well} tracks={trackSets[i]} perf={o.fact.perforation} zMin={zMin} zMax={zMax} h={560} />)}
          </div>
          <p className="muted small">Глубины — абсолютные отметки, вниз — меньше (со знаком минус); шкала глубины и шкалы 0…1 одинаковые у всех скважин. Узкая полоса слева — перфорация.
            Линия цвета воды — ГВК: у факта по пачкам из базы ГИС, у модели — как в «Результатах расчёта → ГВК по скважинам»: сверху вниз, граница ячейки (сплошная) и интерполяция Sg (пунктир); газ — Sg выше критической SGCR из INIT, иначе порога. Порог применяется при «Построить».</p>
          {wellsOut.length > 1 && <table className="raw"><thead><tr><th>Скважина</th><th>Замер</th><th>Альтитуда, м</th><th>ГВК факт, м</th>{models.filter(m => !hidden.includes(m.id)).map(m => <th key={m.id}>ГВК {m.name}, м</th>)}</tr></thead>
            <tbody>{wellsOut.map((o, i) => <tr key={o.fact.well}><td>{o.fact.well}</td><td>{o.fact.date || '—'}</td><td className="num">{fmt(o.fact.altitude)}</td>
              {trackSets[i].map((t, k) => <td key={k} className="num">{gwcOf(t).length ? gwcOf(t).map(z => fmt(z)).join('; ') : '—'}</td>)}</tr>)}</tbody></table>}
        </div>}
      </section>
      <GwcCompare models={models} thr={thr} alts={alts} />
    </main>
  )
}
