import { useEffect, useMemo, useState } from 'react'
import { ALL_GSP, getSeason, type GspData } from './api'
import { SeasonCalc, fmt1, fmtInt, fmtMln, fmtPct, fmtTh } from './model'

interface Props {
  g: GspData; calc: SeasonCalc; kind: string; season: string; a: number; b: number
  selected: number | null; onSelect: (w: number | null) => void; group: number[]
}

/** Все сезоны выбранного вида: нужны для динамики по сезонам. */
function useAllSeasons(g: GspData, kind: string) {
  const keys = (g.seasons[kind as 'Отбор' | 'Закачка'] || []).map(s => s.key).join('|')
  const [all, setAll] = useState<{ key: string; calc: SeasonCalc }[] | null>(null)
  useEffect(() => {
    setAll(null)
    let live = true
    const ks = keys ? keys.split('|') : []
    Promise.all(ks.map(k => getSeason(g.gsp, kind, k).then(d => ({ key: k, calc: new SeasonCalc(d) })))).then(r => { if (live) setAll(r) }).catch(() => { if (live) setAll([]) })
    return () => { live = false }
  }, [g.gsp, kind, keys])
  return all
}

const median = (v: number[]) => { if (!v.length) return 0; const s = [...v].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2 }
const seasonColor = (i: number, n: number) => (i === n - 1 ? 'var(--accent-strong)' : `color-mix(in srgb, var(--accent) ${Math.round(18 + (i / Math.max(1, n - 1)) * 52)}%, var(--line-strong))`)

/** Суммарный суточный ряд скважин группы за сезон. */
function dailyOf(c: SeasonCalc, wells: number[]) {
  const idx = wells.map(w => c.index.get(w)).filter((i): i is number => i !== undefined)
  const out = new Array(c.nd).fill(0)
  for (const i of idx) { const r = c.flow[i]; for (let j = 0; j < c.nd; j++) if (r[j] > 0) out[j] += r[j] }
  return { daily: out, n: idx.length }
}
const cumulative = (d: number[]) => { let s = 0; return d.map(v => (s += v)) }

const W = 560, H = 150, ML = 40, MR = 12, MT = 8, MB = 22
function Axis({ max, unit, fmt }: { max: number; unit: string; fmt: (v: number) => string }) {
  return (
    <>
      {[0, 0.5, 1].map(t => <g key={t}><line x1={ML} x2={W - MR} y1={MT + (1 - t) * (H - MT - MB)} y2={MT + (1 - t) * (H - MT - MB)} className="w-grid" />
        <text x={ML - 5} y={MT + (1 - t) * (H - MT - MB) + 3.5} textAnchor="end" className="w-t">{fmt(max * t)}</text></g>)}
      <text x={ML} y={MT - 1} className="w-t" dy={-1}>{unit}</text>
    </>
  )
}

function Bars({ items, unit, fmt, onPick, mark }: { items: { label: string; v: number; id?: number }[]; unit: string; fmt: (v: number) => string; onPick?: (id: number) => void; mark?: number | null }) {
  const max = Math.max(1e-9, ...items.map(i => i.v))
  const bw = (W - ML - MR) / Math.max(1, items.length)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-chart" role="img">
      <Axis max={max} unit={unit} fmt={fmt} />
      {items.map((it, k) => {
        const h = (it.v / max) * (H - MT - MB), x = ML + k * bw
        return (
          <g key={k} onClick={() => it.id !== undefined && onPick?.(it.id)} style={{ cursor: onPick ? 'pointer' : undefined }}>
            <title>{it.label + ': ' + fmt(it.v) + ' ' + unit}</title>
            <rect x={x + bw * 0.12} y={H - MB - h} width={bw * 0.76} height={Math.max(0, h)} rx={Math.min(3, bw * 0.2)} fill={mark !== undefined && mark === it.id ? 'var(--accent-strong)' : 'var(--map-gas)'} />
            {(items.length <= 14 || k % Math.ceil(items.length / 14) === 0) && <text x={x + bw / 2} y={H - 6} textAnchor="middle" className="w-t">{it.label}</text>}
          </g>
        )
      })}
      <line x1={ML} x2={W - MR} y1={H - MB} y2={H - MB} className="w-axis" />
    </svg>
  )
}

