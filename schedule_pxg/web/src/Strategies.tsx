import { useEffect, useState } from 'react'
import {
  AppState, Season, StrategyView, downloadStrategy, getScenario, getStrategy, loadStrategy, pickFile, saveStrategy, strategyOp,
} from './api'

const fmt = (x: number) => x.toLocaleString('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const sgn = (x: number) => (x > 0 ? '+' : '') + fmt(x)
const num = (s: string) => Number(s.replace(',', '.'))

export default function Strategies({ st, setSt }: { st: AppState; setSt: (s: AppState) => void }) {
  const [sel, setSel] = useState('')
  const [cal, setCal] = useState<Season[]>([])
  const [idx, setIdx] = useState(0)
  const [view, setView] = useState<StrategyView | null>(null)
  const [saved, setSaved] = useState('')
  const [pct, setPct] = useState<Record<string, string>>({})
  const [path, setPath] = useState('')
  const [msg, setMsg] = useState('')
  const [info, setInfo] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const show = (v: StrategyView) => { setView(v); setSaved(JSON.stringify(v.custom ? v.table : v.base)) }
  const reload = (name: string, i: number) => getStrategy(name, i).then(show).catch(e => { setView(null); setMsg(e.message) })

  useEffect(() => {
    setView(null); setInfo([])
    if (!sel || !st.scenarios.some(s => s.name === sel)) { setCal([]); return }
    getScenario(sel).then(v => { setCal(v.values.calendar); const i = Math.min(idx, Math.max(v.values.calendar.length - 1, 0)); setIdx(i); if (v.values.calendar.length) reload(sel, i) }).catch(e => setMsg(e.message))
  }, [sel, st])

  const pickSeason = (i: number) => { setIdx(i); reload(sel, i) }
  const op = (name: string, extra: { group?: string; month?: string; value?: number } = {}) => guard(async () => {
    // правка не записывается в сценарий, пока не нажато «Сохранить»
    if (view) setView(await strategyOp(sel, idx, view.table, name, extra))
  })
  const dirty = view ? JSON.stringify(view.table) !== saved : false
  const save = (all: boolean) => guard(async () => {
    if (!view) return
    setSt(await saveStrategy(sel, idx, view.table, all)); setInfo([all ? 'Стратегия записана в сезон и во все сезоны с этой тех.картой.' : 'Стратегия записана в сезон.'])
  })
  const revert = () => guard(async () => { await reload(sel, idx) })
  const xl = () => guard(async () => { await downloadStrategy(sel) })
  const load = () => guard(async () => { const r = await loadStrategy(sel, path.trim()); setSt(r.state); setInfo(r.report) })
  const pick = () => guard(async () => { const r = await pickFile(path); if (r.path) setPath(r.path) })
  const cell = (g: string, m: string, raw: string) => {
    const x = num(raw)
    if (Number.isNaN(x) || x === view!.table[g][m]) return
    op('cell', { group: g, month: m, value: x })
  }

  return (
    <main className="work">
      <section className="card">
        <h2>Стратегии варьирования</h2>
        <p className="muted small">Объёмы сезона по группам и месяцам (млн м³) вместо объёмов тех.карты. Процент сценария и сезона применяется после замены; ветвь сценария может иметь свою стратегию.</p>
        {st.scenarios.length === 0 ? <p className="muted">Сначала создайте сценарий с календарём сезонов (вкладка «Сценарии»).</p> : (
          <div className="row">
            <label>Сценарий<br /><select value={sel} onChange={e => { setSel(e.target.value); setIdx(0) }}>
              <option value="">—</option>{st.scenarios.map(s => <option key={s.name}>{s.name}</option>)}</select></label>
            <label>Сезон<br /><select value={idx} disabled={cal.length === 0} onChange={e => pickSeason(Number(e.target.value))}>
              {cal.map((e, i) => <option key={i} value={i}>{e.year} · {e.techmap}{e.volumes ? ' ✎' : ''}</option>)}</select></label>
          </div>)}
        {sel && cal.length === 0 && <p className="muted">В календаре сценария нет сезонов.</p>}
        {msg && <p className="note warn">{msg}</p>}
      </section>

      {view && <section className="card">
        <h2>{view.techmap}, {view.year} <span className="muted small">— {view.kind || 'вид не задан'}, млн м³{view.custom ? ' · стратегия задана' : ' · как в тех.карте'}</span></h2>
        <table className="raw">
          <thead><tr><th>Группа</th>{view.months.map(m => <th key={m}>{m}<div className="muted small">{view.days[m] ?? '—'} дн.</div></th>)}<th>За сезон</th></tr></thead>
          <tbody>
            {view.groups.map(g => (
              <tr key={g}>
                <td>{g}</td>
                {view.months.map(m => {
                  const x = view.table[g][m], b = view.base[g][m]
                  return <td key={m} className={x !== b ? 'ch' : ''}>
                    <input style={{ width: 84, textAlign: 'right' }} defaultValue={fmt(x)} key={g + m + x} disabled={busy}
                      title={x !== b ? 'В тех.карте ' + fmt(b) : ''} onBlur={e => cell(g, m, e.target.value)} /></td>
                })}
                <td><input style={{ width: 96, textAlign: 'right' }} defaultValue={fmt(view.totals.groups[g])} key={g + 't' + view.totals.groups[g]} disabled={busy}
                  title="Ввести сумму группы: месяцы пересчитаются пропорционально"
                  onBlur={e => { const x = num(e.target.value); if (!Number.isNaN(x) && Math.abs(x - view.totals.groups[g]) > 5e-4) op('group_total', { group: g, value: x }) }} /></td>
              </tr>))}
            <tr className="tot"><td><b>Итого</b></td>{view.months.map(m => <td key={m} className="num"><b>{fmt(view.totals.months[m])}</b></td>)}<td className="num"><b>{fmt(view.totals.season)}</b></td></tr>
            <tr><td className="muted small">В тех.карте</td>{view.months.map(m => <td key={m} className="num muted small">{fmt(view.base_totals.months[m])}</td>)}<td className="num muted small">{fmt(view.base_totals.season)}</td></tr>
            <tr><td className="muted small">Изменение</td>{view.months.map(m => <td key={m} className={'num small' + (Math.abs(view.changes.months[m]) > 5e-4 ? ' bad' : ' muted')}>{sgn(view.changes.months[m])}</td>)}
              <td className={'num small' + (Math.abs(view.changes.season) > 5e-4 ? ' bad' : ' muted')}>{sgn(view.changes.season)}</td></tr>
            <tr><td className="muted small">% к месяцу</td>{view.months.map(m => <td key={m}>
              <input style={{ width: 54 }} placeholder="110" value={pct[m] ?? ''} onChange={e => setPct(p => ({ ...p, [m]: e.target.value }))} />
              <button disabled={busy || !(num(pct[m] ?? '') >= 0) || !(pct[m] ?? '').trim()} onClick={() => op('month_percent', { month: m, value: num(pct[m]) })}>%</button></td>)}<td /></tr>
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 8 }}>
          <button disabled={busy} title="Все ячейки × (сумма тех.карты / сумма таблицы)" onClick={() => op('normalize')}>Нормализовать к тех.карте</button>
          <button disabled={busy} title="Сумма тех.карты поровну на каждую ячейку" onClick={() => op('equal')}>Поровну</button>
          <button disabled={busy} onClick={() => op('reset')}>Вернуть тех.карту</button>
          {dirty && <button disabled={busy} onClick={revert}>Отменить правки</button>}
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="primary" disabled={busy || !dirty} onClick={() => save(false)}>Сохранить в сезон</button>
          <button disabled={busy || !dirty} title="Копия таблицы во все сезоны с этой тех.картой" onClick={() => save(true)}>Сохранить и применить ко всем годам</button>
          {dirty && <span className="muted small">Есть несохранённые правки.</span>}
        </div>
        <p className="muted small">Группы и месяцы берутся из тех.карты; значения меньше нуля не принимаются. Изменение сезона: {sgn(view.changes.season)} млн м³.</p>
      </section>}

      {sel && cal.length > 0 && <section className="card">
        <h2>Excel</h2>
        <p className="muted small">Листы «Закачка_&lt;год&gt;» и «Отбор_&lt;год&gt;» — как в файлах стратегии прежнего редактора; при загрузке лист ложится в сезон с тем же видом тех.карты и годом.</p>
        <div className="row">
          <button disabled={busy} onClick={xl}>Скачать стратегию сценария</button>
          <input className="grow" value={path} placeholder="Файл стратегии (.xlsx)" onChange={e => setPath(e.target.value)} />
          <button disabled={busy} onClick={pick}>Выбрать…</button>
          <button className="primary" disabled={busy || !path.trim()} onClick={load}>Загрузить в сценарий</button>
        </div>
        {info.length > 0 && <ul className="issues">{info.map((n, i) => <li key={i} className={n.includes('пропущен') ? 'warn' : ''}>{n}</li>)}</ul>}
      </section>}
    </main>
  )
}
