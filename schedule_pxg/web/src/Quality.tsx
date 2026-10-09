import { useState } from 'react'
import PageHead from './PageHead'
import { QualityView, excludeRows, getQuality } from './api'

const SHOW = 300

export default function Quality() {
  const [jump, setJump] = useState(3)
  const [v, setV] = useState<QualityView | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [marked, setMarked] = useState<Set<string>>(new Set())
  const [fCheck, setFCheck] = useState('')
  const [fLevel, setFLevel] = useState('')
  const [fSet, setFSet] = useState('')

  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const scan = () => guard(async () => { setV(await getQuality(jump)); setMarked(new Set()) })
  const exclude = (b: Parameters<typeof excludeRows>[0], text: string) => guard(async () => {
    const r = await excludeRows({ jump, ...b })
    setV(await getQuality(jump)); setMarked(new Set())
    setMsg(text.replace('{n}', String(r.changed)))
  })
  const rows = v ? v.rows.filter(r => (!fCheck || r.check === fCheck) && (!fLevel || r.level === fLevel) && (!fSet || r.dataset === fSet)) : []
  const shown = rows.slice(0, SHOW)
  const checks = v ? Array.from(new Set(v.summary.map(s => s.check))) : []
  const toggle = (id: string) => setMarked(m => { const n = new Set(m); n.has(id) ? n.delete(id) : n.add(id); return n })
  const markShown = () => setMarked(new Set(shown.filter(r => !r.excluded).map(r => r.id)))
  const label = (d: string) => v?.datasets[d] || d

  return (
    <main className="workspace">
      <PageHead title="Проверка данных" lede="Ищем «ненормальные» строки в базе расходов и эталонном суточном объёме и даём исключить их из расчётов." />
      <section className="card">
        <div className="row">
          <label>Скачок расхода, раз
            <input type="number" min={1.5} max={20} step={0.5} value={jump} onChange={e => setJump(Number(e.target.value))} /></label>
          <button className="primary" onClick={scan} disabled={busy}>Проверить данные</button>
          {v && <span className="muted small">Исключено строк: <b>{v.excluded}</b></span>}
        </div>
        <p className="muted small">Источники берутся с экрана «Импорт». Это подсказки: скачок может быть настоящей остановкой, ноль — реальным простоем. Исключение не меняет файлы, а лишь убирает строку из расчётов (осреднение, история, эталон); вернуть её можно в любой момент.</p>
        {msg && <p className="note">{msg}</p>}
      </section>

      {v && v.total === 0 && <p className="note">Сомнительных строк не найдено.</p>}

      {v && v.total > 0 && <>
        <section className="card">
          <h2>Сводка <span className="muted small">находок {v.total}, из них ошибок {v.errors}</span></h2>
          <div className="scroll"><table className="raw"><thead><tr><th>Набор</th><th>Проверка</th><th>Уровень</th><th>Находок</th><th /></tr></thead>
            <tbody>{v.summary.map((s, i) => <tr key={i}>
              <td>{label(s.dataset)}</td><td>{s.check}</td><td>{s.level}</td><td>{s.count}</td>
              <td><button disabled={busy} onClick={() => exclude({ check: s.check, dataset: s.dataset, level: s.level }, 'Исключено строк: {n}')}>Исключить все</button></td></tr>)}</tbody></table></div>
          <div className="row"><button disabled={busy} onClick={() => exclude({ level: 'ошибка' }, 'Исключено строк с ошибками: {n}')}>Исключить все ошибки</button></div>
        </section>

        <section className="card">
          <h2>Строки <span className="muted small">показано {shown.length} из {rows.length}{v.shown < v.total ? ' (всего находок ' + v.total + ', показаны первые ' + v.shown + ')' : ''}</span></h2>
          <div className="row">
            <label>Набор<select value={fSet} onChange={e => setFSet(e.target.value)}><option value="">все</option>
              {Object.entries(v.datasets).map(([k, n]) => <option key={k} value={k}>{n}</option>)}</select></label>
            <label>Проверка<select value={fCheck} onChange={e => setFCheck(e.target.value)}><option value="">все</option>
              {checks.map(c => <option key={c}>{c}</option>)}</select></label>
            <label>Уровень<select value={fLevel} onChange={e => setFLevel(e.target.value)}><option value="">все</option><option>ошибка</option><option>внимание</option></select></label>
            <button onClick={markShown}>Отметить показанные</button>
            <button className="primary" disabled={busy || !marked.size} onClick={() => exclude({ ids: Array.from(marked) }, 'Исключено строк: {n}')}>Исключить отмеченные ({marked.size})</button>
          </div>
          <div className="scroll"><table className="raw"><thead><tr><th /><th>Набор</th><th>Скважина</th><th>Дата</th><th>Вид</th><th>Проверка</th><th>Уровень</th><th>Значение</th><th>Пояснение</th></tr></thead>
            <tbody>{shown.map(r => <tr key={r.id + r.check} className={r.excluded ? 'dim' : ''}>
              <td><input type="checkbox" checked={marked.has(r.id)} disabled={r.excluded} onChange={() => toggle(r.id)} aria-label="Отметить строку" /></td>
              <td>{label(r.dataset)}</td><td>{r.well || 'по объекту'}</td><td>{r.date}</td><td>{r.kind}</td><td>{r.check}</td>
              <td className={r.level === 'ошибка' ? 'bad' : ''}>{r.level}</td><td>{r.value}</td><td className="muted small">{r.excluded ? 'Исключено. ' : ''}{r.details}</td></tr>)}</tbody></table></div>
        </section>
      </>}

      {v && v.excludedRows.length > 0 && <section className="card">
        <h2>Исключено из расчётов <span className="muted small">{v.excludedRows.length}</span></h2>
        <div className="row"><button disabled={busy} onClick={() => guard(async () => { await excludeRows({ all_restore: true }); setV(await getQuality(jump)); setMsg('Все строки возвращены.') })}>Вернуть все</button></div>
        <div className="scroll" style={{ maxHeight: 240 }}><table className="raw"><thead><tr><th>Набор</th><th>Скважина</th><th>Дата</th><th>Вид</th><th /></tr></thead>
          <tbody>{v.excludedRows.slice(0, 500).map(r => <tr key={r.id}><td>{label(r.dataset)}</td><td>{r.well || 'по объекту'}</td><td>{r.date}</td><td>{r.kind}</td>
            <td><button disabled={busy} onClick={() => exclude({ ids: [r.id], on: false }, 'Строка возвращена.')}>Вернуть</button></td></tr>)}</tbody></table></div>
      </section>}
    </main>
  )
}