interface Line { name: string; ys: number[]; color: string; dash?: boolean; bold?: boolean }
function Lines({ lines, n, unit, fmt, win }: { lines: Line[]; n: number; unit: string; fmt: (v: number) => string; win?: [number, number] }) {
  const max = Math.max(1e-9, ...lines.flatMap(l => l.ys))
  const x = (j: number) => ML + ((j + 0.5) / Math.max(1, n)) * (W - ML - MR), y = (v: number) => MT + (1 - v / max) * (H - MT - MB)
  return (
    <svg viewBox={`0 0 ${W + 70} ${H}`} className="w-chart" role="img">
      <Axis max={max} unit={unit} fmt={fmt} />
      {win && <rect x={x(win[0]) - 1} width={Math.max(2, x(win[1]) - x(win[0]) + 2)} y={MT} height={H - MT - MB} className="daily-win" />}
      {lines.map((l, k) => l.ys.length > 0 && (
        <g key={k}>
          <path d={'M' + l.ys.map((v, j) => `${x(j).toFixed(1)},${y(v).toFixed(1)}`).join('L')} fill="none" stroke={l.color} strokeWidth={l.bold ? 2.4 : 1.5} strokeDasharray={l.dash ? '5 3' : undefined} strokeLinejoin="round" />
          <text x={x(l.ys.length - 1) + 4} y={y(l.ys[l.ys.length - 1]) + 3.5} className="w-t" style={{ fill: 'var(--ink)' }}>{l.name}</text>
        </g>))}
      <line x1={ML} x2={W - MR} y1={H - MB} y2={H - MB} className="w-axis" />
      <text x={ML} y={H - 6} className="w-t">день 1</text><text x={W - MR} y={H - 6} textAnchor="end" className="w-t">день {n}</text>
    </svg>
  )
}

