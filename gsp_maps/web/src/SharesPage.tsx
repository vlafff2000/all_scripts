import { useEffect, useMemo, useState } from 'react'
import { getWork, type GspData, type WorkData } from './api'
import { fmt1, fmtPct } from './model'

type Tab = 'wells' | 'dirs'
const PALETTE = ['#0072b2', '#e69f00', '#009e73', '#cc79a7', '#56b4e9', '#d55e00', '#8c564b', '#6a3d9a', '#1b9e77', '#e7298a']
const OTHER = '#aab5b9'
const DIR_ORDER = ['Север', 'Северо-Восток', 'Восток', 'Юго-Восток', 'Юг', 'Юго-Запад', 'Запад', 'Северо-Запад']
const DIR_COLOR: Record<string, string> = { 'Север': '#0072b2', 'Северо-Восток': '#56b4e9', 'Восток': '#009e73', 'Юго-Восток': '#e69f00', 'Юг': '#d55e00', 'Юго-Запад': '#cc79a7', 'Запад': '#6a3d9a', 'Северо-Запад': '#8c564b' }

interface Part { name: string; color: string; v: number; label: string }
function Stacked({ cols, hover, setHover }: { cols: { key: string; parts: Part[] }[]; hover: string | null; setHover: (s: string | null) => void }) {
  const W = 1000, H = 300, L = 44, B = 30, T = 8
  const bw = Math.min(46, ((W - L - 8) / Math.max(1, cols.length)) * 0.72), step = (W - L - 8) / Math.max(1, cols.length)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="pchart" role="img" aria-label="Доли по сезонам">
      {[0, 25, 50, 75, 100].map(v => { const y = T + (1 - v / 100) * (H - T - B); return <g key={v}><line x1={L} x2={W - 8} y1={y} y2={y} className="grid" /><text x={L - 6} y={y} textAnchor="end" dominantBaseline="central" className="ax">{v}%</text></g> })}
      {cols.map((c, i) => {
        let acc = 0
        const x = L + i * step + (step - bw) / 2
        return (
          <g key={c.key}>
            {c.parts.map(p => {
              const h = p.v * (H - T - B), y = T + (1 - acc - p.v) * (H - T - B)
              acc += p.v
              return <rect key={p.name} x={x} y={y} width={bw} height={Math.max(0, h)} fill={p.color} stroke="var(--surface)" strokeWidth={0.8} opacity={hover && hover !== p.name ? 0.35 : 1}
                onPointerEnter={() => setHover(p.name)} onPointerLeave={() => setHover(null)}><title>{`${c.key} · ${p.name}: ${p.label}`}</title></rect>
            })}
            <text x={x + bw / 2} y={H - 12} textAnchor="middle" className="ax">{c.key}</text>
          </g>)
      })}
    </svg>
  )
}

function LineShare({ keys, vals, name }: { keys: string[]; vals: (number | null)[]; name: string }) {
  const W = 1000, H = 220, L = 44, B = 30, T = 10
  const mx = Math.max(1e-9, ...vals.map(v => v ?? 0)) * 1.15
  const x = (i: number) => L + ((i + 0.5) / Math.max(1, keys.length)) * (W - L - 8)
  const y = (v: number) => T + (1 - v / mx) * (H - T - B)
  const pts = vals.map((v, i) => (v === null ? null : [x(i), y(v)] as [number, number]))
  const d = pts.filter(Boolean).map((p, i) => (i ? 'L' : 'M') + p![0].toFixed(1) + ',' + p![1].toFixed(1)).join('')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="pchart" role="img" aria-label={`Доля скважины ${name} по сезонам`}>
      {[0, 0.5, 1].map(f => { const v = (mx / 1.15) * f; return <g key={f}><line x1={L} x2={W - 8} y1={y(v)} y2={y(v)} className="grid" /><text x={L - 6} y={y(v)} textAnchor="end" dominantBaseline="central" className="ax">{fmt1(v * 100)}%</text></g> })}
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={2} />
      {pts.map((p, i) => p && <g key={i}><circle cx={p[0]} cy={p[1]} r={4} fill="var(--accent)" stroke="var(--surface)" /><title>{`${keys[i]}: ${fmtPct(vals[i]!)}`}</title></g>)}
      {keys.map((k, i) => <text key={k} x={x(i)} y={H - 10} textAnchor="middle" className="ax">{k}</text>)}
    </svg>
  )
}

