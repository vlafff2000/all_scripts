import { useState } from 'react'
import { AppState, TechMapView, deleteTechMap, getTechMap, pickFile, readTechMap, saveTechMap } from './api'

const fmt = (x: number | undefined) => (x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: 3 }))

export default function TechMaps({ st, setSt }: { st: AppState; setSt: (s: AppState) => void }) {
  const [path, setPath] = useState('')
  const [name, setName] = useState('')
  const [kind, setKind] = useState('')
  const [view, setView] = useState<TechMapView | null>(null)
  const [saved, setSaved] = useState(false)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const pick = () => guard(async () => { const r = await pickFile(path); if (r.path) setPath(r.path) })
  const load = () => guard(async () => {
    const v = await readTechMap(path.trim(), name.trim(), kind)
    setView(v); setName(v.techmap.name); setKind(v.techmap.kind); setSaved(false)
  })
  const open = (n: string) => guard(async () => { const v = await getTechMap(n); setView(v); setName(n); setKind(v.techmap.kind); setSaved(true) })
  const save = () => guard(async () => {
    if (!view) return
    const exists = st.techmaps.some(t => t.name === name.trim())
    if (exists && !window.confirm('Тех.карта «' + name + '» уже есть в библиотеке. Заменить?')) return
    setSt(await saveTechMap({ ...view.techmap, name: name.trim(), kind }, exists)); setSaved(true)
    setMsg('Тех.карта «' + name.trim() + '» сохранена в библиотеке проекта')
  })
  const remove = (n: string) => guard(async () => { setSt(await deleteTechMap(n)); if (view?.techmap.name === n) setView(null) })
  const tm = view?.techmap

  return (
    <main className="workspace">
      <section className="card">
        <h2>Библиотека тех.карт</h2>
        {st.techmaps.length === 0 ? <p className="muted">Пока пусто. Загрузите файл «Утверждённые объёмы» ниже и сохраните его в проект.</p> : (
          <table className="raw"><thead><tr><th>Название</th><th>Вид</th><th>Месяцы</th><th>Групп</th><th>Итого, млн м³</th><th /></tr></thead>
            <tbody>{st.techmaps.map(t => (
              <tr key={t.name}>
                <td><button className="link" onClick={() => open(t.name)}>{t.name}</button></td>
                <td>{t.kind}</td><td>{t.months[0]} — {t.months[t.months.length - 1]}</td><td className="num">{t.groups}</td>
                <td className="num">{fmt(t.total)}</td>
                <td><button className="x" title="Удалить из библиотеки" onClick={() => remove(t.name)}>×</button></td>
              </tr>))}</tbody></table>
        )}
      </section>

      <section className="card">
        <h2>Импорт из Excel</h2>
        <div className="row">
          <input className="grow" value={path} placeholder="Путь к файлу «Утверждённые объёмы»" onChange={e => setPath(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && path.trim() && load()} />
          <button onClick={pick} disabled={busy}>Выбрать…</button>
          <button className="primary" onClick={load} disabled={busy || !path.trim()}>Показать</button>
        </div>
      </section>

      {tm && view && (
        <section className="card">
          <h2>Тех.карта</h2>
          <div className="row">
            <input value={name} placeholder="Название" onChange={e => { setName(e.target.value); setSaved(false) }} />
            <select value={kind} onChange={e => { setKind(e.target.value); setSaved(false) }}>
              <option value="">вид не задан</option>{view.kinds.map(k => <option key={k}>{k}</option>)}
            </select>
            <button className="primary" onClick={save} disabled={busy || !name.trim() || !kind || saved}>{saved ? 'Сохранено' : 'Сохранить в библиотеку'}</button>
          </div>
          <p className="muted">Объёмы по группам, млн м³. Проверка: {view.summary}</p>
          <div className="scroll">
            <table className="raw">
              <thead><tr><th>Группа</th><th>Скв.</th>{tm.months.map(m => <th key={m}>{m}</th>)}<th>Всего</th></tr></thead>
              <tbody>
                <tr><th>Рабочих дней</th><td />{tm.months.map(m => <td key={m} className="num">{tm.days[m]}</td>)}<td /></tr>
                {Object.entries(tm.volumes).map(([g, v]) => (
                  <tr key={g}><th>{g}</th><td className="num">{tm.wells[g] ?? ''}</td>
                    {tm.months.map(m => <td key={m} className="num">{fmt(v[m])}</td>)}
                    <td className="num">{fmt(tm.months.reduce((s, m) => s + (v[m] || 0), 0))}</td></tr>))}
                <tr><th>Сумма</th><td />{tm.months.map(m => {
                  const sum = Object.values(tm.volumes).reduce((s, v) => s + (v[m] || 0), 0)
                  const bad = m in tm.totals && Math.abs(sum - tm.totals[m]) > Math.max(0.01, Math.abs(tm.totals[m]) * 1e-4)
                  return <td key={m} className={'num' + (bad ? ' bad' : '')} title={bad ? 'В файле: ' + fmt(tm.totals[m]) : ''}>{fmt(sum)}</td>
                })}<td className="num">{fmt(Object.values(tm.volumes).reduce((s, v) => s + tm.months.reduce((a, m) => a + (v[m] || 0), 0), 0))}</td></tr>
              </tbody>
            </table>
          </div>
          {view.issues.length > 0 && <ul className="issues">{view.issues.map((i, k) => <li key={k} className={i.level}>{i.message}</li>)}</ul>}
        </section>
      )}
      {msg && <p className="note warn">{msg}</p>}
    </main>
  )
}