export default function WellsPage({ g, calc, kind, season, a, b, selected, onSelect, group }: Props) {
  const all = useAllSeasons(g, kind)
  const picked = group.length > 1 ? group : []
  const [scopePref, setScope] = useState<'all' | 'group'>('all')
  const scope = scopePref === 'group' && picked.length > 1 ? 'group' : 'all'
  const wells = scope === 'group' ? picked.filter(w => calc.index.has(w)) : calc.wells
  const dir = (w: number) => g.layout.wells[String(w)]?.dir || ''
  const idxS = all ? all.findIndex(s => s.key === season) : -1
  const prev = all && idxS > 0 ? all[idxS - 1] : null

  const rows = useMemo(() => wells.map(w => {
    const i = calc.index.get(w)!, st = calc.stat(i, a, b), full = calc.stat(i, 0, calc.nd - 1)
    let d: number | null = null
    if (prev && prev.calc.index.has(w)) { const o = prev.calc.stat(prev.calc.index.get(w)!, 0, prev.calc.nd - 1).total; d = o > 0 ? full.total / o - 1 : null }
    return { w, total: st.total, mean: st.mean, days: st.days, full: full.total, d }
  }), [wells, calc, a, b, prev])
  const sum = rows.reduce((s, r) => s + Math.max(0, r.total), 0)
  const working = rows.filter(r => r.total > 0)
  const sorted = [...rows].sort((p, q) => q.total - p.total)
  const top5 = sorted.slice(0, 5).reduce((s, r) => s + Math.max(0, r.total), 0)

  // распределение скважин по объёму за окно
  const hist = useMemo(() => {
    const v = working.map(r => r.total), mx = Math.max(1, ...v), bins = 10, out = Array.from({ length: bins }, (_, k) => ({ label: fmtMln((mx / bins) * (k + 1)), v: 0 }))
    for (const x of v) out[Math.min(bins - 1, Math.floor((x / mx) * bins))].v++
    return out
  }, [working])

  // по сезонам
  const perSeason = useMemo(() => (all || []).map(s => {
    const { daily, n } = dailyOf(s.calc, wells), tot = daily.reduce((x, y) => x + y, 0)
    const per = wells.map(w => s.calc.index.get(w)).filter((i): i is number => i !== undefined).map(i => s.calc.stat(i, 0, s.calc.nd - 1).total).filter(v => v > 0)
    return { key: s.key, total: tot, n, work: per.length, mean: per.length ? tot / per.length : 0, med: median(per), cum: cumulative(daily) }
  }), [all, wells])
  const nmax = Math.max(1, ...perSeason.map(s => s.cum.length))

  // выбранная скважина против среднего по набору
  const one = selected !== null && calc.index.has(selected) ? selected : null
  const oneVs = useMemo(() => {
    if (one === null) return null
    const mine = cumulative(Array.from(calc.flow[calc.index.get(one)!], v => Math.max(0, v)))
    const others = wells.filter(w => w !== one)
    const { daily, n } = dailyOf(calc, others)
    const avg = cumulative(daily.map(v => (n ? v / n : 0)))
    return { mine, avg, last: mine[mine.length - 1] || 0, avgLast: avg[avg.length - 1] || 0 }
  }, [one, wells, calc])

  const scopeName = scope === 'group' ? `группа, ${wells.length} скв.` : `${g.gsp === ALL_GSP ? g.gsp : "весь " + g.gsp}, ${wells.length} скв.`
  return (
    <div className="wells-page">
      <div className="card wells-head">
        <div className="segmented" role="radiogroup" aria-label="Что анализировать">
          <button type="button" role="radio" aria-checked={scope === 'all'} onClick={() => setScope('all')}>Весь ГСП</button>
          <button type="button" role="radio" aria-checked={scope === 'group'} onClick={() => setScope('group')} disabled={picked.length < 2}
            title={picked.length < 2 ? 'Выберите группу на карте: Ctrl+клик или Shift+рамка' : ''}>Группа{picked.length > 1 ? ` (${picked.length})` : ''}</button>
        </div>
        <span className="muted">{kind} {season} · {scopeName} · окно сезона на странице «Карта»</span>
      </div>
      <div className="stat-grid wells-kpi">
        <div><span>Накоплено в окне</span><b>{fmtMln(sum)}</b><i>млн м³</i></div>
        <div><span>Работало скважин</span><b>{working.length}</b><i>из {rows.length}</i></div>
        <div><span>На скважину: среднее / медиана</span><b>{working.length ? fmtMln(sum / working.length) : '—'}</b><i>медиана {fmtMln(median(working.map(r => r.total)))} млн м³</i></div>
        <div><span>Доля пяти лучших</span><b>{sum > 0 ? fmtPct(top5 / sum) : '—'}</b><i>вклад лидеров</i></div>
      </div>
      <div className="wells-grid">
        <section className="card"><h3>Сколько скважин дают какой объём</h3><p className="muted hint">Объём скважины за окно, млн м³ (подписи — верх каждой корзины).</p>
          <Bars items={hist} unit="скв." fmt={v => String(Math.round(v))} /></section>
        <section className="card"><h3>Объём по сезонам</h3><p className="muted hint">Суммарный расход набора скважин за сезон, млн м³.</p>
          {all ? <Bars items={perSeason.map(s => ({ label: s.key.slice(2, 4) + '–' + s.key.slice(7), v: s.total / 1e6 }))} unit="млн м³" fmt={v => fmt1(v)} /> : <p className="muted">Загружаю сезоны…</p>}</section>
        <section className="card"><h3>Накопленный расход по дням от старта сезона</h3><p className="muted hint">Все сезоны набора на одной оси: видно, какой сезон шёл быстрее.</p>
          {all ? <Lines n={nmax} unit="млн м³" fmt={v => fmt1(v / 1e6)} win={[a, b]} lines={perSeason.map((s, k) => ({ name: s.key.slice(2, 4) + '–' + s.key.slice(7), ys: s.cum, color: seasonColor(k, perSeason.length), bold: k === perSeason.length - 1 || s.key === season }))} /> : <p className="muted">Загружаю сезоны…</p>}</section>
        <section className="card"><h3>Скважина в среднем по сезонам</h3><p className="muted hint">Объём на работающую скважину, млн м³: показывает, падает ли расход скважины, а не число скважин.</p>
          {all ? <Bars items={perSeason.map(s => ({ label: s.key.slice(2, 4) + '–' + s.key.slice(7), v: s.mean / 1e6 }))} unit="млн м³" fmt={v => fmt1(v)} /> : <p className="muted">Загружаю сезоны…</p>}</section>
        {oneVs && <section className="card wide"><h3>Скважина {one} против средней скважины набора</h3>
          <p className="muted hint">Накопленный расход сезона: скважина {one} — {fmtMln(oneVs.last)} млн м³, средняя из остальных — {fmtMln(oneVs.avgLast)} млн м³{oneVs.avgLast > 0 ? ' (' + fmtPct(oneVs.last / oneVs.avgLast) + ' от средней)' : ''}.</p>
          <Lines n={calc.nd} unit="млн м³" fmt={v => fmt1(v / 1e6)} win={[a, b]} lines={[{ name: 'сред.', ys: oneVs.avg, color: '#8a979c', dash: true }, { name: String(one), ys: oneVs.mine, color: 'var(--accent-strong)', bold: true }]} /></section>}
      </div>
      <section className="card wells-table">
        <h3>Скважины набора, {fmtDay2(a, b)}</h3>
        <div className="table-scroll">
          <table className="data"><thead><tr><th>Скв.</th><th>Направление</th><th className="number">Объём, млн м³</th><th className="number">Доля</th><th className="number">В среднем, тыс. м³/сут</th><th className="number">Дней</th><th className="number">Сезон, млн м³</th><th className="number">К прошлому сезону</th></tr></thead>
            <tbody>{sorted.map(r => (
              <tr key={r.w} className={selected === r.w ? 'sel' : ''} onClick={() => onSelect(r.w)}>
                <td><b>{r.w}</b></td><td className="muted">{dir(r.w)}</td><td className="number">{fmtMln(r.total)}</td><td className="number">{sum > 0 ? fmtPct(Math.max(0, r.total) / sum) : '—'}</td>
                <td className="number">{fmtTh(r.mean)}</td><td className="number">{fmtInt(r.days)}</td><td className="number">{fmtMln(r.full)}</td>
                <td className="number">{r.d === null ? '—' : (r.d >= 0 ? '+' : '−') + fmtPct(Math.abs(r.d))}</td></tr>))}</tbody></table>
        </div>
      </section>
    </div>
  )
  function fmtDay2(x: number, y: number) { return `дни ${x + 1}–${y + 1} сезона` }
}
