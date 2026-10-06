import { useEffect, useMemo, useRef, useState } from 'react'
import { checkUrl, fileUrl, getJob, getJobs, openFolder, pickPath, runCheck, startJob, type Job, type ModuleInfo, type Param, type QcReport } from './api'
import { loadForm, saveForm } from './prefs'

const STATUS = { running: 'Выполняется', done: 'Готово', failed: 'Завершено с ошибкой' } as const

export const size = (n: number) => (n < 1024 ? n + ' Б' : n < 1048576 ? (n / 1024).toFixed(1) + ' КБ' : (n / 1048576).toFixed(1) + ' МБ')
const clock = (s: number) => (s < 60 ? Math.round(s) + ' с' : Math.floor(s / 60) + ' мин ' + Math.round(s % 60) + ' с')
const when = (t: number) => new Date(t * 1000).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

function PathField({ param, value, onChange, invalid }: { param: Param; value: string; onChange: (v: string) => void; invalid: boolean }) {
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const browse = async (as: 'folder' | 'file') => {
    setBusy(true); setProblem('')
    try {
      const many = param.kind === 'paths'
      const p = await pickPath(many ? as : (param.kind as 'folder' | 'file'), many ? '' : value)
      if (p) onChange(many ? (value.trim() ? value.replace(/\s*$/, '') + '\n' : '') + p : p)
    }
    catch (e) { setProblem((e as Error).message) }
    finally { setBusy(false) }
  }
  return (
    <div className={'field wide' + (invalid ? ' invalid' : '')}>
      <label className="field-label" htmlFor={'f-' + param.id}>{param.label}{param.required && <b className="req"> *</b>}</label>
      <div className="path-row">
        {param.kind === 'paths' ? (
          <textarea id={'f-' + param.id} value={value} spellCheck={false} rows={3} onChange={e => onChange(e.target.value)}
            placeholder={'По одному пути в строке'} />
        ) : (
          <input id={'f-' + param.id} value={value} spellCheck={false} onChange={e => onChange(e.target.value)}
            placeholder={param.kind === 'folder' ? 'Путь к папке' : 'Путь к файлу'} />
        )}
        {param.kind === 'paths' ? (
          <span className="pick-pair">
            <button type="button" className="quiet" onClick={() => browse('file')} disabled={busy}>Добавить файл…</button>
            <button type="button" className="quiet" onClick={() => browse('folder')} disabled={busy}>Добавить папку…</button>
          </span>
        ) : (
          <button type="button" className="quiet" onClick={() => browse(param.kind as 'folder' | 'file')} disabled={busy}>{busy ? 'Выбор…' : 'Обзор…'}</button>
        )}
      </div>
      {param.hint && <span className="hint">{param.hint}</span>}
      {problem && <span className="field-error">{problem}</span>}
    </div>
  )
}

const LEVEL_CLASS: Record<string, string> = { 'ошибка': 'failed', 'предупреждение': 'warn', 'заметка': 'idle' }

