import { useEffect, useMemo, useState } from 'react'
import { getDateIssues, saveDateFixes, type DateIssue } from './api'

const key = (i: DateIssue) => `${i.Файл}|${i.Лист}|${i.Ячейка}`
const yearOf = (v: string) => (v.match(/(\d{4})$/) || [, 'текст'])[1] as string

// Окно решений по подозрительным датам: группы «файл + год», лист-фрагмент, выбор для группы и для ячейки.
export default function DateIssues({ jobId, onRerun }: { jobId: string; onRerun: (fixesPath: string) => void }) {
  const [issues, setIssues] = useState<DateIssue[]>([])
  const [pick, setPick] = useState<Record<string, string>>({})   // ячейка → '', 'исключить', 'принять' или дата
  const [open, setOpen] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { getDateIssues(jobId).then(setIssues).catch(e => setError(e.message)) }, [jobId])

  const groups = useMemo(() => {
    const m = new Map<string, DateIssue[]>()
    issues.forEach(i => { const k = `${i.Файл}|${yearOf(i.Значение)}`; m.set(k, [...(m.get(k) || []), i]) })
    return Array.from(m.entries())
  }, [issues])

  if (!issues.length && !error) return null
  const setGroup = (items: DateIssue[], v: string) => setPick(p => ({ ...p, ...Object.fromEntries(items.map(i => [key(i), v])) }))
  const apply = async () => {
    setBusy(true); setError('')
    try {
      const fixes = issues.filter(i => pick[key(i)]).map(i => ({ file: i.Файл, sheet: i.Лист, cell: i.Ячейка, decision: pick[key(i)] }))
      const saved = await saveDateFixes(jobId, fixes)
      onRerun(saved.path)
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const changed = Object.values(pick).filter(Boolean).length

  return (
    <section className="card date-issues">
      <h3>Подозрительные даты: {issues.length}</h3>
      <p className="muted">В заголовках листов найдены даты, которые не подходят по году или месяцу. Эти столбцы в базу не попали либо исправлены
        автоматически (если соседние даты шли подряд). Выберите, что сделать, и пересоберите базу.</p>
      {groups.map(([k, items]) => {
        const [file, year] = k.split('|')
        return (
          <div key={k} className="date-group">
            <div className="date-head">
              <strong>{file}</strong> · значение «{year}» · ячеек: {items.length}
              <span className="spacer" />
              <select aria-label="Решение для всей группы" value="" onChange={e => e.target.value && setGroup(items, e.target.value === '-' ? '' : e.target.value)}>
                <option value="">Для всей группы…</option>
                <option value="-">как предложено</option>
                <option value="исключить">исключить все</option>
                <option value="принять">принять как есть</option>
              </select>
              <button className="quiet" onClick={() => setOpen(open === k ? '' : k)}>{open === k ? 'Скрыть' : 'Показать'}</button>
            </div>
            {open === k && items.map(i => (
              <div key={key(i)} className="date-item">
                <div>
                  <b>{i.Лист}, ячейка {i.Ячейка}</b>: «{i.Значение}», ожидалось {i.Ожидалось || '—'}. Сейчас: {i['Что сделано']}
                  {i['Что сделано'] === 'исключено' ? '' : ` → ${i.Предложение}`}
                </div>
                {i.fragment.length > 0 && (
                  <table className="fragment"><tbody>{i.fragment.map((r, y) => (
                    <tr key={y}>{r.map((c, x) => <td key={x}>{String(c)}</td>)}</tr>
                  ))}</tbody></table>
                )}
                <label>Решение{' '}
                  <select value={['', 'исключить', 'принять'].includes(pick[key(i)] || '') ? (pick[key(i)] || '') : 'дата'}
                    onChange={e => setPick(p => ({ ...p, [key(i)]: e.target.value === 'дата' ? '01.01.2000' : e.target.value }))}>
                    <option value="">как предложено</option>
                    <option value="исключить">исключить столбец</option>
                    <option value="принять">принять как есть</option>
                    <option value="дата">указать дату…</option>
                  </select>
                </label>{' '}
                {!['', 'исключить', 'принять'].includes(pick[key(i)] || '') && (
                  <input aria-label="Дата ДД.ММ.ГГГГ" placeholder="ДД.ММ.ГГГГ" value={pick[key(i)]}
                    onChange={e => setPick(p => ({ ...p, [key(i)]: e.target.value }))} />
                )}
              </div>
            ))}
          </div>
        )
      })}
      {error && <p className="error" role="alert">{error}</p>}
      <button onClick={apply} disabled={busy}>{busy ? 'Запускаем…' : changed ? `Применить решения (${changed}) и пересобрать` : 'Пересобрать как предложено'}</button>
    </section>
  )
}
