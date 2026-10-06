import Chart from './Chart'
import { useEffect, useMemo, useState } from 'react'
import { getWork, type GspData, type WorkData } from './api'
import { fmt1, fmtPct } from './model'

type Tab = 'wells' | 'dirs'
const PALETTE = ['#0072b2', '#e69f00', '#009e73', '#cc79a7', '#56b4e9', '#d55e00', '#8c564b', '#6a3d9a', '#1b9e77', '#e7298a']
const OTHER = '#aab5b9'
const DIR_ORDER = ['Север', 'Северо-Восток', 'Восток', 'Юго-Восток', 'Юг', 'Юго-Запад', 'Запад', 'Северо-Запад']
const DIR_COLOR: Record<string, string> = { 'Север': '#0072b2', 'Северо-Восток': '#56b4e9', 'Восток': '#009e73', 'Юго-Восток': '#e69f00', 'Юг': '#d55e00', 'Юго-Запад': '#cc79a7', 'Запад': '#6a3d9a', 'Северо-Запад': '#8c564b' }

interface Part { name: string; color: string; v: number; label: string }
function Stacked({ cols, hover }: { cols: { key: string; parts: Part[] }[]; hover: string | null; setHover: (s: string | null) => void }) {
  const names = [...new Set(cols.flatMap(c => c.parts.map(p => p.name)))]
  const series = names.map(n => ({ key: n, label: n, color: cols.flatMap(c => c.parts).find(p => p.name === n)!.color, y: cols.map(c => c.parts.find(p => p.name === n)?.v ?? 0) }))
  return <Chart mode="bars" stack highlight={hover} labels={cols.map(c => c.key)} fmt={v => fmt1(v * 100) + '%'} unit="" height={300} label="Доли по сезонам" series={series} />
}

function LineShare({ keys, vals, name }: { keys: string[]; vals: (number | null)[]; name: string }) {
  return <Chart mode="lines" labels={keys} fmt={v => fmt1(v * 100) + '%'} unit="" height={220} label={`Доля скважины ${name} по сезонам`}
    series={[{ key: 'v', label: 'Доля', color: 'var(--accent)', y: vals.map(v => v ?? 0) }]} />
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
