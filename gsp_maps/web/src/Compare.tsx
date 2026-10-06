import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getSeason, type GspData } from './api'
import MapView, { type MapOptions, type View } from './MapView'
import { syncMaps, usePref } from './prefs'
import { SeasonCalc, fmt1, fmtDay, fmtMln, fmtPct, fmtTh } from './model'

interface Props {
  g: GspData; kind: string; options: MapOptions; onOptions: (o: Partial<MapOptions>) => void
  inspector: boolean
}
const PAD = 10

/** Окно в днях от старта сезона; у более короткого сезона оно обрезается, а если сезон кончился раньше окна, окна нет. */
const clampTo = (c: SeasonCalc, a: number, b: number): [number, number] | null => (a >= c.nd ? null : [a, Math.min(b, c.nd - 1)])

interface Totals {
  total: number; days: number; mean: number; peak: number; peakDay: number; working: number; perWell: number; top5: number; half: number
}
function totalsOf(c: SeasonCalc, a: number, b: number): Totals | null {
  const w = clampTo(c, a, b)
  if (!w) return null
  const [x, y] = w
  let total = 0, peak = 0, peakDay = x
  for (let j = x; j <= y; j++) { const v = c.daily[j]; total += v; if (v > peak) { peak = v; peakDay = j } }
  const per: number[] = []
  for (let i = 0; i < c.nw; i++) { const t = c.stat(i, x, y).total; if (t > 0) per.push(t) }
  per.sort((p, q) => q - p)
  const sum = per.reduce((s, v) => s + v, 0)
  const all = c.daily.reduce((s, v) => s + v, 0)
  let acc = 0, half = 0
  for (let j = 0; j < c.nd; j++) { acc += c.daily[j]; if (acc >= all / 2) { half = j; break } }
  return {
    total, days: y - x + 1, mean: total / (y - x + 1), peak, peakDay, working: per.length,
    perWell: per.length ? sum / per.length : 0, top5: sum > 0 ? per.slice(0, 5).reduce((s, v) => s + v, 0) / sum : 0, half,
  }
}

function useSeason(g: GspData, kind: string, key: string) {
  const [calc, setCalc] = useState<SeasonCalc | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    setCalc(null); setErr('')
    if (!key) return
    let live = true
    getSeason(g.gsp, kind, key).then(d => { if (live) setCalc(new SeasonCalc(d)) }).catch(e => live && setErr(String(e.message || e)))
    return () => { live = false }
  }, [g.gsp, kind, key])
  return { calc, err }
}

