import { useEffect, useState } from 'react'
import { getGdisTemplates, saveGdisMapping, type GdisLoc, type GdisRow, type GdisTemplate } from './api'

const locKey = (l: GdisLoc | null) => (l ? `${l.table}|${l.label}|${l.method}` : '')
const SOURCE: Record<string, string> = { 'авто': 'подсказка', 'вручную': 'выбрано вручную', 'отключено': 'отключено' }

// Мастер сопоставления шапок: по каждому шаблону отчёта таблица «поле базы → величина отчёта».
// Подсказка автоматическая; выбор за инженером и запоминается за шаблоном.
export default function GdisPanel({ folder, mapping, method, onClose }: { folder: string; mapping: string; method: string; onClose: () => void }) {
  const [templates, setTemplates] = useState<GdisTemplate[]>([])
  const [errors, setErrors] = useState<{ file: string; error: string }[]>([])
  const [pick, setPick] = useState<Record<string, Record<string, GdisLoc | null>>>({})
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')

  const load = async () => {
    setBusy(true); setError('')
    try {
      const r = await getGdisTemplates(folder, mapping, method)
      setTemplates(r.templates); setErrors(r.errors)
      setPick(Object.fromEntries(r.templates.map(t => [t.id, Object.fromEntries(t.rows.map(x => [x.key, x.current]))])))
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  useEffect(() => { load() }, [folder, mapping, method])

  const set = (t: GdisTemplate, row: GdisRow, value: string) => {
    const loc = value === '' ? null : row.options.find(o => locKey(o.loc) === value)?.loc ?? null
    setPick(p => ({ ...p, [t.id]: { ...p[t.id], [row.key]: loc } }))
  }
  const sampleOf = (row: GdisRow, loc: GdisLoc | null) => row.options.find(o => locKey(o.loc) === locKey(loc))?.sample ?? ''
  const save = async (t: GdisTemplate) => {
    setError(''); setSaved('')
    try {
      const r = await saveGdisMapping(t.id, t.program, pick[t.id])
      setSaved(`Шаблон ${t.id}: запомнено полей ${r.saved}. Запуск и проверка подставят этот выбор.`)
      await load()
    } catch (e) { setError((e as Error).message) }
  }

  return (
    <section className="card result" aria-live="polite">
      <div className="result-head">
        <strong>Сопоставление шапок</strong>
        <span className="muted">{busy ? 'Читаю отчёты…' : `Шаблонов отчёта: ${templates.length}`}</span>
        <span className="spacer" />
        <button type="button" className="quiet" onClick={onClose}>Закрыть</button>
      </div>
      <p className="muted out-dir">Для каждого шаблона отчёта показано, какая величина попадёт в поле базы. Это подсказка по названиям и единицам: выберите другую величину или отключите поле, итог за вами. Выбор запоминается за шаблоном.</p>
      {error && <p className="note warning">{error}</p>}
      {saved && <p className="note info">{saved}</p>}
      {errors.length > 0 && <p className="note warning">Не прочитано: {errors.map(e => `${e.file} (${e.error})`).join('; ')}</p>}
      {templates.map(t => (
        <details key={t.id} open={templates.length === 1 || t.files === Math.max(...templates.map(x => x.files))} className="card">
          <summary><strong>Шаблон {t.id}</strong> · {t.program || 'программа не указана'} · файлов: {t.files}{t.saved ? ' · есть сохранённое сопоставление' : ''}
            <span className="muted"> (например, {t.names.slice(0, 3).join(', ')})</span></summary>
          <table className="files qc">
            <thead><tr><th>Поле базы</th><th>Величина отчёта</th><th>Пример значений</th><th>Откуда</th></tr></thead>
            <tbody>{t.rows.map(row => {
              const cur = pick[t.id]?.[row.key] ?? null
              const changed = locKey(cur) !== locKey(row.current)
              return (
                <tr key={row.key}>
                  <td>{row.label}{row.required && <span className="muted"> *</span>}{row.hint && <div className="muted">{row.hint}</div>}</td>
                  <td>
                    <select value={locKey(cur)} aria-label={`Величина для поля ${row.label}`} onChange={e => set(t, row, e.target.value)}>
                      <option value="">— не использовать —</option>
                      {row.options.map(o => (
                        <option key={locKey(o.loc)} value={locKey(o.loc)}>
                          {o.label}{o.unit ? ` [${o.unit}]` : ''}{o.method ? ` (метод ${o.method})` : ''}{locKey(o.loc) === locKey(row.auto) ? ' — подсказка' : ''}
                        </option>
                      ))}
                    </select>
                    {!row.found && cur && <div className="note warning">Выбранной величины нет в этом отчёте.</div>}
                    {row.required && !cur && <div className="note warning">Обязательное поле без величины: строки будут с замечанием.</div>}
                  </td>
                  <td className="muted">{changed ? sampleOf(row, cur) : row.sample}</td>
                  <td><span className={'chip small ' + (row.source === 'авто' ? 'warn' : 'done')}>{changed ? 'изменено' : SOURCE[row.source] ?? row.source}</span></td>
                </tr>
              )
            })}</tbody>
          </table>
          <div className="actions"><button type="button" className="primary" onClick={() => save(t)}>Запомнить для шаблона</button></div>
        </details>
      ))}
      {!busy && templates.length === 0 && !error && <p className="note info">В папке нет читаемых отчётов ГДИ.</p>}
    </section>
  )
}