export default function SharesPage({ g, kind, selected, onSelect }: { g: GspData; kind: string; selected: number | null; onSelect: (w: number | null) => void }) {
  const [tab, setTab] = useState<Tab>('wells')
  const [data, setData] = useState<WorkData | null>(null)
  const [err, setErr] = useState('')
  const [hover, setHover] = useState<string | null>(null)
  useEffect(() => { setData(null); getWork(g.gsp).then(setData).catch(e => setErr(String(e.message || e))) }, [g.gsp])

  const m = useMemo(() => {
    if (!data) return null
    const seasons = data.seasons.filter(s => s.kind === kind && s.total.some(v => v > 0))
    const sums = seasons.map(s => s.total.reduce((a, v) => a + Math.max(0, v), 0))
    const share = data.wells.map((_w, i) => seasons.map((s, j) => (sums[j] > 0 ? Math.max(0, s.total[i]) / sums[j] : null)))
    const avg = share.map((row, i) => { const t = seasons.reduce((a, s) => a + Math.max(0, s.total[i]), 0), all = sums.reduce((a, v) => a + v, 0); void row; return all > 0 ? t / all : 0 })
    const dirOf = (w: number) => g.layout.wells[String(w)]?.dir || 'Без положения'
    const dirNames = [...new Set(data.wells.map(dirOf))].sort((p, q) => (DIR_ORDER.indexOf(p) + 99) % 99 - (DIR_ORDER.indexOf(q) + 99) % 99)
    const dirShare = dirNames.map(d => seasons.map((_s, j) => (sums[j] > 0 ? data.wells.reduce((a, w, i) => a + (dirOf(w) === d ? Math.max(0, seasons[j].total[i]) : 0), 0) / sums[j] : 0)))
    const dirWells = dirNames.map(d => data.wells.filter(w => dirOf(w) === d).length)
    return { seasons, share, avg, dirNames, dirShare, dirWells }
  }, [data, kind, g])

  const top = useMemo(() => m && data ? [...data.wells.keys()].sort((p, q) => m.avg[q] - m.avg[p]).slice(0, 10) : [], [m, data])
  const well = selected !== null && data?.wells.includes(selected) ? selected : top.length && data ? data.wells[top[0]] : null

  return (
    <section className="card work">
      <div className="work-head">
        <div className="segmented" role="tablist" aria-label="Доли">
          <button type="button" role="tab" aria-selected={tab === 'wells'} onClick={() => setTab('wells')}>Скважины по сезонам</button>
          <button type="button" role="tab" aria-selected={tab === 'dirs'} onClick={() => setTab('dirs')}>Направления</button></div>
        <span className="muted">{g.gsp} · {kind}: доля скважины в суммарном расходе ГСП за сезон</span>
      </div>
      {err && <div className="note warning">{err}</div>}
      {!data && !err && <p className="muted">Считаю…</p>}
      {data && m && !m.seasons.length && <p className="muted">В этом виде нет сезонов с расходом.</p>}
      {data && m && m.seasons.length > 0 && tab === 'wells' && <>
        <Legend items={[...top.map((i, n) => ({ name: String(data.wells[i]), color: PALETTE[n] })), { name: 'остальные', color: OTHER }]} hover={hover} setHover={setHover} />
        <Stacked hover={hover} setHover={setHover} cols={m.seasons.map((s, j) => {
          const parts: Part[] = top.map((i, n) => ({ name: String(data.wells[i]), color: PALETTE[n], v: m.share[i][j] ?? 0, label: fmtPct(m.share[i][j] ?? 0) }))
          const rest = Math.max(0, 1 - parts.reduce((a, p) => a + p.v, 0))
          return { key: s.key, parts: [...parts, { name: 'остальные', color: OTHER, v: rest, label: fmtPct(rest) }] }
        })} />
        {well !== null && <>
          <h3>Доля скважины {well} по сезонам</h3>
          <LineShare keys={m.seasons.map(s => s.key)} vals={m.share[data.wells.indexOf(well)]} name={String(well)} />
        </>}
        <h3>Таблица долей, % (нажмите на строку, чтобы выбрать скважину)</h3>
        <div className="scroll"><table className="matrix shares">
          <thead><tr><th className="stick">Скв.</th><th className="mo">Напр.</th>{m.seasons.map(s => <th key={s.key} className="mo">{s.key}</th>)}<th className="mo">Всего</th></tr></thead>
          <tbody>{[...data.wells.keys()].sort((p, q) => m.avg[q] - m.avg[p]).map(i => (
            <tr key={data.wells[i]} className={well === data.wells[i] ? 'cur' : ''} onClick={() => onSelect(data.wells[i])}>
              <th className="stick">{data.wells[i]}</th><td className="dir">{g.layout.wells[String(data.wells[i])]?.dir || ''}</td>
              {m.share[i].map((v, j) => <td key={j} style={{ background: v ? `color-mix(in srgb, var(--accent) ${Math.round(Math.min(1, v / 0.08) * 70)}%, transparent)` : undefined }}>{v === null ? '' : v > 0 ? fmt1(v * 100) : '0'}</td>)}
              <td><b>{fmt1(m.avg[i] * 100)}</b></td></tr>))}</tbody>
        </table></div>
      </>}
      {data && m && m.seasons.length > 0 && tab === 'dirs' && <>
        <Legend items={m.dirNames.map(d => ({ name: d, color: DIR_COLOR[d] || OTHER }))} hover={hover} setHover={setHover} />
        <Stacked hover={hover} setHover={setHover} cols={m.seasons.map((s, j) => ({ key: s.key, parts: m.dirNames.map((d, k) => ({ name: d, color: DIR_COLOR[d] || OTHER, v: m.dirShare[k][j], label: fmtPct(m.dirShare[k][j]) })) }))} />
        <div className="scroll"><table className="matrix shares">
          <thead><tr><th className="stick">Направление</th><th className="mo">Скважин</th>{m.seasons.map(s => <th key={s.key} className="mo">{s.key}</th>)}</tr></thead>
          <tbody>{m.dirNames.map((d, k) => (
            <tr key={d}><th className="stick dirname"><i style={{ background: DIR_COLOR[d] || OTHER }} />{d}</th><td>{m.dirWells[k]}</td>
              {m.dirShare[k].map((v, j) => <td key={j} style={{ background: v ? `color-mix(in srgb, var(--accent) ${Math.round(Math.min(1, v / 0.4) * 70)}%, transparent)` : undefined }}>{fmt1(v * 100)}</td>)}</tr>))}</tbody>
        </table></div>
        <p className="muted hint">Направления считаются по положению скважин (сетка — по четвертям листа, XY — по азимуту от центра), см. страницу «Данные».</p>
      </>}
    </section>
  )
}

function Legend({ items, hover, setHover }: { items: { name: string; color: string }[]; hover: string | null; setHover: (s: string | null) => void }) {
  return <div className="p-legend share-legend">{items.map(it => (
    <span key={it.name} className={hover === it.name ? 'on' : ''} onPointerEnter={() => setHover(it.name)} onPointerLeave={() => setHover(null)}><i style={{ background: it.color, height: 10, width: 14 }} />{it.name}</span>))}</div>
}