export default function Compare({ g, kind, options, onOptions, inspector }: Props) {
  const seasons = g.seasons[kind as 'Отбор' | 'Закачка'] || []
  const keys = seasons.map(s => s.key)
  const [pa, setPa] = useState(''), [pb, setPb] = useState('')
  // по умолчанию: слева прошлый сезон, справа последний
  const keyB = keys.includes(pb) ? pb : keys[keys.length - 1] || ''
  const keyA = keys.includes(pa) ? pa : keys.length > 1 ? keys[keys.indexOf(keyB) > 0 ? keys.indexOf(keyB) - 1 : Math.max(0, keys.length - 2)] : ''
  const A = useSeason(g, kind, keyA), B = useSeason(g, kind, keyB)
  const ca = A.calc, cb = B.calc
  const nd = Math.max(ca?.nd || 0, cb?.nd || 0)
  const sync = usePref(syncMaps)
  const [winA, setWinA] = useState<[number, number] | null>(null)
  const [winB, setWinB] = useState<[number, number] | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [group, setGroup] = useState<number[]>([])
  const [viewA, setViewA] = useState<View>({ k: 1, tx: 0, ty: 0 })
  const [viewB, setViewB] = useState<View>({ k: 1, tx: 0, ty: 0 })
  const syncRef = useRef(sync); syncRef.current = sync
  const onViewA = useCallback((v: View) => { setViewA(v); if (syncRef.current) setViewB(v) }, [])
  const onViewB = useCallback((v: View) => { setViewB(v); if (syncRef.current) setViewA(v) }, [])
  useEffect(() => { const w: [number, number] = [0, Math.max(0, nd - 1)]; setWinA(w); setWinB(w) }, [nd, keyA, keyB])
  // при включении синхронизации правая карта берёт вид и окно левой
  useEffect(() => { if (sync) { setViewB(viewA); setWinB(winA) } }, [sync]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSelected(null); setGroup([]) }, [g.gsp])
  const pick = useCallback((w: number | null) => { setSelected(w); setGroup([]) }, [])
  // при синхронизации обе карты живут на общей оси дней (по длиннейшему сезону), иначе у каждой своя ось
  const lim = (n: number) => Math.max(0, (sync ? nd : n) - 1)
  const fit = (w: [number, number] | null, n: number): [number, number] => (w ? [Math.min(w[0], lim(n)), Math.min(w[1], lim(n))] : [0, 0])
  const [a, b] = fit(winA, ca?.nd || 0)
  const [a2, b2] = sync ? [a, b] : fit(winB, cb?.nd || 0)
  const setWindowA = useCallback((x: number, y: number) => { setWinA([x, y]); if (syncRef.current) setWinB([x, y]) }, [])
  const setWindowB = useCallback((x: number, y: number) => { setWinB([x, y]); if (syncRef.current) setWinA([x, y]) }, [])

  const wa = ca ? clampTo(ca, a, b) : null, wb = cb ? clampTo(cb, a2, b2) : null
  // общий масштаб кругов: самая крупная скважина из двух сезонов, иначе круги нельзя сравнивать
  const scaleMax = useMemo(() => {
    if (!ca || !cb) return undefined
    const mx = (c: SeasonCalc, x: number, y: number) => { let m = 1; for (let i = 0; i < c.nw; i++) m = Math.max(m, c.stat(i, x, y).total); return m }
    const fix = options.fixed
    const ra = fix ? [0, ca.nd - 1] : wa, rb = fix ? [0, cb.nd - 1] : wb
    return Math.max(ra ? mx(ca, ra[0], ra[1]) : 1, rb ? mx(cb, rb[0], rb[1]) : 1)
  }, [ca, cb, wa, wb, options.fixed])

  const title = (side: string, c: SeasonCalc, key: string, w: [number, number] | null) =>
    `${g.gsp} (${side}) · ${kind} ${key} · ${w ? fmtDay(c.days[w[0]]) + ' — ' + fmtDay(c.days[w[1]]) : 'сезон уже закончился'}`

  if (keys.length < 2) return <section className="card"><h2>Нечего сравнивать</h2><p className="muted">Для «{g.gsp}» в виде «{kind}» меньше двух сезонов.</p></section>
  const err = A.err || B.err
  const ready = !!ca && !!cb
  const swap = () => { setPa(keyB); setPb(keyA) }

  const mapFor = (side: string, c: SeasonCalc | null, key: string, w: [number, number] | null) => c && w ? (
    <MapView g={g} calc={c} kind={kind} season={key} a={w[0]} b={w[1]} selected={selected} onSelect={pick} group={group} onGroup={setGroup} title={title(side, c, key, w)}
      options={options} onOptions={onOptions} compact scaleMax={scaleMax} view={side === 'А' ? viewA : viewB} onView={side === 'А' ? onViewA : onViewB} />
  ) : <div className="map-wrap"><div className="empty-map">{c ? 'Сезон ' + key + ' закончился раньше выбранных дней.' : 'Считаю…'}</div></div>

  return (
    <div className={'cmp-page' + (inspector ? '' : ' no-insp')}>
      <div className="cmp-main">
        <div className="cmp-bar">
          <label className="sel"><span>А</span><select value={keyA} onChange={e => setPa(e.target.value)}>{keys.map(k => <option key={k}>{k}</option>)}</select></label>
          <button type="button" className="quiet" onClick={swap} title="Поменять карты местами">⇄</button>
          <button type="button" className={'quiet sync-btn' + (sync ? ' on' : '')} aria-pressed={sync} onClick={() => syncMaps.set(!sync)}
            title={sync ? 'Карты связаны: зум, сдвиг и время общие. Нажмите, чтобы отвязать' : 'Карты независимы. Нажмите, чтобы связать зум, сдвиг и время'}>
            <svg viewBox="0 0 16 16" aria-hidden="true">{sync ? <path d="M6.5 9.5 9.5 6.5M7 4.5l1-1a2.5 2.5 0 0 1 3.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 0 1 4.5 9l1-1" /> : <path d="M6.5 9.5 9.5 6.5M7 4.5l1-1a2.5 2.5 0 0 1 3.5 3.5M9 11.5l-1 1A2.5 2.5 0 0 1 4.5 9M3 3l10 10" />}</svg>
            {sync ? 'Синхронно' : 'Независимо'}</button>
          <label className="sel"><span>Б</span><select value={keyB} onChange={e => setPb(e.target.value)}>{keys.map(k => <option key={k}>{k}</option>)}</select></label>
          <span className="muted cmp-hint">{sync ? 'Карты двигаются, приближаются и листаются по времени вместе: дни считаются от старта сезона.' : 'Каждая карта со своим видом и своим окном времени.'} Круги везде одного масштаба.</span>
        </div>
        {err && <div className="note warning">{err}</div>}
        <div className="cmp-maps">
          <div className="cmp-cell">{mapFor('А', ca, keyA, wa)}</div>
          <div className="cmp-cell">{mapFor('Б', cb, keyB, wb)}</div>
        </div>
        {ready && (sync
          ? <CompareTimeline items={[{ calc: ca!, key: keyA, side: 'А' }, { calc: cb!, key: keyB, side: 'Б' }]} nd={nd} a={a} b={b} setWindow={setWindowA} />
          : <div className="cmp-tls">
            <CompareTimeline items={[{ calc: ca!, key: keyA, side: 'А' }]} nd={ca!.nd} a={a} b={b} setWindow={setWindowA} th={34} />
            <CompareTimeline items={[{ calc: cb!, key: keyB, side: 'Б' }]} nd={cb!.nd} a={a2} b={b2} setWindow={setWindowB} th={34} /></div>)}
      </div>
      {inspector && ready && <ComparePanel ca={ca!} cb={cb!} keyA={keyA} keyB={keyB} nd={nd} a={a} b={b} a2={a2} b2={b2} selected={selected} group={group} onSelect={pick} />}
    </div>
  )
}

