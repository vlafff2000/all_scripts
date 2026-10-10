import { useEffect, useMemo, useState } from 'react'

import PageHead from './PageHead'
import ColumnWizard from './ColumnWizard'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import {
  AppState, AvgDaily, AvgParams, AvgStatus, AvgView, AvgWellView, avgAdvice, avgChoose, avgExclude, avgManual, buildSources, getAvgDaily, getAvgStatus,
  getAveraging, getAveragingWell, setAvgParams,
} from './api'

const pct = (x: number | null | undefined, d = 1) => (x == null ? '—' : (x * 100).toFixed(d) + ' %')
const fillCounts = (f: { how: string }[]) => f.reduce((a: Record<string, number>, x) => { a[x.how] = (a[x.how] || 0) + 1; return a }, {})
const num = (s: string) => Number(s.replace(',', '.'))

/** Цвет ячейки тепловой карты: зелёный — малая ошибка, красный — большая (в долях от максимума строки не берём: шкала общая). */
function heat(v: number | null, max: number) {
  if (v == null) return 'transparent'
  const t = Math.min(1, v / (max || 1))
  return 'hsl(' + Math.round(130 - 130 * t) + ', 55%, ' + Math.round(80 - 18 * t) + '%)'
}

const pc = (vals: (number | null)[]) => vals.map(v => (v == null ? null : v * 100))

/** Доли скважины по месяцам: линия на год, выбранное среднее жирно, правки вручную — точки (общий график, как в Газовом Атласе). */
function Lines({ w }: { w: AvgWellView }) {
  const chart = useMemo(() => {
    const used = new Set(w.chosen || [])
    const series = w.years.map((y, k) => mkSeries({
      name: String(y) + (w.autoExcluded[String(y)] ? ' (простой)' : ''), slot: k, x: w.months, y: pc(w.byYear[String(y)]),
      dashed: !used.has(y), width: used.has(y) ? 2 : 1.2, opacity: used.has(y) ? 1 : .6,
    }))
    series.push(mkSeries({ name: 'выбранное среднее', color: '#4a5a64', width: 3.5, x: w.months, y: pc(w.mean) }))
    const man = w.months.filter(m => w.manual[m] != null)
    if (man.length) series.push(mkSeries({ name: 'правка вручную', kind: 'points', color: '#d9480f', x: man, y: man.map(m => w.manual[m] * 100) }))
    return mkChart('sched-avg-' + w.well, 'Доли скважины ' + w.well + ' по годам', mkAxis('Месяц', '', 'category', { categories: w.months }), mkAxis('Доля в группе', '%', 'value', { from_zero: true }), series)
  }, [w])
  return <ChartView chart={chart} excludeMode={false} onExclude={() => {}} />
}

/** Состав группы по месяцам: столбики-доли скважин. */
function GroupBars({ v, group }: { v: AvgView; group: string }) {
  const chart = useMemo(() => {
    const ws = Object.keys(v.groups[group] || {})
    const series = ws.map((w, k) => mkSeries({
      name: w, kind: 'bar', slot: k, x: v.months, stack: 'состав',
      y: v.months.map(m => ((v.groups[group][w][m]?.share || 0) / (v.sums[group]?.[m] || 1)) * 100),
    }))
    return mkChart('sched-comp-' + group, 'Состав группы ' + group + ' по месяцам', mkAxis('Месяц', '', 'category', { categories: v.months }), mkAxis('Доля', '%', 'value', { minimum: 0, maximum: 100 }), series)
  }, [v, group])
  return <ChartView chart={chart} excludeMode={false} onExclude={() => {}} />
}

const FILL_COLORS: Record<string, string> = { 'окно ±3 суток': '#e0b43a', 'окно ±7 суток': '#e08a3a', 'доля месяца': '#d4523a', 'поровну': '#8a5bb0' }
const METHOD_LABELS: Record<string, string> = { mean: 'Среднее', median: 'Медиана', recency: 'Взвешенное по свежести', trimmed: 'Усечённое (без крайних)' }
const METHOD_HELP: Record<string, string> = {
  mean: 'простое среднее долей по выбранным сезонам', median: 'устойчива к выбросам одного сезона',
  recency: 'последний сезон весит больше предыдущих', trimmed: 'отбрасывает самый большой и самый малый сезон (от 3 сезонов)',
}

/** Суточный профиль долей скважин группы: линия на скважину; сутки, заполненные запасными правилами, отмечены на оси (события). */
function DailyChart({ d, group }: { d: AvgDaily; group: string }) {
  const g = d.groups[group]
  const chart = useMemo(() => {
    if (!g) return null
    const names = Object.keys(g.wells)
    const x = Array.from({ length: Math.max(2, d.days) }, (_, i) => i + 1)
    const c = mkChart('sched-daily-' + group, 'Суточные доли скважин группы ' + group, mkAxis('Сутки сезона', 'сут'), mkAxis('Доля в группе', '%', 'value', { from_zero: true }),
      names.map((w, k) => mkSeries({ name: w, slot: k, x, y: pc(g.wells[w]) })))
    c.events = g.filled.map(f => ({ x: f.day + 1, label: 'заполнено: ' + f.how, kind: 'other' as const, well: '' }))
    return c
  }, [d, g, group])
  if (!chart) return null
  return <div>
    <ChartView chart={chart} excludeMode={false} onExclude={() => {}} />
    <p className="muted small">Сутки отсчитываются от старта сезона; отметки на оси — сутки, где данных не было и доли заполнены по запасному правилу (список ниже).
      {d.dates ? ' Календарные даты — по последнему выбранному сезону.' : ''}</p>
  </div>
}

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
          <Lines w={wv} />
          <div className="row small"><span className="muted">Поправить долю вручную, месяц:</span>
            {wv.months.map(m => <button key={m} className="quiet" onClick={() => setEdit({ month: m, text: wv.manual[m] != null ? String(wv.manual[m] * 100) : '' })}>{m.slice(0, 3)}</button>)}</div>
          <div className="muted small">Тонкие линии — доли по годам (пунктир — год не в выбранной комбинации), толстая — итоговое среднее. Кнопки месяцев под графиком — задать долю вручную.</div>
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
