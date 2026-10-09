import { useEffect, useState } from 'react'

import PageHead from './PageHead'
import ColumnWizard from './ColumnWizard'
import {
  AppState, AvgDaily, AvgParams, AvgStatus, AvgView, AvgWellView, avgAdvice, avgChoose, avgExclude, avgManual, buildSources, getAvgDaily, getAvgStatus,
  getAveraging, getAveragingWell, setAvgParams,
} from './api'

const COLORS = ['#2f6fb0', '#c4622d', '#3f9a6a', '#8a5bb0', '#b09a2f', '#2f9aa8', '#b0426b', '#6b7a8a']
const pct = (x: number | null | undefined, d = 1) => (x == null ? '—' : (x * 100).toFixed(d) + ' %')
const fillCounts = (f: { how: string }[]) => f.reduce((a: Record<string, number>, x) => { a[x.how] = (a[x.how] || 0) + 1; return a }, {})
const num = (s: string) => Number(s.replace(',', '.'))

/** Цвет ячейки тепловой карты: зелёный — малая ошибка, красный — большая (в долях от максимума строки не берём: шкала общая). */
function heat(v: number | null, max: number) {
  if (v == null) return 'transparent'
  const t = Math.min(1, v / (max || 1))
  return 'hsl(' + Math.round(130 - 130 * t) + ', 55%, ' + Math.round(80 - 18 * t) + '%)'
}