interface TlItem { calc: SeasonCalc; key: string; side: string }
function CompareTimeline({ items, nd, a, b, setWindow, th = 70 }: { items: TlItem[]; th?: number; nd: number; a: number; b: number; setWindow: (a: number, b: number) => void }) {
  const two = items.length > 1
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(900)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const drag = useRef<{ mode: 'a' | 'b' | 'move' | 'new'; at: number; a: number; b: number } | null>(null)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setW(el.clientWidth))
    ro.observe(el); setW(el.clientWidth)
    return () => ro.disconnect()
  }, [])
  const inner = Math.max(50, w - 2 * PAD)
  const px = (i: number) => PAD + (i / nd) * inner
  const idxAt = (x: number) => Math.max(0, Math.min(nd - 1, Math.floor(((x - PAD) / inner) * nd)))
  const wr = useRef({ a, b }); wr.current = { a, b }
  useEffect(() => {
    if (!playing) return
    let last = performance.now(), pos = wr.current.b
    const tick = (t: number) => {
      pos += ((t - last) / 1000) * speed * Math.max(6, nd / 12)
      last = t
      const next = Math.min(nd - 1, Math.floor(pos))
      if (next !== wr.current.b) setWindow(wr.current.a, next)
      if (next >= nd - 1) { setPlaying(false); return }
      id = requestAnimationFrame(tick)
    }
    let id = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(id)
  }, [playing, speed, nd, setWindow])

  const mx = Math.max(1, ...items.flatMap(i => Array.from(i.calc.daily)))
  const path = (c: SeasonCalc) => 'M' + Array.from(c.daily, (v, j) => `${(PAD + ((j + 0.5) / nd) * inner).toFixed(1)},${(th - (Math.max(0, v) / mx) * (th - 6)).toFixed(1)}`).join('L')
  const paths = useMemo(() => items.map(i => path(i.calc)), [items, nd, inner]) // eslint-disable-line react-hooks/exhaustive-deps
  const step = nd > 400 ? 90 : 30
  const ticks = Array.from({ length: Math.floor((nd - 1) / step) + 1 }, (_, k) => k * step)

  const pos = (e: React.PointerEvent) => e.clientX - box.current!.getBoundingClientRect().left
  const down = (e: React.PointerEvent) => {
    const x = pos(e), xa = px(a), xb = px(b + 1)
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    setPlaying(false)
    if (Math.abs(x - xa) < 9) drag.current = { mode: 'a', at: idxAt(x), a, b }
    else if (Math.abs(x - xb) < 9) drag.current = { mode: 'b', at: idxAt(x), a, b }
    else if (x > xa && x < xb) drag.current = { mode: 'move', at: idxAt(x), a, b }
    else { drag.current = { mode: 'new', at: idxAt(x), a, b }; setWindow(idxAt(x), idxAt(x)) }
  }
  const move = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const i = idxAt(pos(e))
    if (d.mode === 'a') setWindow(Math.min(i, d.b), d.b)
    else if (d.mode === 'b') setWindow(d.a, Math.max(i, d.a))
    else if (d.mode === 'new') setWindow(Math.min(i, d.at), Math.max(i, d.at))
    else { const len = d.b - d.a, na = Math.max(0, Math.min(nd - 1 - len, d.a + i - d.at)); setWindow(na, na + len) }
  }
  const whole = a === 0 && b === nd - 1
  const dates = (c: SeasonCalc) => (a < c.nd ? fmtDay(c.days[a]) + ' — ' + fmtDay(c.days[Math.min(b, c.nd - 1)]) : 'нет')
  return (
    <div className="timeline">
      <div className="tl-row">
        <button type="button" className="play" onClick={() => { if (!playing && b >= nd - 1) setWindow(a, a); setPlaying(p => !p) }} aria-label={playing ? 'Пауза' : 'Показать развитие по дням'}
          title={playing ? 'Пауза' : 'Показать развитие по дням: окно растёт от его начала'}>
          <svg viewBox="0 0 16 16" aria-hidden="true">{playing ? <path d="M5 3v10M11 3v10" /> : <path d="M5 3l8 5-8 5z" />}</svg></button>
        <div className="segmented tl-speed" role="radiogroup" aria-label="Скорость">
          {[1, 2, 4, 8].map(s => <button key={s} type="button" role="radio" aria-checked={speed === s} onClick={() => setSpeed(s)}>{s}×</button>)}
        </div>
        <div className="tl-read"><b>день {a + 1} — {b + 1}</b><span className="muted"> · {b - a + 1} дн. · {items.map(i => i.side + ': ' + dates(i.calc)).join(' · ')}</span></div>
        <div className="tl-chips">
          <button type="button" className={'chip-btn' + (whole ? ' on' : '')} onClick={() => { setPlaying(false); setWindow(0, nd - 1) }}>Весь сезон</button>
          {ticks.filter(t => t + step <= nd + 1).map(t => <button key={t} type="button" className="chip-btn" onClick={() => { setPlaying(false); setWindow(t, Math.min(nd - 1, t + step - 1)) }} title={`Дни ${t + 1}–${Math.min(nd, t + step)} от старта сезона`}>{t + 1}–{Math.min(nd, t + step)}</button>)}
        </div>
      </div>
      <div ref={box} className="tl-track" onPointerDown={down} onPointerMove={move} onPointerUp={() => { drag.current = null }}>
        <svg width={w} height={th + 22} role="img" aria-label="Общий бегунок по дням от старта сезона">
          {ticks.map(t => <g key={t}><line x1={px(t)} x2={px(t)} y1={4} y2={th} className="tl-tick" /><text x={px(t) + 3} y={th + 14} className="tl-label">день {t + 1}</text></g>)}
          {paths.map((d, i) => <path key={i} d={d} className={'spark-line' + (two && i === 0 ? ' cmp-line-a' : '')} />)}
          <rect x={px(a)} width={Math.max(2, px(b + 1) - px(a))} y={2} height={th - 4} className="tl-sel" />
          <rect x={px(a) - 3} y={th / 2 - 14} width={6} height={28} rx={3} className="tl-handle" />
          <rect x={px(b + 1) - 3} y={th / 2 - 14} width={6} height={28} rx={3} className="tl-handle" />
        </svg>
        <div className="cum-legend">{items.map((i, k) => <span key={k}><i className={two && k === 0 ? 'cmp-key-a' : ''} style={two && k === 0 ? undefined : { background: 'var(--accent)' }} />{i.side} · {i.key}</span>)}<span className="muted">суточный расход ГСП{two ? ', общая шкала' : ''}</span></div>
      </div>
    </div>
  )
}

