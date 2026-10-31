import { Fragment, useState } from 'react'
import { ModelEntry, PressureCompare, PressureStat, comparePressure } from './api'
import { Tables } from '../../../pxg_core/web-ui/table/Tables'
import { tableOf } from '../../../pxg_core/web-ui/table/tableBuild'

const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const tail = (path: string) => path.split(/[\\/]/).filter(Boolean).slice(-2).join('/')

/** Строки «скважина; дата; давление» (разделитель «;» или Tab). Дата — ГГГГ-ММ-ДД или ДД.ММ.ГГГГ. */
export function parseMeasured(text: string) {
  return text.split('\n').map(s => s.trim()).filter(Boolean).map(line => {
    const [well = '', rawDate = '', p = ''] = line.split(/[;\t]/).map(x => x.trim())
    const dm = rawDate.match(/^(\d{2})\.(\d{2})\.(\d{4})$/)
    const date = dm ? dm[3] + '-' + dm[2] + '-' + dm[1] : rawDate
    return { well, date, p: Number(p.replace(',', '.')) }
  })
}

/** Сравнение моделей по давлению замерного фонда: замеры против давления каждой выбранной модели на ближайшем шаге. */
export default function ModelCompare({ models }: { models: ModelEntry[] }) {
  const [text, setText] = useState('')
  const [kw, setKw] = useState('WBHP')
  const [tol, setTol] = useState('15')
  const [excluded, setExcluded] = useState<string[]>([])
  const [res, setRes] = useState<PressureCompare | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  // подпись модели в таблицах: имя и хвост папки (одинаковые имена в разных папках различимы)
  const names = models.map(m => m.name + ' (' + tail(m.folder) + ')')

  const run = async (exc: string[]) => {
    setBusy(true); setMsg('')
    try {
      const r = await comparePressure({
        models: models.map((m, i) => ({ name: names[i], path: m.id })),
        measured: parseMeasured(text), keyword: kw, tolerance_days: Number(tol) || 0, excluded: exc,
      })
      setRes(r)
    } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const compare = () => { setExcluded([]); run([]) }
  const toggle = (key: string) => {
    const next = excluded.includes(key) ? excluded.filter(k => k !== key) : [...excluded, key]
    setExcluded(next); run(next)
  }

  return (
    <section className="card">
      <h3>Сравнение моделей: давление в скважинах замерного фонда</h3>
      <p className="muted small">Вставьте замеры строками «скважина; дата; давление» (кгс/см², абсолютное). Каждый замер сравнивается с давлением модели
        той же скважины на ближайшем шаге. Пропуски («нет данных» -999,25 и нули) не учитываются. Строку можно исключить вручную: подсказка программы — только подсказка.
        Разница = модель − замер; плюс — модель выше замера.</p>
      <div className="row" style={{ alignItems: 'flex-start' }}>
        <textarea style={{ width: 360, height: 120 }} placeholder={'Скв-1; 2023-01-15; 152.3\nСкв-2; 15.01.2023; 148.0'}
          value={text} onChange={e => setText(e.target.value)} aria-label="Замеры давления" />
        <div>
          <div className="row">
            <span className="muted small">Вид:</span>
            <select value={kw} onChange={e => setKw(e.target.value)}>
              <option value="WBHP">WBHP — забойное</option><option value="WBP">WBP — в ячейке</option>
              <option value="WBP4">WBP4 — вокруг, 4 ячейки</option><option value="WBP9">WBP9 — вокруг, 9 ячеек</option>
            </select>
          </div>
          <div className="row">
            <span className="muted small">Допуск по датам, сут:</span><input style={{ width: 70 }} value={tol} onChange={e => setTol(e.target.value)} />
          </div>
          <div className="row"><button className="primary" disabled={busy || !models.length || !text.trim()} onClick={compare}>Сравнить</button></div>
        </div>
      </div>
      {!models.length && <p className="muted small">Отметьте модели с результатами в таблице выше.</p>}
      {msg && <p className="note warn">{msg}</p>}
      {res && <>
        <p className="muted small">Исключено вручную: {res.excluded_count}. Допуск по датам: {res.tolerance_days} сут.</p>
        <div style={{ overflowX: 'auto' }}>
          <table className="raw"><thead><tr><th>Скважина</th><th>Дата</th><th>Замер, кгс/см²</th>
            {res.models.map(n => <th key={n} colSpan={2}>{n}: модель / Δ</th>)}
            <th>Подсказка</th><th>Исключить</th></tr></thead>
          <tbody>{res.rows.map(r => <tr key={r.key} className={r.excluded ? 'muted' : ''}>
            <td>{r.well}</td><td>{r.date}</td><td className="num">{fmt(r.fact, 1)}</td>
            {res.models.map(n => { const m = r.models[n]; return <Fragment key={n}>
              <td className="num">{fmt(m?.value, 1)}{m?.gap_days ? <span className="muted small"> ({m.gap_days} сут)</span> : null}</td>
              <td className="num">{fmt(m?.diff, 1)}</td></Fragment> })}
            <td className="small">{[r.hint, ...res.models.map(n => r.models[n]?.hint ? n + ': ' + r.models[n].hint : '')].filter(Boolean).join('; ')}</td>
            <td><input type="checkbox" checked={r.excluded} disabled={busy} onChange={() => toggle(r.key)} aria-label={'Исключить ' + r.well + ' ' + r.date} /></td>
          </tr>)}</tbody></table>
        </div>
        <h3 style={{ marginTop: 12 }}>Статистика по моделям (без исключённых строк)</h3>
        <Tables scope="sched-pressure-stat" tables={[tableOf('stat', 'Статистика по моделям',
          ['Модель', ['Точек', 'number', 0], ['Среднее Δ, кгс/см²', 'number', 2], ['Среднее |Δ|, кгс/см²', 'number', 2], ['Максимум |Δ|, кгс/см²', 'number', 2]],
          res.models.map(n => { const s: PressureStat = res.stats[n]; return [n, s.n, s.mean, s.mean_abs, s.max_abs] }))]} />
        {res.models.map(n => { const w = Object.entries(res.stats[n].wells); return w.length ? <p key={n} className="small">{n} по скважинам: {w.map(([k, v]) => k + ' — ' + v.n + ' т., среднее Δ ' + fmt(v.mean, 1)).join('; ')}</p> : null })}
      </>}
    </section>
  )
}