function Lines({ w, onMonth }: { w: AvgWellView; onMonth: (m: string) => void }) {
  const W = 560, H = 220, L = 44, B = 26, T = 10
  const all = [...Object.values(w.byYear).flat(), ...w.mean].filter((x): x is number => x != null)
  const max = Math.max(0.05, ...all) * 1.1
  const X = (i: number) => L + (w.months.length < 2 ? (W - L - 10) / 2 : (i * (W - L - 10)) / (w.months.length - 1))
  const Y = (v: number) => T + (H - T - B) * (1 - v / max)
  const path = (vals: (number | null)[]) => vals.map((v, i) => (v == null ? '' : (i && vals[i - 1] != null ? 'L' : 'M') + X(i) + ',' + Y(v))).join('')
  const used = new Set(w.chosen || [])
  return (
    <svg viewBox={'0 0 ' + W + ' ' + H} className="chart" role="img" aria-label="Доли скважины по годам и выбранное среднее">
      {[0, .25, .5, .75, 1].map(t => <g key={t}><line x1={L} x2={W - 10} y1={Y(max * t)} y2={Y(max * t)} stroke="var(--line)" />
        <text x={L - 6} y={Y(max * t) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">{(max * t * 100).toFixed(0)}%</text></g>)}
      {w.months.map((m, i) => <text key={m} x={X(i)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--muted)" style={{ cursor: 'pointer' }} onClick={() => onMonth(m)}>{m.slice(0, 3)}</text>)}
      {w.years.map((y, k) => <path key={y} d={path(w.byYear[String(y)])} fill="none" stroke={COLORS[k % COLORS.length]}
        strokeWidth={used.has(y) ? 1.8 : 1} strokeDasharray={used.has(y) ? undefined : '4 3'} opacity={used.has(y) ? 1 : .55} />)}
      <path d={path(w.mean)} fill="none" stroke="var(--ink)" strokeWidth="3.5" />
      {w.months.map((m, i) => w.manual[m] != null && <circle key={m} cx={X(i)} cy={Y(w.manual[m])} r="5" fill="var(--warn)" stroke="var(--surface)"><title>правлено вручную: {pct(w.manual[m])}</title></circle>)}
    </svg>
  )
}

function Legend({ w }: { w: AvgWellView }) {
  return <div className="legend small">{w.years.map((y, k) => <span key={y}><i style={{ background: COLORS[k % COLORS.length] }} />{y}{w.autoExcluded[String(y)] ? ' (простой)' : ''}</span>)}
    <span><i style={{ background: 'var(--ink)' }} />выбранное среднее</span></div>
}

function GroupBars({ v, group }: { v: AvgView; group: string }) {
  const ws = Object.keys(v.groups[group] || {})
  const W = 560, H = 190, L = 44, B = 26, T = 8
  const bw = (W - L - 10) / Math.max(1, v.months.length)
  return (
    <svg viewBox={'0 0 ' + W + ' ' + H} className="chart" role="img" aria-label="Состав группы по месяцам">
      {v.months.map((m, i) => {
        let acc = 0
        const sum = v.sums[group]?.[m] || 0
        return <g key={m}>
          {ws.map((w, k) => {
            const s = (v.groups[group][w][m]?.share || 0) / (sum || 1)
            const y0 = T + (H - T - B) * (1 - acc - s)
            acc += s
            return <rect key={w} x={L + i * bw + 3} width={bw - 6} y={y0} height={(H - T - B) * s} fill={COLORS[k % COLORS.length]} opacity={v.groups[group][w][m]?.manual ? 1 : .85}>
              <title>{w}: {pct(s)}{v.groups[group][w][m]?.manual ? ' (вручную)' : ''}</title></rect>
          })}
          <text x={L + i * bw + bw / 2} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--muted)">{m.slice(0, 3)}</text>
        </g>
      })}
      {[0, .5, 1].map(t => <text key={t} x={L - 6} y={T + (H - T - B) * (1 - t) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">{t * 100}%</text>)}
    </svg>
  )
}

const FILL_COLORS: Record<string, string> = { 'окно ±3 суток': '#e0b43a', 'окно ±7 суток': '#e08a3a', 'доля месяца': '#d4523a', 'поровну': '#8a5bb0' }
const METHOD_LABELS: Record<string, string> = { mean: 'Среднее', median: 'Медиана', recency: 'Взвешенное по свежести', trimmed: 'Усечённое (без крайних)' }
const METHOD_HELP: Record<string, string> = {
  mean: 'простое среднее долей по выбранным сезонам', median: 'устойчива к выбросам одного сезона',
  recency: 'последний сезон весит больше предыдущих', trimmed: 'отбрасывает самый большой и самый малый сезон (от 3 сезонов)',
}

/** Суточный профиль долей скважин группы: линия на каждую скважину, сутки, заполненные запасными правилами, подсвечены полосами. */
function DailyChart({ d, group }: { d: AvgDaily; group: string }) {
  const g = d.groups[group]
  const [hover, setHover] = useState<number | null>(null)
  if (!g) return null
  const W = 760, H = 250, L = 46, B = 28, T = 10, R = 10
  const names = Object.keys(g.wells)
  const all = names.flatMap(w => g.wells[w]).filter((x): x is number => x != null)
  const max = Math.max(0.05, ...all) * 1.1
  const n = Math.max(2, d.days)
  const X = (i: number) => L + (i * (W - L - R)) / (n - 1)
  const Y = (v: number) => T + (H - T - B) * (1 - v / max)
  const path = (vals: (number | null)[]) => vals.map((v, i) => (v == null ? '' : (i && vals[i - 1] != null ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1))).join('')
  const ticks = (d.dates || []).map((x, i) => [x, i] as [string, number]).filter(([x]) => x.endsWith('-01'))
  const bw = Math.max(1.5, (W - L - R) / n)
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const x = ((e.clientX - r.left) / r.width) * W
    setHover(Math.min(n - 1, Math.max(0, Math.round(((x - L) * (n - 1)) / (W - L - R)))))
  }
  const hv = hover != null ? names.map((w, k) => [w, g.wells[w][hover], k] as [string, number | null, number]).filter(x => x[1] != null) : []
  const fill = hover != null ? g.filled.find(f => f.day === hover) : undefined
  return (
    <div>
      <svg viewBox={'0 0 ' + W + ' ' + H} className="chart wide" role="img" aria-label="Суточные доли скважин группы" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {g.filled.map(f => <rect key={f.day} x={X(f.day) - bw / 2} y={T} width={bw} height={H - T - B} fill={FILL_COLORS[f.how] || '#d4523a'} opacity=".28" />)}
        {[0, .25, .5, .75, 1].map(t => <g key={t}><line x1={L} x2={W - R} y1={Y(max * t)} y2={Y(max * t)} stroke="var(--line)" />
          <text x={L - 6} y={Y(max * t) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">{(max * t * 100).toFixed(0)}%</text></g>)}
        {ticks.map(([x, i]) => <g key={x}><line x1={X(i)} x2={X(i)} y1={H - B} y2={H - B + 4} stroke="var(--muted)" />
          <text x={X(i)} y={H - 10} textAnchor="middle" fontSize="11" fill="var(--muted)">{MONTH_SHORT[Number(x.slice(5, 7)) - 1]}</text></g>)}
        {names.map((w, k) => <path key={w} d={path(g.wells[w])} fill="none" stroke={COLORS[k % COLORS.length]} strokeWidth="1.6" />)}
        {hover != null && <line x1={X(hover)} x2={X(hover)} y1={T} y2={H - B} stroke="var(--ink)" strokeDasharray="3 3" />}
      </svg>
      <div className="muted small" style={{ minHeight: 20 }}>
        {hover != null ? <>Сутки {hover + 1}{d.dates ? ' (' + d.dates[hover].split('-').reverse().join('.') + ' в последнем выбранном сезоне)' : ''}: {hv.map(([w, v]) => w + ' ' + pct(v, 1)).join(' · ')}{fill ? ' · заполнено: ' + fill.how : ''}</> : 'Наведите курсор на график, чтобы увидеть доли скважин за сутки.'}
      </div>
      <div className="legend small">{names.map((w, k) => <span key={w}><i style={{ background: COLORS[k % COLORS.length] }} />{w}</span>)}</div>
    </div>
  )
}
const MONTH_SHORT = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']

export default function Averaging({ st, setSt }: { st: AppState; setSt: (s: AppState) => void }) {
  const [kind, setKind] = useState('закачка')
  const [v, setV] = useState<AvgView | null>(null)
  const [sel, setSel] = useState('')
  const [wv, setWv] = useState<AvgWellView | null>(null)
  const [status, setStatus] = useState<AvgStatus | null>(null)
  const [daily, setDaily] = useState<AvgDaily | null>(null)
  const [wizard, setWizard] = useState('')
  const [edit, setEdit] = useState<{ month: string; text: string } | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const apply = (x: AvgView) => setV(x)
  const load = async (k: string) => {
    const s = await getAvgStatus(k)
    setStatus(s); setV(null); setDaily(null)
    if (s.problem) return
    await Promise.all([getAvgDaily(k).then(setDaily).catch(e => setMsg(e.message)), getAveraging(k).then(apply).catch(e => setMsg(e.message))])
  }
  const reload = () => guard(() => load(kind))
  useEffect(() => { setSel(''); setMsg(''); load(kind).catch(e => setMsg(e.message)) }, [kind, st])
  useEffect(() => { if (v && sel && v.wells.some(w => w.well === sel)) getAveragingWell(kind, sel).then(setWv).catch(e => setMsg(e.message)); else setWv(null) }, [sel, v])

  const act = (f: () => Promise<AvgView>) => guard(async () => apply(await f()))
  const prm = status?.params
  const setParams = (p: Partial<AvgParams>) => guard(async () => { await setAvgParams(kind, p); await load(kind) })
  const buildWells = () => guard(async () => { await buildSources(); await load(kind) })
  const chosenSeasons = prm && status ? (prm.seasons.length ? prm.seasons : status.seasons) : []
  const toggleSeason = (y: number) => {
    if (!status) return
    const cur = new Set(chosenSeasons)
    if (cur.has(y)) cur.delete(y); else cur.add(y)
    if (!cur.size) return
    setParams({ seasons: cur.size === status.seasons.length ? [] : Array.from(cur).sort() })
  }
  const row = v?.wells.find(w => w.well === sel)
  const maxHeat = v ? Math.max(0, ...v.heat.flatMap(h => h.values.filter((x): x is number => x != null))) : 0
  const combo = (c: string) => c.split('+').map(Number)
  const groups = v ? Array.from(new Set(v.wells.map(w => w.group))) : []
  const [grp, setGrp] = useState('')
  const g = grp && groups.includes(grp) ? grp : groups[0] || ''
  const [dgrp, setDgrp] = useState('')
  const dg = daily && dgrp && daily.groups[dgrp] ? dgrp : daily ? Object.keys(daily.groups)[0] || '' : ''

  return (
    <main className="workspace">
      <PageHead title="Осреднение" lede="Доли скважин в расходе группы считаются из базы расходов проекта по выбранным сезонам: для каждых суток сезона, от его старта." />
      {msg && <div className="note warn">{msg}</div>}
      <div className="card">
        <h2>Источник и настройки</h2>
        <div className="row">
          <label>Вид<select value={kind} onChange={e => setKind(e.target.value)}><option>закачка</option><option>отбор</option></select></label>
          {status && !status.problem && prm && <>
            <div className="segmented" role="radiogroup" aria-label="Как считать доли" style={{ alignSelf: 'flex-end' }}>
              <button type="button" role="radio" aria-checked={prm.mode === 'day'} disabled={busy} onClick={() => setParams({ mode: 'day' })}>По суткам</button>
              <button type="button" role="radio" aria-checked={prm.mode === 'month'} disabled={busy} onClick={() => setParams({ mode: 'month' })}>По месяцам</button>
            </div>
            <label>Метод по сезонам<select value={prm.method} disabled={busy || prm.mode !== 'day'} onChange={e => setParams({ method: e.target.value })}>
              {status.methods.map(m => <option key={m} value={m}>{METHOD_LABELS[m] || m}</option>)}</select></label>
          </>}
        </div>
        {status && <p className="src-status">
          База расходов: <b>{status.files ? status.files + ' ' + (status.files === 1 ? 'файл' : 'файла(ов)') : 'нет'}</b>
          {' · '}скважин: <b>{status.wells}</b>, групп: <b>{status.groups}</b>{status.withoutGroup > 0 && <span className="warn"> (без группы: {status.withoutGroup})</span>}
          {' · '}сезоны: <b>{status.seasons.length ? status.seasons.join(', ') : '—'}</b>
          {' · '}эталон суточного объёма: <b>{status.reference ? 'есть' : 'нет'}</b>
          {' · '}<a href="#/import">Изменить в Импорте</a>
        </p>}
        {status?.problem === 'files' && <div className="note warn">В проекте нет базы расходов. Выберите её на экране <a href="#/import">Импорт</a>: осреднение берёт данные оттуда и ничего не загружает само.</div>}
        {status?.problem === 'techmap' && <div className="note warn">В библиотеке нет тех.карты вида «{kind}», поэтому неизвестны месяцы сезона. Загрузите её на экране <a href="#/techmaps">Тех.карты</a>.</div>}
        {status?.problem === 'columns' && <div className="note warn">
          <p>{status.error ? status.error : 'Из файла расходов не прочитано ни одной строки.'}</p>
          <p>Скорее всего, файл не распознан без шаблона столбцов: укажите, в каких столбцах скважина, дата и расход.</p>
          <div className="row"><button className="primary" disabled={!status.paths.length} onClick={() => setWizard(status.paths[0])}>Настроить столбцы для «{(status.paths[0] || '').split(/[\\/]/).pop()}»</button>
            <a className="btn" href="#/import">Открыть Импорт</a></div></div>}
        {status?.problem === 'wells' && <div className="note warn">
          <p>В проекте ещё нет скважин и групп. Они создаются по базе расходов и разбивке на группы.</p>
          <div className="row"><button className="primary" disabled={busy} onClick={buildWells}>Создать скважины и группы</button>
            <a className="btn" href="#/import">Открыть Импорт</a></div></div>}
        {status?.problem === 'seasons' && <div className="note warn">В базе расходов нет данных за месяцы сезона ({status.months.join(', ')}). Проверьте файл и вид «{kind}» в <a href="#/import">Импорте</a>.</div>}
        {status && !status.problem && prm && prm.mode === 'day' && <>
          <h3>Сезоны для осреднения</h3>
          <div className="row">{status.seasons.map(y => (
            <label key={y} style={{ flexDirection: 'row', gap: 6 }}><input type="checkbox" checked={chosenSeasons.includes(y)} disabled={busy} onChange={() => toggleSeason(y)} />
              {status.months[0].slice(0, 3)} {y}</label>))}</div>
          <div className="muted small">{METHOD_LABELS[prm.method]}: {METHOD_HELP[prm.method]}. Сутки считаются от старта сезона, поэтому високосный год учитывается сам.</div>
        </>}
        {status && !status.problem && prm && prm.mode === 'month' && <div className="muted small">Режим «По месяцам»: одна доля на месяц, как в прежней версии. Для долей по суткам включите «По суткам».</div>}
      </div>

      {daily && daily.days > 0 && <div className="card">
        <h2>Суточный профиль долей <span className="muted small">{daily.days} суток, сезоны {daily.seasons.join(', ')}</span></h2>
        <div className="row">
          <label>Группа<select value={dg} onChange={e => setDgrp(e.target.value)}>{Object.keys(daily.groups).map(x => <option key={x}>{x}</option>)}</select></label>
        </div>
        <DailyChart d={daily} group={dg} />
        {(daily.groups[dg]?.filled.length || 0) > 0
          ? <div className="note"><b>Сутки без данных: {daily.groups[dg].filled.length} из {daily.days}.</b> На графике они закрашены полосами. Доли в них взяты по цепочке: окно ±3 суток, окно ±7 суток, доля месяца, поровну.
            <div className="legend small">{Object.entries(fillCounts(daily.groups[dg].filled)).map(([how, c]) => <span key={how}><i style={{ background: FILL_COLORS[how] || '#d4523a' }} />{how}: {c}</span>)}</div>
            <details><summary className="small">Показать сутки</summary>
              <div className="small">{daily.groups[dg].filled.map(f => <span key={f.day} style={{ display: 'inline-block', margin: '2px 12px 2px 0' }}>
                <i style={{ display: 'inline-block', width: 9, height: 9, marginRight: 4, background: FILL_COLORS[f.how] || '#d4523a', borderRadius: 2 }} />
                {f.date.split('-').reverse().slice(0, 2).join('.')}</span>)}</div></details></div>
          : <div className="muted small">В выбранных сезонах для этой группы есть данные за все сутки.</div>}
      </div>}
      {status && !status.problem && daily && daily.days === 0 && <div className="note">Суточный профиль не построен: {daily.notes.join(' ') || 'нет данных за выбранные сезоны'}. Сценарии будут использовать доли по месяцам.</div>}

      {v && <details className="card" style={{ padding: 0 }}><summary style={{ padding: '10px 14px', cursor: 'pointer' }}><b>Подбор сезонов по месяцам</b> <span className="muted small">помощь в выборе: совет, тепловая карта, правки долей вручную</span></summary><div style={{ padding: '0 14px 14px' }}>
      <>
        {v.unknown.length > 0 && <div className="note warn">Нет в проекте (пропущены): {v.unknown.join(', ')}</div>}
        {v.skippedYears.length > 0 && <div className="note">Не вошли старые сезоны: {v.skippedYears.join(', ')} (ограничение «последних сезонов»).</div>}
        <div className="card">
          <h2>Скважины и совет <span className="muted small">сезоны {v.years.join(', ')}</span></h2>
          <div className="row"><button className="primary" disabled={busy} onClick={() => act(() => avgAdvice(kind))}>Применить совет ко всем</button></div>
          <div className="scroll"><table className="raw"><thead><tr><th>Группа</th><th>Скважина</th><th>Совет</th><th>Ошибка отл. года</th><th>Выбрано</th><th>Простой</th><th>Правок</th></tr></thead>
            <tbody>{v.wells.map(w => <tr key={w.well} className={w.well === sel ? 'hdr' : ''} onClick={() => setSel(w.well)}>
              <td>{w.group}</td><td>{w.well}</td><td>{w.advice ? w.advice.join('+') : '—'}<span className="muted small"> {w.adviceBy}</span></td>
              <td>{w.holdout == null ? '—' : w.holdout.toFixed(2)}</td><td>{w.chosen ? w.chosen.join('+') : '—'}{w.choice ? '' : <span className="muted small"> (по совету)</span>}</td>
              <td>{w.excluded.join(', ') || '—'}</td><td>{w.manual || ''}</td></tr>)}</tbody></table></div>
        </div>

        <div className="card">
          <h2>Тепловая карта: ошибка отложенного года</h2>
          <div className="muted small">Строка — скважина, столбец — комбинация сезонов. Зелёное — хорошо, красное — плохо; пусто — комбинация содержит отложенный год или не из чего считать. Рамка — выбранная комбинация. Клик по ячейке — выбрать.</div>
          <div className="scroll"><table className="raw heat"><thead><tr><th>Скв.</th>{v.combos.map(c => <th key={c}>{c.split('+').map(y => y.slice(2)).join('+')}</th>)}</tr></thead>
            <tbody>{v.heat.map(h => {
              const wr = v.wells.find(x => x.well === h.well)
              return <tr key={h.well}><th>{h.well}</th>{h.values.map((x, i) => {
                const on = wr?.chosen?.join('+') === v.combos[i]
                return <td key={i} title={v.combos[i] + (x == null ? '' : ': ' + x.toFixed(2))} style={{ background: heat(x, maxHeat), outline: on ? '2px solid var(--ink)' : undefined, cursor: x == null ? 'default' : 'pointer' }}
                  onClick={() => x != null && act(() => avgChoose(kind, h.well, combo(v.combos[i])))}>{x == null ? '' : x.toFixed(1)}</td>
              })}</tr>
            })}</tbody></table></div>
        </div>

        {row && wv && <div className="card">
          <h2>Скважина {wv.well} <span className="muted small">группа {wv.group}</span></h2>
          <Lines w={wv} onMonth={m => setEdit({ month: m, text: wv.manual[m] != null ? String(wv.manual[m] * 100) : '' })} />
          <Legend w={wv} />
          <div className="muted small">Тонкие линии — доли по годам (пунктир — год не в выбранной комбинации), толстая — итоговое среднее. Клик по названию месяца — задать долю вручную.</div>
          {edit && <div className="row"><label>{edit.month}, доля %<input value={edit.text} onChange={e => setEdit({ ...edit, text: e.target.value })} /></label>
            <button className="primary" disabled={busy} onClick={() => act(() => avgManual(kind, wv.well, edit.month, num(edit.text) / 100)).then(() => setEdit(null))}>Задать вручную</button>
            <button disabled={busy} onClick={() => act(() => avgManual(kind, wv.well, edit.month, null)).then(() => setEdit(null))}>Убрать правку</button>
            <button onClick={() => setEdit(null)}>Закрыть</button></div>}
          <h3>Годы</h3>
          <div className="row">{wv.years.map(y => {
            const off = row.excluded.includes(y)
            return <label key={y} style={{ flexDirection: 'row', gap: 6 }}><input type="checkbox" checked={!off} disabled={busy}
              onChange={() => act(() => avgExclude(kind, wv.well, y, !off))} />{y}
              {wv.autoExcluded[String(y)] && <span className="muted small">({wv.autoExcluded[String(y)]})</span>}
              {(wv.autoMonths[String(y)] || []).length > 0 && <span className="muted small">без: {wv.autoMonths[String(y)].map(m => m.slice(0, 3)).join(', ')}</span>}</label>
          })}</div>
          <h3>Комбинации <button className="link" onClick={() => act(() => avgChoose(kind, wv.well, null))}>вернуть выбор по совету</button></h3>
          <div className="scroll"><table className="raw"><thead><tr><th>Сезоны</th><th>Лет</th><th>Отл. год</th><th>Близость</th><th>Разброс</th><th /></tr></thead>
            <tbody>{wv.table.map(r => <tr key={r.years} className={r.chosen || (!row.choice && r.advice) ? 'hdr' : ''} onClick={() => act(() => avgChoose(kind, wv.well, combo(r.years)))}>
              <td>{r.years}{r.advice ? ' ★' : ''}</td><td>{r.n}</td><td>{r.holdout == null ? '—' : r.holdout.toFixed(2)}</td>
              <td>{r.closeness == null ? '—' : r.closeness.toFixed(2)}</td><td>{r.stability == null ? '—' : r.stability.toFixed(2)}</td><td>{r.chosen ? 'выбрано' : ''}</td></tr>)}</tbody></table></div>
        </div>}

        {g && <div className="card">
          <h2>Группа <select value={g} onChange={e => setGrp(e.target.value)}>{groups.map(x => <option key={x}>{x}</option>)}</select></h2>
          <GroupBars v={v} group={g} />
          <div className="legend small">{Object.keys(v.groups[g] || {}).map((w, k) => <span key={w}><i style={{ background: COLORS[k % COLORS.length] }} />{w}</span>)}</div>
          <div className="muted small">Столбец — состав группы за месяц после нормировки на 100 %. Сумма долей до нормировки: {v.months.map(m => m.slice(0, 3) + ' ' + pct(v.sums[g]?.[m], 0)).join(' · ')}.</div>
        </div>}
        {v.exclusions.length > 0 && <div className="card"><h2>Исключённые годы</h2>
          <div className="small">{v.exclusions.map(e => <div key={e.well + e.year}>{e.well}: {e.year} — {e.reason}</div>)}</div></div>}
      </>
      </div></details>}
      {wizard && <ColumnWizard st={st} setSt={setSt} initialPath={wizard} onClose={() => { setWizard(''); reload() }} />}
    </main>
  )
}
