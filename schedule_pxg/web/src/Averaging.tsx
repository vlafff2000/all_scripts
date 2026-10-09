import { useEffect, useState } from 'react'
import PageHead from './PageHead'
import {
  AppState, AvgView, AvgWellView, avgAdvice, avgChoose, avgExclude, avgManual, getAveraging, getAveragingWell, pickFile, setAvgSources,
} from './api'

const COLORS = ['#2f6fb0', '#c4622d', '#3f9a6a', '#8a5bb0', '#b09a2f', '#2f9aa8', '#b0426b', '#6b7a8a']
const pct = (x: number | null | undefined, d = 1) => (x == null ? '—' : (x * 100).toFixed(d) + ' %')
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

export default function Averaging({ st }: { st: AppState }) {
  const [kind, setKind] = useState('закачка')
  const [v, setV] = useState<AvgView | null>(null)
  const [sel, setSel] = useState('')
  const [wv, setWv] = useState<AvgWellView | null>(null)
  const [paths, setPaths] = useState('')
  const [prm, setPrm] = useState({ max_years: 6, last_k: 3, metric: 'rmse' })
  const [edit, setEdit] = useState<{ month: string; text: string } | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const apply = (x: AvgView) => { setV(x); setPaths(x.sources.join('\n')); setPrm(x.params) }
  const reload = () => guard(async () => apply(await getAveraging(kind)))
  useEffect(() => { setV(null); setSel(''); getAveraging(kind).then(apply).catch(e => setMsg(e.message)) }, [kind, st])
  useEffect(() => { if (v && sel && v.wells.some(w => w.well === sel)) getAveragingWell(kind, sel).then(setWv).catch(e => setMsg(e.message)); else setWv(null) }, [sel, v])

  const act = (f: () => Promise<AvgView>) => guard(async () => apply(await f()))
  const sources = () => guard(async () => apply(await setAvgSources(kind, paths.split('\n').map(s => s.trim()).filter(Boolean), prm)))
  const pick = () => guard(async () => { const r = await pickFile(paths.split('\n')[0] || ''); if (r.path) setPaths(p => (p.trim() ? p.trim() + '\n' : '') + r.path) })
  const row = v?.wells.find(w => w.well === sel)
  const maxHeat = v ? Math.max(0, ...v.heat.flatMap(h => h.values.filter((x): x is number => x != null))) : 0
  const combo = (c: string) => c.split('+').map(Number)
  const groups = v ? Array.from(new Set(v.wells.map(w => w.group))) : []
  const [grp, setGrp] = useState('')
  const g = grp && groups.includes(grp) ? grp : groups[0] || ''

  return (
    <main className="workspace">
      <PageHead title="Осреднение" lede="Из истории работы скважин по годам получаем средний расход, на котором строится прогноз." />
      <div className="card">
        <h2>Осреднение истории: источники</h2>
        <div className="row">
          <label>Вид<select value={kind} onChange={e => setKind(e.target.value)}><option>закачка</option><option>отбор</option></select></label>
          <label>Последних сезонов<input type="number" min={2} max={10} value={prm.max_years} onChange={e => setPrm({ ...prm, max_years: Number(e.target.value) })} /></label>
          <label>Близость к последним<input type="number" min={1} max={5} value={prm.last_k} onChange={e => setPrm({ ...prm, last_k: Number(e.target.value) })} /></label>
          <label>Ошибка<select value={prm.metric} onChange={e => setPrm({ ...prm, metric: e.target.value })}><option value="rmse">RMSE, п.п.</option><option value="mape">MAPE, %</option></select></label>
        </div>
        <label>Файлы истории (по одному в строке)<textarea rows={3} value={paths} onChange={e => setPaths(e.target.value)} /></label>
        <div className="row"><button onClick={pick} disabled={busy}>Выбрать файл…</button>
          <button className="primary" onClick={sources} disabled={busy || !paths.trim()}>Посчитать</button>
          <button onClick={reload} disabled={busy}>Обновить</button></div>
        <div className="muted small">Файлы, годы и правки сохраняются в проекте; сценарии берут доли отсюда. Без файлов доли в сценариях делятся поровну.</div>
        {msg && <div className="note warn">{msg}</div>}
      </div>

      {v && <>
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
      </>}
    </main>
  )
}
