import { useEffect, useState } from 'react'

import PageHead from './PageHead'
import {
  AppState, BuildView, ScenarioInfo, ScenarioView, Season, buildScenario, createScenario, deleteScenario, expandPattern, getScenario,
  inheritScenario, percentBranches, scheduleUrl, setScenario,
} from './api'

const STEPS: [string, string][] = [['day', 'сутки'], ['week', 'неделя'], ['decade', 'декада'], ['half', 'полмесяца'], ['month', 'месяц']]
const num = (s: string) => Number(s.replace(',', '.'))

function order(list: ScenarioInfo[]): { s: ScenarioInfo; depth: number }[] {
  const out: { s: ScenarioInfo; depth: number }[] = []
  const walk = (parent: string | null, depth: number) =>
    list.filter(x => x.parent === parent).forEach(x => { out.push({ s: x, depth }); walk(x.name, depth + 1) })
  walk(null, 0)
  return out
}

export default function Scenarios({ st, setSt }: { st: AppState; setSt: (s: AppState) => void }) {
  const [sel, setSel] = useState('')
  const [view, setView] = useState<ScenarioView | null>(null)
  const [cal, setCal] = useState<Season[]>([])
  const [build, setBuild] = useState<BuildView | null>(null)
  const [newName, setNewName] = useState('')
  const [pattern, setPattern] = useState<string[]>([])
  const [years, setYears] = useState<[number, number]>([new Date().getFullYear(), new Date().getFullYear() + 1])
  const [variants, setVariants] = useState('90, 110')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const maps = st.techmaps.map(t => t.name)

  const load = (name: string) => getScenario(name).then(v => { setView(v); setCal(v.values.calendar); setBuild(null) }).catch(e => setMsg(e.message))
  useEffect(() => { if (sel && st.scenarios.some(s => s.name === sel)) load(sel); else { setView(null); setCal([]) } }, [sel, st])

  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const create = (parent: string | null) => guard(async () => {
    const n = newName.trim()
    setSt(await createScenario(n, parent)); setSel(n); setNewName('')
  })
  const put = (key: string, value: unknown) => guard(async () => { setSt(await setScenario(sel, key, value)) })
  const back = (key: string) => guard(async () => { setSt(await inheritScenario(sel, key)) })
  const remove = () => guard(async () => {
    if (!window.confirm('Удалить сценарий «' + sel + '»?')) return
    setSt(await deleteScenario(sel)); setSel('')
  })
  const expand = () => guard(async () => { setCal((await expandPattern(pattern, years[0], years[1])).calendar) })
  const variantsGo = () => guard(async () => {
    const ps = variants.split(/[;,\s]+/).filter(Boolean).map(num)
    if (ps.some(p => !(p > 0))) throw new Error('Проценты — положительные числа через запятую')
    setSt(await percentBranches(sel, ps))
  })
  const run = () => guard(async () => { setBuild(await buildScenario(sel)) })
  const upd = (i: number, patch: Partial<Season>) => setCal(c => c.map((e, k) => (k === i ? { ...e, ...patch, ...(patch.techmap && patch.techmap !== e.techmap ? { volumes: undefined } : {}) } : e)))

  const v = view?.values
  const isBranch = !!view?.parent
  const tag = (key: string) => {
    if (!view || !isBranch) return null
    const own = view.origin[key]
    return own === view.name
      ? <span className="muted small"> · задано здесь <button className="link" onClick={() => back(key)}>вернуть как у родителя</button></span>
      : <span className="muted small"> · как у «{own || view.parent}»</span>
  }
  const calDirty = v ? JSON.stringify(cal) !== JSON.stringify(v.calendar) : false

  return (
    <main className="workspace">
      <PageHead title="Сценарии" lede="Основные сценарии и их ветви: у ветви хранятся только отличия от родителя." />
      <section className="card">
        <h2>Сценарии и ветви</h2>
        {st.scenarios.length === 0 && <p className="muted">Пока нет. Создайте основной сценарий: у него полные настройки, ветви хранят только отличия.</p>}
        <div className="sc-list" role="list">
          {order(st.scenarios).map(({ s, depth }) => (
            <button key={s.name} role="listitem" className={'sc-item' + (s.name === sel ? ' on' : '')} aria-pressed={s.name === sel}
              style={{ marginLeft: depth * 20 }} onClick={() => setSel(s.name)}>
              <span className="sc-name">{depth ? '↳ ' : ''}{s.name}</span>
              <span className="sc-meta">{s.percent}% · сезонов: {s.seasons}</span>
            </button>))}
        </div>
        <div className="row sc-new">
          <label className="grow">Название нового сценария
            <input value={newName} placeholder="Например, База 2027" onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && newName.trim() && !busy && create(null)} /></label>
          <button disabled={busy || !newName.trim()} onClick={() => create(null)}>Новый основной</button>
          <button className="primary" disabled={busy || !newName.trim() || !sel} onClick={() => create(sel)}
            title={sel ? '' : 'Сначала выберите сценарий в списке'}>Ветвь от «{sel || '…'}»</button>
        </div>
      </section>

      {view && v && <>
        <section className="card">
          <h2>{view.name} {isBranch && <span className="muted small">— ветвь от «{view.parent}»</span>}</h2>
          {isBranch && (view.diff.length === 0 ? <p className="muted">Отличий от родителя нет.</p> :
            <><p className="note">Отличия от родителя: {view.diff.map(d => d.label).join(', ')}. Остальное берётся у родителя и меняется вместе с ним.</p></>)}
          <div className="row sc-fields">
            <label>Процент от тех.карты{tag('percent')}<br />
              <input defaultValue={v.percent} key={'p' + v.percent} onBlur={e => num(e.target.value) !== v.percent && put('percent', num(e.target.value))} /></label>
            <label>Допуск сверки{tag('tolerance')}<br />
              <input defaultValue={v.tolerance} key={'t' + v.tolerance} onBlur={e => num(e.target.value) !== v.tolerance && put('tolerance', num(e.target.value))} /></label>
            <label>Знаков в дебите{tag('decimals')}<br />
              <input defaultValue={v.decimals} key={'d' + v.decimals} onBlur={e => num(e.target.value) !== v.decimals && put('decimals', num(e.target.value))} /></label>
            <label>Шаг сетки{tag('grid')}<br />
              <select value={v.grid.step} onChange={e => put('grid', { ...v.grid, step: e.target.value })}>
                {STEPS.map(([k, n]) => <option key={k} value={k}>{n}</option>)}</select></label>
          </div>
          <label>Примечание{tag('note')}<br />
            <input className="sc-wide" defaultValue={v.note} key={'n' + v.note} onBlur={e => e.target.value !== v.note && put('note', e.target.value)} /></label>
          <p className="muted small">Режим управления: {v.control.mode ? v.control.mode + ', ' + (v.control.level || 'wells') + ', лимитов: ' + (v.control.limits?.length || 0) : 'по умолчанию'}{tag('control')}
            {' · '}отключений: {v.outages.length}{tag('outages')}</p>
        </section>

        <section className="card">
          <h2>Календарь сезонов{tag('calendar')}</h2>
          {maps.length === 0 ? <p className="muted">Сначала сохраните тех.карты в библиотеку (вкладка «Тех.карты»).</p> : <>
            <div className="row sc-pattern">
              <span className="muted small">Повторить по шаблону:</span>
              {pattern.map((n, i) => <button key={i} className="x" title="Убрать из шаблона" onClick={() => setPattern(p => p.filter((_, k) => k !== i))}>{n} ×</button>)}
              <select value="" onChange={e => e.target.value && setPattern(p => [...p, e.target.value])}>
                <option value="">+ карта</option>{maps.map(n => <option key={n}>{n}</option>)}</select>
              <label>с <input className="sc-num" value={years[0]} onChange={e => setYears([num(e.target.value), years[1]])} /></label>
              <label>до <input className="sc-num" value={years[1]} onChange={e => setYears([years[0], num(e.target.value)])} /></label>
              <button disabled={busy || pattern.length === 0} onClick={expand}>Заполнить</button>
            </div>
            <p className="muted small">Карты идут по кругу: [закачка, отбор] — каждый год; [закачка A, отбор, закачка B, отбор] — чередование A, B, A…</p>
          </>}
          {cal.length > 0 && <div className="scroll sc-cal"><table className="raw"><thead><tr><th>Год начала</th><th>Тех.карта</th><th>% сезона</th><th>Подпись</th><th /></tr></thead>
            <tbody>{cal.map((e, i) => (
              <tr key={i}>
                <td><input className="sc-num" value={e.year} onChange={ev => upd(i, { year: num(ev.target.value) })} /></td>
                <td><select value={e.techmap} onChange={ev => upd(i, { techmap: ev.target.value })}>
                  {!maps.includes(e.techmap) && <option>{e.techmap}</option>}{maps.map(n => <option key={n}>{n}</option>)}</select></td>
                <td><input className="sc-num" value={e.percent} onChange={ev => upd(i, { percent: num(ev.target.value) })} /></td>
                <td><input value={e.label} onChange={ev => upd(i, { label: ev.target.value })} /></td>
                <td><button className="x" title="Убрать сезон" onClick={() => setCal(c => c.filter((_, k) => k !== i))}>×</button></td>
              </tr>))}</tbody></table></div>}
          <div className="row sc-actions">
            <button disabled={maps.length === 0} onClick={() => setCal(c => [...c, { year: (c.length ? c[c.length - 1].year : years[0]), techmap: maps[0], percent: 100, label: '' }])}>+ сезон</button>
            <button className="primary" disabled={busy || !calDirty} onClick={() => put('calendar', cal)}>Сохранить календарь</button>
            {calDirty && <button onClick={() => setCal(v.calendar)}>Отменить</button>}
          </div>
          {view.notes.length > 0 && <ul className="issues">{view.notes.map((n, i) => <li key={i} className="warn">{n}</li>)}</ul>}
        </section>

        <section className="card">
          <h2>Варианты и проверка</h2>
          <div className="row">
            <span className="muted small">Варианты в процентах от этого сценария (ветви):</span>
            <input value={variants} onChange={e => setVariants(e.target.value)} />
            <button disabled={busy} onClick={variantsGo}>Создать ветви</button>
          </div>
          <div className="row sc-actions">
            <button className="primary" disabled={busy || cal.length === 0 || calDirty} onClick={run}>Сшить сезоны и проверить</button>
            {build && build.steps > 0 && <a href={scheduleUrl(sel)}><button>Скачать schedule.inc</button></a>}
            <button className="danger sc-end" disabled={busy || view.children.length > 0} title={view.children.length ? 'Сначала удалите ветви' : ''} onClick={remove}>Удалить сценарий</button>
          </div>
          {build && <>
            <p className="note">Шагов: {build.steps}. Расхождений с тех.картой сверх допуска: {build.over} из {build.rows}. {build.stitch.length ? 'Стык: есть замечания.' : 'Стык сезонов без дыр и наложений.'}</p>
            <div className="scroll"><table className="raw"><thead><tr><th>Тех.карта</th><th>Год</th><th>%</th><th>С</th><th>По</th><th>Шагов</th><th>Сверх допуска</th></tr></thead>
              <tbody>{build.seasons.map((s, i) => <tr key={i}><td>{s.techmap}{s.strategy && <span className="muted small" title="Объёмы заменены стратегией"> · стратегия</span>}</td><td>{s.year}</td><td className="num">{s.percent}</td><td>{s.from}</td><td>{s.to}</td>
                <td className="num">{s.steps}</td><td className={'num' + (s.over ? ' bad' : '')}>{s.over}</td></tr>)}</tbody></table></div>
            {build.gaps.length > 0 && <p className="muted small">Между сезонами скважины закрыты (нейтральный шаг): {build.gaps.map(g => g.from + ' — ' + g.to + ' (' + g.days + ' сут)').join('; ')}.</p>}
            {[...build.stitch, ...build.notes].length > 0 && <ul className="issues">{[...build.stitch, ...build.notes].map((n, i) => <li key={i} className="warn">{n}</li>)}</ul>}
            <p className="muted small">{build.shares}.</p>
          </>}
        </section>
      </>}
      {msg && <p className="note warn">{msg}</p>}
    </main>
  )
}