function QcPanel({ report }: { report: QcReport }) {
  const [level, setLevel] = useState('')
  const rows = report.issues.filter(i => !level || i.level === level)
  const where = (i: QcReport['issues'][number]) =>
    [i.file, i.sheet && 'лист ' + i.sheet, i.row && 'строка ' + i.row, i.well && 'скв. ' + i.well, i.date].filter(Boolean).join(' · ')
  return (
    <section className="card result" aria-live="polite">
      <div className="result-head">
        <strong>Проверка исходников</strong>
        <span className="muted">{report.summary}</span>
        <span className="spacer" />
        {(['', 'ошибка', 'предупреждение', 'заметка'] as const).map(l => (
          <button key={l} className={'quiet' + (level === l ? ' current' : '')} onClick={() => setLevel(l)}>
            {l ? `${l} (${report.counts[l] ?? 0})` : 'все'}
          </button>
        ))}
        <a className="quiet" href={checkUrl(report.id, 'xlsx')}>Excel</a>
      </div>
      {report.checked.length > 0 && <p className="muted out-dir">Просмотрено: {report.checked.join('; ')}</p>}
      {rows.length === 0 ? <p className="note info">{report.issues.length ? 'В этом уровне замечаний нет.' : 'Замечаний нет.'}</p> : (
        <table className="files qc">
          <thead><tr><th>Уровень</th><th>Что не так</th><th>Где</th><th>Значение</th></tr></thead>
          <tbody>{rows.map((i, k) => (
            <tr key={k}>
              <td><span className={'chip small ' + LEVEL_CLASS[i.level]}>{i.level}</span><div className="muted">{report.codes[i.code] ?? i.code}</div></td>
              <td>{i.message}{i.hint && <div className="muted">→ {i.hint}</div>}</td>
              <td className="muted">{where(i)}</td>
              <td>{i.value}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {report.hidden.length > 0 && <p className="muted">Однотипные замечания сверх лимита не показаны: {report.hidden.map(h => `${h.level} ${report.codes[h.code] ?? h.code} — ${h.count}`).join('; ')}.</p>}
    </section>
  )
}

export default function ModulePage({ module }: { module: ModuleInfo }) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const saved = loadForm(module.id)
    return Object.fromEntries(module.params.map(p => [p.id, saved[p.id] ?? p.default]))
  })
  const [outDir, setOutDir] = useState(() => loadForm(module.id).out_dir ?? '')
  const [job, setJob] = useState<Job | null>(null)
  const [log, setLog] = useState<string[]>([])
  const [history, setHistory] = useState<Job[]>([])
  const [error, setError] = useState('')
  const [qc, setQc] = useState<QcReport | null>(null)
  const [checking, setChecking] = useState(false)
  const [now, setNow] = useState(Date.now() / 1000)
  const [copied, setCopied] = useState('')
  const logRef = useRef<HTMLPreElement>(null)

  const reloadHistory = () => getJobs().then(js => setHistory(js.filter(j => j.module === module.id))).catch(() => undefined)
  useEffect(() => { reloadHistory() }, [module.id])

  const jobId = job?.id
  const running = job?.status === 'running'
  useEffect(() => {
    if (!running || !jobId) return
    let seen = 0
    const t = setInterval(async () => {
      try {
        const next = await getJob(jobId, seen)
        seen = next.log_len
        setLog(l => [...l, ...next.log])
        setJob(next)
        if (next.status !== 'running') reloadHistory()
      } catch (e) { setError((e as Error).message) }
    }, 700)
    const tick = setInterval(() => setNow(Date.now() / 1000), 500)
    return () => { clearInterval(t); clearInterval(tick) }
  }, [running, jobId])

  useEffect(() => { const el = logRef.current; if (el && running) el.scrollTop = el.scrollHeight }, [log, running])

  const visible = (p: Param) => { if (!p.when) return true; const [k, v] = p.when.split('='); return values[k] === v }
  const missing = useMemo(() => module.params.filter(p => visible(p) && p.required && !(values[p.id] || '').trim()).map(p => p.id), [module, values])
  const [touched, setTouched] = useState(false)

  const run = async () => {
    setTouched(true); setError('')
    if (missing.length) return
    saveForm(module.id, { ...values, out_dir: outDir })
    setLog([])
    try { setJob(await startJob(module.id, { ...values, out_dir: outDir })) }
    catch (e) { setError((e as Error).message) }
  }
  const check = async () => {
    setTouched(true); setError('')
    if (missing.length) return
    saveForm(module.id, { ...values, out_dir: outDir })
    setChecking(true); setQc(null)
    try { setQc(await runCheck(module.id, values)) }
    catch (e) { setError((e as Error).message) }
    finally { setChecking(false) }
  }
  const show = async (j: Job) => { const full = await getJob(j.id, 0); setLog(full.log); setJob(full); setError('') }
  const copy = (key: string, text: string) => {
    navigator.clipboard?.writeText(text).then(() => { setCopied(key); setTimeout(() => setCopied(''), 1500) }, () => undefined)
  }

  const elapsed = job ? (job.finished ?? now) - job.started : 0
  return (
    <>
      <header className="module-head">
        <div>
          <p className="crumb">{module.group}</p>
          <h1>{module.title}</h1>
          <p className="lede">{module.description}</p>
        </div>
      </header>

      {!module.web ? (
        <div className="card console-card">
          <h3>Этот модуль пока работает только из консоли</h3>
          <p className="muted">Скрипт пока без веб-формы: его параметры ещё спрашивают окна или консоль. Запуск сейчас (из папки репозитория):</p>
          <div className="cmd"><code>{module.command}</code>
            <button className="quiet" onClick={() => copy('cmd', module.command)}>{copied === 'cmd' ? 'Скопировано' : 'Копировать'}</button></div>
        </div>
      ) : (
        <form className="card param-card" onSubmit={e => { e.preventDefault(); run() }}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run() }}>
          {module.note && <p className="note info">{module.note}</p>}
          <div className="fields">
            {module.params.filter(visible).map(p => p.kind === 'folder' || p.kind === 'file' || p.kind === 'paths' ? (
              <PathField key={p.id} param={p} value={values[p.id]} invalid={touched && missing.includes(p.id)}
                onChange={v => setValues(o => ({ ...o, [p.id]: v }))} />
            ) : (
              <div key={p.id} className={'field' + (p.kind === 'choice' || p.kind === 'lines' ? ' wide' : '') + (touched && missing.includes(p.id) ? ' invalid' : '')}>
                <label className="field-label" htmlFor={'f-' + p.id}>{p.label}{p.required && <b className="req"> *</b>}</label>
                {p.kind === 'bool' ? (
                  <label className="check"><input id={'f-' + p.id} type="checkbox" checked={!!values[p.id]}
                    onChange={e => setValues(o => ({ ...o, [p.id]: e.target.checked ? '1' : '' }))} /><span>Да</span></label>
                ) : p.kind === 'lines' ? (
                  <textarea id={'f-' + p.id} rows={3} value={values[p.id]} onChange={e => setValues(o => ({ ...o, [p.id]: e.target.value }))} />
                ) : p.kind === 'choice' ? (
                  <select id={'f-' + p.id} value={values[p.id]} onChange={e => setValues(o => ({ ...o, [p.id]: e.target.value }))}>
                    {p.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : (
                  <input id={'f-' + p.id} value={values[p.id]} onChange={e => setValues(o => ({ ...o, [p.id]: e.target.value }))} />
                )}
                {p.hint && <span className="hint">{p.hint}</span>}
              </div>
            ))}
          </div>
          <details className="advanced">
            <summary>Дополнительно</summary>
            <PathField param={{ id: 'out_dir', label: 'Папка результатов', kind: 'folder', default: '', required: false,
              hint: 'Пусто — каждый запуск пишет в новую папку pxg_runs/<дата и время>', when: '', options: [] }}
              value={outDir} onChange={setOutDir} invalid={false} />
          </details>
          <div className="actions">
            <button className="primary" type="submit" disabled={running}>{running ? 'Выполняется…' : 'Запустить'}</button>
            {module.check && <button type="button" className="quiet" onClick={check} disabled={checking || running}>{checking ? 'Проверка…' : 'Проверить исходники'}</button>}
            <span className="muted keys">Ctrl+Enter — запустить</span>
            {touched && missing.length > 0 && <span className="field-error">Заполните обязательные поля.</span>}
          </div>
        </form>
      )}

      {error && <p className="note warning">{error}</p>}

      {qc && <QcPanel report={qc} />}

      {job && (
        <section className="card result" aria-live="polite">
          <div className="result-head">
            <span className={'chip ' + job.status}>{running && <i className="dot" />}{STATUS[job.status]}</span>
            <span className="muted">{clock(elapsed)}</span>
            <span className="spacer" />
            <button className="quiet" onClick={() => openFolder(job.id).catch(e => setError(e.message))}>Открыть папку</button>
            <button className="quiet" onClick={() => copy('dir', job.out_dir)}>{copied === 'dir' ? 'Скопировано' : 'Копировать путь'}</button>
          </div>
          <p className="muted out-dir">Папка результатов: <code>{job.out_dir}</code></p>
          <pre ref={logRef} className="log" tabIndex={0}>{log.length ? log.join('\n') : 'Ждём вывода модуля…'}</pre>
          {job.files.length > 0 && (
            <table className="files">
              <thead><tr><th>Файл результата</th><th className="number">Размер</th></tr></thead>
              <tbody>{job.files.map(f => (
                <tr key={f}><td><a href={fileUrl(job.id, f)}>{f}</a></td><td className="number">{size(job.sizes?.[f] ?? 0)}</td></tr>
              ))}</tbody>
            </table>
          )}
        </section>
      )}

      {history.length > 0 && (
        <section className="card history">
          <h3>Запуски в этом сеансе</h3>
          <ul>{history.map(j => (
            <li key={j.id}>
              <button className={'row' + (job?.id === j.id ? ' current' : '')} onClick={() => show(j)}>
                <span className={'chip small ' + j.status}>{STATUS[j.status]}</span>
                <span>{when(j.started)}</span>
                <span className="muted path">{j.out_dir}</span>
              </button>
            </li>
          ))}</ul>
        </section>
      )}
    </>
  )
}
