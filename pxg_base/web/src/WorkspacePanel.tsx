import { useEffect, useState } from 'react'
import { openFilePicker } from '../../../pxg_core/web-ui/FilePicker'
import { getWorkspace, setWorkspaceProject, addReadyFiles, type WorkspaceState } from './api'

const STATUS_LABEL: Record<string, string> = { copied: 'скопирован', exists: 'уже есть, не заменён', missing: 'не найден', error: 'ошибка' }

/** Общая папка проекта на все приложения: выбор папки, статус подпапок и добавление готовых файлов с любого места диска. */
export function WorkspacePanel() {
  const [state, setState] = useState<WorkspaceState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    getWorkspace().then(setState).catch(e => setError(String(e.message || e)))
  }, [])

  const run = async (work: () => Promise<WorkspaceState>, done: string) => {
    setBusy(true); setError(''); setMessage('')
    try { setState(await work()); setMessage(done) }
    catch (e) { setError(String((e as Error).message || e)) }
    finally { setBusy(false) }
  }

  const chooseProject = async () => {
    let chosen: string | null = null
    try { chosen = await openFilePicker({ mode: 'folder', start: state?.project || undefined, title: 'Папка проекта' }) }
    catch (e) { setError(String((e as Error).message || e)); return }
    if (chosen) await run(() => setWorkspaceProject(chosen!), 'Папка проекта выбрана.')
  }

  const addFiles = async () => {
    let picked: string | null = null
    try { picked = await openFilePicker({ mode: 'files', start: state?.project || undefined, title: 'Файлы для «готовых»' }) }
    catch (e) { setError(String((e as Error).message || e)); return }
    if (!picked) return
    const paths = picked.split('\n').filter(Boolean)
    setBusy(true); setError(''); setMessage('')
    try {
      const reply = await addReadyFiles(paths)
      setState(reply)
      const copied = reply.results.filter(r => r.status === 'copied').length
      const notes = reply.results.filter(r => r.status !== 'copied').map(r => `${r.name}: ${STATUS_LABEL[r.status] ?? r.status}`)
      setMessage(`Скопировано: ${copied} из ${reply.results.length}.` + (notes.length ? ' ' + notes.join('; ') + '.' : ''))
    } catch (e) { setError(String((e as Error).message || e)) }
    finally { setBusy(false) }
  }

  return (
    <section className="group workspace-panel" aria-label="Папка проекта">
      <h2>Папка проекта</h2>
      <p className="lede">Одна папка на все приложения. Внутри две подпапки: «готовые» (файлы не пересобираются) и «выгрузки» (сюда пишет База ПХГ).</p>
      {state && <div className="folder-row">
        <span className="muted">{state.project || 'Проект не выбран'}</span>
        <button type="button" onClick={chooseProject} disabled={busy}>{state.project ? 'Сменить папку' : 'Выбрать папку проекта'}</button>
        {state.project && <button type="button" className="quiet" onClick={addFiles} disabled={busy}>Добавить файлы в «готовые»…</button>}
      </div>}
      {error && <div className="note warning">{error}</div>}
      {message && <div className="note">{message}</div>}
      {state && state.project && <ul className="folder-checklist" aria-label="Подпапки проекта">
        {state.folders.map(f => (
          <li key={f.slot}>
            <strong>{f.label}:</strong> {f.found ? `${f.files.length} файл(ов)` : 'папки нет'}
            {f.found && f.files.length > 0 && <div className="muted">{f.files.join(', ')}</div>}
          </li>
        ))}
      </ul>}
    </section>
  )
}