const sign = (v: number, f: (x: number) => string) => (v > 0 ? '+' : v < 0 ? '−' : '') + f(Math.abs(v))
function Row({ label, a, b, f, unit, pct = true }: { label: string; a: number | null; b: number | null; f: (v: number) => string; unit?: string; pct?: boolean }) {
  const d = a !== null && b !== null ? b - a : null
  return (
    <tr><th>{label}{unit && <small>{unit}</small>}</th>
      <td className="number">{a === null ? '—' : f(a)}</td><td className="number">{b === null ? '—' : f(b)}</td>
      <td className="number delta">{d === null ? '—' : sign(d, f)}{pct && d !== null && a ? <small> {sign((d / a) * 100, fmt1)} %</small> : null}</td></tr>
  )
}

function CumCompare({ rows, wins, nd, keyA, keyB }: { rows: [number[] | null, number[] | null]; wins: [number, number][]; nd: number; keyA: string; keyB: string }) {
  const W = 300, H = 110
  const cum = (r: number[] | null) => { const o: number[] = []; let s = 0; for (const v of r || []) { s += Math.max(0, v); o.push(s) } return o }
  const [xa, xb] = [cum(rows[0]), cum(rows[1])]
  const mx = Math.max(1, ...xa, ...xb)
  const x = (j: number) => ((j + 0.5) / nd) * W, y = (v: number) => H - (v / mx) * (H - 6)
  const line = (c: number[]) => 'M' + c.map((v, j) => `${x(j).toFixed(1)},${y(v).toFixed(1)}`).join('L')
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H + 14}`} className="cum" role="img" aria-label="Накопленный расход по дням от старта сезона, два сезона">
        {wins.map(([x0, x1], k) => <rect key={k} x={(x0 / nd) * W} width={Math.max(1, ((x1 - x0 + 1) / nd) * W)} y={0} height={H} className="daily-win" opacity={wins[0][0] === wins[1][0] && wins[0][1] === wins[1][1] && k ? 0 : 1} />)}
        <path d={line(xa)} fill="none" className="cmp-line-a" strokeWidth={1.8} />
        <path d={line(xb)} fill="none" stroke="var(--accent)" strokeWidth={2} />
        <line x1={0} x2={W} y1={H} y2={H} className="daily-axis" />
        <text x={0} y={H + 11} className="daily-t">день 1</text>
        <text x={W} y={H + 11} textAnchor="end" className="daily-t">день {nd}</text>
        <text x={W} y={9} textAnchor="end" className="daily-t">макс. {fmtMln(mx)} млн м³</text>
      </svg>
      <div className="cum-legend"><span><i className="cmp-key-a" />А · {keyA}: {fmtMln(xa[xa.length - 1] || 0)}</span><span><i style={{ background: 'var(--accent)' }} />Б · {keyB}: {fmtMln(xb[xb.length - 1] || 0)}</span></div>
    </>
  )
}

function ComparePanel({ ca, cb, keyA, keyB, nd, a, b, a2, b2, selected, group, onSelect }: { ca: SeasonCalc; cb: SeasonCalc; keyA: string; keyB: string; nd: number; a: number; b: number; a2: number; b2: number; selected: number | null; group: number[]; onSelect: (w: number | null) => void }) {
  const ta = useMemo(() => totalsOf(ca, a, b), [ca, a, b]), tb = useMemo(() => totalsOf(cb, a2, b2), [cb, a2, b2])
  const wells = useMemo(() => {
    const m = new Map<number, [number, number]>()
    const wa = clampTo(ca, a, b), wb = clampTo(cb, a2, b2)
    for (let i = 0; i < ca.nw; i++) m.set(ca.wells[i], [wa ? ca.stat(i, wa[0], wa[1]).total : 0, 0])
    for (let i = 0; i < cb.nw; i++) { const v = wb ? cb.stat(i, wb[0], wb[1]).total : 0; const e = m.get(cb.wells[i]); if (e) e[1] = v; else m.set(cb.wells[i], [0, v]) }
    return [...m.entries()].map(([w, [x, y]]) => ({ w, x, y, d: y - x })).filter(r => r.x > 0 || r.y > 0)
  }, [ca, cb, a, b, a2, b2])
  const top = useMemo(() => [...wells].sort((p, q) => Math.abs(q.d) - Math.abs(p.d)).slice(0, 8), [wells])
  const dmax = Math.max(1, ...top.map(r => Math.abs(r.d)))
  const picked = group.length > 1 ? group : selected !== null ? [selected] : []
  const rowsFor = (c: SeasonCalc): number[] | null => {
    if (!picked.length) return Array.from(c.daily)
    const idx = picked.map(w => c.index.get(w)).filter((i): i is number => i !== undefined)
    if (!idx.length) return null
    return Array.from({ length: c.nd }, (_, j) => idx.reduce((s, i) => s + Math.max(0, c.flow[i][j]), 0))
  }
  const scope = picked.length > 1 ? `Выбрано скважин: ${picked.length}` : picked.length ? `Скважина ${picked[0]}` : 'Весь ГСП'
  const onlyA = wells.filter(r => r.x > 0 && r.y === 0).length, onlyB = wells.filter(r => r.y > 0 && r.x === 0).length
  return (
    <aside className="inspector">
      <div className="insp-head"><div><h2>Сравнение</h2><span className="muted">А {keyA} · Б {keyB}</span></div></div>
      {(a !== a2 || b !== b2) && <p className="muted hint">Окна у карт разные: А — дни {a + 1}–{b + 1}, Б — дни {a2 + 1}–{b2 + 1}.</p>}
      <h3>Итоги за выбранные дни</h3>
      <table className="mini cmp-table">
        <thead><tr><th /><th className="number">А</th><th className="number">Б</th><th className="number">Б − А</th></tr></thead>
        <tbody>
          <Row label="Объём" unit="млн м³" a={ta ? ta.total : null} b={tb ? tb.total : null} f={fmtMln} />
          <Row label="Средний расход" unit="тыс. м³/сут" a={ta ? ta.mean : null} b={tb ? tb.mean : null} f={fmtTh} />
          <Row label="Пик суток" unit="тыс. м³" a={ta ? ta.peak : null} b={tb ? tb.peak : null} f={fmtTh} />
          <Row label="День пика" a={ta ? ta.peakDay + 1 : null} b={tb ? tb.peakDay + 1 : null} f={v => String(v)} pct={false} />
          <Row label="Работало скважин" a={ta ? ta.working : null} b={tb ? tb.working : null} f={v => String(v)} pct={false} />
          <Row label="На скважину" unit="млн м³" a={ta ? ta.perWell : null} b={tb ? tb.perWell : null} f={fmtMln} />
          <Row label="Доля пяти лучших" a={ta ? ta.top5 : null} b={tb ? tb.top5 : null} f={v => fmtPct(v)} pct={false} />
          <Row label="День 50 % сезона" a={ta ? ta.half + 1 : null} b={tb ? tb.half + 1 : null} f={v => String(v)} pct={false} />
        </tbody>
      </table>
      <p className="muted hint">Скважин, работавших только в А: {onlyA}, только в Б: {onlyB}. «День 50 %» считается по всему сезону.</p>
      <h3>Накопленный расход · {scope}</h3>
      <CumCompare rows={[rowsFor(ca), rowsFor(cb)]} wins={[[a, b], [a2, b2]]} nd={nd} keyA={keyA} keyB={keyB} />
      <h3>Что изменилось сильнее всего</h3>
      <ul className="toplist cmp-top">{top.map(r => (
        <li key={r.w}><button type="button" className={selected === r.w ? 'on' : ''} onClick={() => onSelect(r.w)} title={`А ${fmtMln(r.x)} → Б ${fmtMln(r.y)} млн м³`}>
          <b>{r.w}</b>
          <span className="dvbar"><i className={r.d < 0 ? 'neg' : 'pos'} style={{ width: (Math.abs(r.d) / dmax) * 50 + '%', [r.d < 0 ? 'right' : 'left']: '50%' }} /></span>
          <span className="number">{sign(r.d, fmtMln)}</span></button></li>))}</ul>
      <p className="muted hint">Справа — скважина дала в Б больше, слева — меньше. Клик выбирает её на обеих картах.</p>
    </aside>
  )
}
