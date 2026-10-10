import { useEffect, useState } from 'react'

import PageHead from './PageHead'
import {
  AppState, CopyReport, Season, StrategyExtra, StrategyView, copyStrategy, downloadStrategy, getScenario, getStrategy, loadStrategy, pickFile, saveStrategy, strategyOp,
} from './api'

const fmt = (x: number) => x.toLocaleString('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const sgn = (x: number) => (x > 0 ? '+' : '') + fmt(x)
// число из ячейки: пробелы (в том числе неразрывные из «2 345,678») убираются; пусто — не число, а не 0
const num = (s: string) => { const t = s.replace(/[\s  ]/g, '').replace(',', '.'); return t === '' ? NaN : Number(t) }
const pc = (x: number) => x.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 2 })

// окно с флажками: группы и месяцы для деления / сезоны для копирования
function Picker({ title, hint, items, init, onOk, onClose, extra, okText }: {
  title: string; hint?: string; items: { id: string; label: string; note?: string }[]; init: string[]
  onOk: (ids: string[]) => void; onClose: () => void; extra?: React.ReactNode; okText: string
}) {
  const [on, setOn] = useState<string[]>(init)
  const toggle = (id: string) => setOn(o => (o.includes(id) ? o.filter(x => x !== id) : [...o, id]))
  return <div className="overlay" onClick={onClose}><div className="palette" style={{ padding: 14 }} onClick={e => e.stopPropagation()}>
    <h3 style={{ margin: '0 0 6px' }}>{title}</h3>
    {hint && <p className="muted small" style={{ margin: '0 0 8px' }}>{hint}</p>}
    <div className="row small"><button onClick={() => setOn(items.map(i => i.id))}>Все</button><button onClick={() => setOn([])}>Ничего</button></div>
    <div style={{ maxHeight: '40vh', overflowY: 'auto', margin: '8px 0' }}>
      {items.map(i => <label key={i.id} className="check" style={{ display: 'flex', margin: '3px 0' }}>
        <input type="checkbox" checked={on.includes(i.id)} onChange={() => toggle(i.id)} /> {i.label} {i.note && <span className="muted small">{i.note}</span>}</label>)}
    </div>
    {extra}
    <div className="row"><button className="primary" disabled={on.length === 0} onClick={() => onOk(on)}>{okText}</button><button onClick={onClose}>Отмена</button></div>
  </div></div>
}

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
  const [dlg, setDlg] = useState<'' | 'spread' | 'equal' | 'copy'>('')
  const [mode, setMode] = useState<'proportional' | 'equal'>('proportional')
  const [report, setReport] = useState<CopyReport[]>([])

  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const show = (v: StrategyView) => { setView(v); setSaved(JSON.stringify([v.custom ? v.table : v.base, v.custom ? v.locks : []])) }
  const reload = (name: string, i: number) => getStrategy(name, i).then(show).catch(e => { setView(null); setMsg(e.message) })

  useEffect(() => {
    setView(null); setInfo([]); setReport([])
    if (!sel || !st.scenarios.some(s => s.name === sel)) { setCal([]); return }
    getScenario(sel).then(v => { setCal(v.values.calendar); const i = Math.min(idx, Math.max(v.values.calendar.length - 1, 0)); setIdx(i); if (v.values.calendar.length) reload(sel, i) }).catch(e => setMsg(e.message))
  }, [sel, st])

  const pickSeason = (i: number) => { setIdx(i); reload(sel, i) }
  const op = (name: string, extra: StrategyExtra = {}, target?: number) => guard(async () => {
    // правка не записывается в сценарий, пока не нажато «Сохранить»; замки и цель живут в окне вместе с таблицей
    if (view) setView(await strategyOp(sel, idx, view.table, name, extra, view.locks, target ?? view.target))
  })
  const locked = (g: string, m: string) => !!view && view.locks.some(l => l[0] === g && l[1] === m)
  const rowLocked = (g: string) => !!view && view.months.every(m => locked(g, m))
  const colLocked = (m: string) => !!view && view.groups.every(g => locked(g, m))
  const dirty = view ? JSON.stringify([view.table, view.locks]) !== saved : false
  const save = (all: boolean) => guard(async () => {
    if (!view) return
    setSt(await saveStrategy(sel, idx, view.table, all, view.locks)); setInfo([all ? 'Стратегия записана в сезон и во все сезоны с этой тех.картой.' : 'Стратегия записана в сезон.'])
  })
  const revert = () => guard(async () => { await reload(sel, idx) })
  const xl = () => guard(async () => { await downloadStrategy(sel) })
  const load = () => guard(async () => { const r = await loadStrategy(sel, path.trim()); setSt(r.state); setInfo(r.report) })
  const pick = () => guard(async () => { const r = await pickFile(path); if (r.path) setPath(r.path) })
  const setTarget = (x: number) => setView(v => v && ({
    ...v, target: x, residual: x - v.totals.season,
    percents: Object.fromEntries(v.groups.map(g => [g, x ? 100 * v.totals.groups[g] / x : 0])),
  }))
  const spreadOk = (ids: string[]) => {
    const pick = (k: string) => ids.filter(i => i.startsWith(k + '|')).map(i => i.slice(2))
    const gs = pick('g'), ms = pick('m')
    setDlg('')
    op('spread', { groups: gs.length ? gs : undefined, months: ms.length ? ms : undefined, mode: dlg === 'equal' ? 'equal' : mode })
  }
  const copy = (ids: string[]) => guard(async () => {
    if (!view) return
    setDlg('')
    const r = await copyStrategy(sel, idx, view.table, view.locks, ids.map(Number))
    setSt(r); setReport(r.report)
  })
  const cell = (g: string, m: string, raw: string) => {
    const x = num(raw)
    if (Number.isNaN(x) || x === view!.table[g][m]) return
    if (x < 0) { setMsg('Объём не может быть отрицательным: введите 0 или больше'); return }
    op('cell', { group: g, month: m, value: x })
  }

  return (
    <main className="workspace">
      <PageHead title="Стратегии" lede="Свои объёмы по группам и месяцам вместо объёмов тех.карты, в том числе с процентным варьированием." />
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
          <thead><tr><th>Группа</th>{view.months.map(m => <th key={m}>{m} <button className="lk" disabled={busy} title={colLocked(m) ? 'Снять замок со всего месяца' : 'Зафиксировать весь месяц'}
            onClick={() => op(colLocked(m) ? 'unlock' : 'lock', { month: m })}>{colLocked(m) ? '🔒' : '🔓'}</button><div className="muted small">{view.days[m] ?? '—'} дн.</div></th>)}<th>За сезон</th><th>% от сезона</th></tr></thead>
          <tbody>
            {view.groups.map(g => (
              <tr key={g}>
                <td>{g} <button className="lk" disabled={busy} title={rowLocked(g) ? 'Снять замок со всей группы' : 'Зафиксировать всю группу'}
                  onClick={() => op(rowLocked(g) ? 'unlock' : 'lock', { group: g })}>{rowLocked(g) ? '🔒' : '🔓'}</button></td>
                {view.months.map(m => {
                  const x = view.table[g][m], b = view.base[g][m]
                  return <td key={m} className={(x !== b ? 'ch' : '') + (locked(g, m) ? ' lkd' : '')}>
                    <button className="lk" disabled={busy} title={locked(g, m) ? 'Снять замок' : 'Зафиксировать: разница не будет размазываться на эту ячейку'}
                      onClick={() => op(locked(g, m) ? 'unlock' : 'lock', { group: g, month: m })}>{locked(g, m) ? '🔒' : '🔓'}</button>
                    <input style={{ width: 84, textAlign: 'right' }} defaultValue={fmt(x)} key={g + m + x} disabled={busy}
                      title={x !== b ? 'В тех.карте ' + fmt(b) : ''} onBlur={e => cell(g, m, e.target.value)} /></td>
                })}
                <td><input style={{ width: 96, textAlign: 'right' }} defaultValue={fmt(view.totals.groups[g])} key={g + 't' + view.totals.groups[g]} disabled={busy}
                  title="Ввести сумму группы: месяцы пересчитаются пропорционально"
                  onBlur={e => { const x = num(e.target.value); if (!Number.isNaN(x) && Math.abs(x - view.totals.groups[g]) > 5e-4) op('group_total', { group: g, value: x }) }} /></td>
                <td><input style={{ width: 64, textAlign: 'right' }} defaultValue={pc(view.percents[g])} key={g + 'p' + view.percents[g]} disabled={busy}
                  title="Доля группы в сезоне: остальные свободные группы пересчитаются так, чтобы сумма сезона не изменилась"
                  onBlur={e => { const x = num(e.target.value); if (!Number.isNaN(x) && Math.abs(x - view.percents[g]) > 5e-3) op('group_percent', { group: g, value: x }) }} /> %</td>
              </tr>))}
            <tr className="tot"><td><b>Итого</b></td>{view.months.map(m => <td key={m} className="num"><b>{fmt(view.totals.months[m])}</b></td>)}<td className="num"><b>{fmt(view.totals.season)}</b></td>
              <td className={'num' + (Math.abs(view.residual) > 5e-4 ? ' bad' : '')}><b>{pc(Object.values(view.percents).reduce((a, b) => a + b, 0))} %</b></td></tr>
            <tr><td className="muted small">В тех.карте</td>{view.months.map(m => <td key={m} className="num muted small">{fmt(view.base_totals.months[m])}</td>)}<td className="num muted small">{fmt(view.base_totals.season)}</td></tr>
            <tr><td className="muted small">Изменение</td>{view.months.map(m => <td key={m} className={'num small' + (Math.abs(view.changes.months[m]) > 5e-4 ? ' bad' : ' muted')}>{sgn(view.changes.months[m])}</td>)}
              <td className={'num small' + (Math.abs(view.changes.season) > 5e-4 ? ' bad' : ' muted')}>{sgn(view.changes.season)}</td></tr>
            <tr><td className="muted small">% к месяцу</td>{view.months.map(m => <td key={m}>
              <input style={{ width: 54 }} placeholder="110" value={pct[m] ?? ''} onChange={e => setPct(p => ({ ...p, [m]: e.target.value }))} />
              <button disabled={busy || !(num(pct[m] ?? '') >= 0) || !(pct[m] ?? '').trim()} onClick={() => op('month_percent', { month: m, value: num(pct[m]) })}>%</button></td>)}<td /><td /></tr>
          </tbody>
        </table>
        <div className={'note' + (Math.abs(view.residual) > 5e-4 ? ' warn' : '')} style={{ marginTop: 8 }}>
          <div className="row">
            <span>Сумма сезона (цель, млн м³):{' '}
              <input style={{ width: 96, textAlign: 'right' }} defaultValue={fmt(view.target)} key={'tg' + view.target} disabled={busy}
                title="По умолчанию — сумма тех.карты; можно задать свою"
                onBlur={e => { const x = num(e.target.value); if (!Number.isNaN(x) && x >= 0 && Math.abs(x - view.target) > 5e-4) setTarget(x) }} /></span>
            <b>К размазыванию: {sgn(view.residual)} млн м³</b>
            <span className="muted small">зафиксировано ячеек: {view.locks.length}</span>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button disabled={busy || Math.abs(view.residual) <= 5e-4} title="По всем незафиксированным ячейкам пропорционально текущим значениям" onClick={() => op('spread', { mode: 'proportional' })}>Размазать по остальным</button>
            <button disabled={busy || Math.abs(view.residual) <= 5e-4} title="Выбрать группы и месяцы" onClick={() => { setMode('proportional'); setDlg('spread') }}>Размазать…</button>
            <button disabled={busy || Math.abs(view.residual) <= 5e-4} title="Выбрать группы и месяцы, поровну" onClick={() => setDlg('equal')}>Разделить изменение поровну…</button>
            <button disabled={busy || view.locks.length === 0} onClick={() => op('unlock_all')}>Снять все замки</button>
          </div>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button disabled={busy} title="Все ячейки × (сумма тех.карты / сумма таблицы)" onClick={() => op('normalize')}>Нормализовать к тех.карте</button>
          <button disabled={busy} title="Сумма тех.карты поровну на каждую ячейку" onClick={() => op('equal')}>Сбросить в равномерное</button>
          <button disabled={busy} onClick={() => op('reset')}>Вернуть тех.карту</button>
          {dirty && <button disabled={busy} onClick={revert}>Отменить правки</button>}
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="primary" disabled={busy || !dirty} onClick={() => save(false)}>Сохранить в сезон</button>
          <button disabled={busy || !dirty} title="Копия таблицы во все сезоны с этой тех.картой" onClick={() => save(true)}>Сохранить и применить ко всем годам</button>
          <button disabled={busy || cal.length < 2} title="Таблица (с замками) в выбранные сезоны календаря" onClick={() => setDlg('copy')}>Копировать на другие сезоны…</button>
          {dirty && <span className="muted small">Есть несохранённые правки.</span>}
        </div>
        {report.length > 0 && <ul className="issues">{report.map(r => <li key={r.index} className={r.skipped.length ? 'warn' : ''}>{r.message}</li>)}</ul>}
        <p className="muted small">Группы и месяцы берутся из тех.карты; значения меньше нуля не принимаются. Правка ячейки или группы её фиксирует (🔒), а разница к сумме сезона остаётся «к размазыванию». Изменение сезона: {sgn(view.changes.season)} млн м³.</p>
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
      {view && (dlg === 'spread' || dlg === 'equal') && <Picker okText={dlg === 'equal' ? 'Разделить поровну' : 'Размазать'} onClose={() => setDlg('')} onOk={spreadOk}
        title={dlg === 'equal' ? 'Разделить изменение поровну' : 'Размазать разницу'}
        hint={'Разница ' + sgn(view.residual) + ' млн м³ делится между незафиксированными ячейками выбранных групп и месяцев. Если в разделе ничего не отмечено, берутся все.'}
        items={[...view.groups.map(g => ({ id: 'g|' + g, label: 'Группа ' + g })), ...view.months.map(m => ({ id: 'm|' + m, label: 'Месяц ' + m }))]}
        init={[...view.groups.map(g => 'g|' + g), ...view.months.map(m => 'm|' + m)]}
        extra={dlg === 'spread' ? <div className="row small" style={{ margin: '6px 0' }}>
          <label className="check"><input type="radio" checked={mode === 'proportional'} onChange={() => setMode('proportional')} /> пропорционально текущим</label>
          <label className="check"><input type="radio" checked={mode === 'equal'} onChange={() => setMode('equal')} /> поровну</label></div> : undefined} />}
      {view && dlg === 'copy' && <Picker title="Копировать на другие сезоны" okText="Копировать" onClose={() => setDlg('')} onOk={copy}
        hint="Таблица (с замками) переносится по именам групп и месяцев; что не нашлось в тех.карте сезона, будет в отчёте. Сохранять сезон до копирования не нужно."
        items={cal.map((e, i) => ({ id: String(i), label: e.year + ' · ' + e.techmap, note: i === idx ? '(текущий — пропускается)' : '' })).filter((_, i) => i !== idx)}
        init={cal.map((e, i) => (e.techmap === view.techmap && i !== idx ? String(i) : '')).filter(Boolean)} />}
    </main>
  )
}
