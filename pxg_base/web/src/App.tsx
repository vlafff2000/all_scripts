import { useEffect, useMemo, useRef, useState } from 'react'
import { fileUrl, getJob, getModules, startJob, type Job, type ModuleInfo } from './api'

export default function App() {
  const [modules, setModules] = useState<ModuleInfo[]>([])
  const [current, setCurrent] = useState<string | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getModules().then(m => { setModules(m); setCurrent(m.find(x => x.web)?.id ?? m[0]?.id ?? null) })
      .catch(e => setError(String(e.message || e)))
  }, [])

  const groups = useMemo(() => {
    const g: Record<string, ModuleInfo[]> = {}
    for (const m of modules) (g[m.group] ||= []).push(m)
    return g
  }, [modules])
  const module = modules.find(m => m.id === current)

  return (
    <div className="app">
      <nav className="menu">
        <h1>База ПХГ</h1>
        {Object.entries(groups).map(([name, items]) => (
          <div key={name}>
            <h2>{name}</h2>
            {items.map(m => (
              <button key={m.id} className={m.id === current ? 'item active' : 'item'} onClick={() => setCurrent(m.id)}>
                {m.title}{!m.web && <span className="tag">консоль</span>}
              </button>
            ))}
          </div>
        ))}
      </nav>
      <main>
        {error && <p className="error">{error}</p>}
        {module && <ModulePage key={module.id} module={module} />}
      </main>
    </div>
  )
}

function ModulePage({ module }: { module: ModuleInfo }) {
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(module.params.map(p => [p.id, p.default])))
  const [outDir, setOutDir] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [log, setLog] = useState<string[]>([])
  const [error, setError] = useState('')
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (!job || job.status !== 'running') return
    const t = setInterval(async () => {
      try {
        const next = await getJob(job.id, log.length)
        setLog(l => [...l, ...next.log])
        setJob(next)
      } catch (e) { setError(String((e as Error).message)) }
    }, 800)
    return () => clearInterval(t)
  }, [job, log.length])

  useEffect(() => { logRef.current?.scrollTo(0, logRef.current.scrollHeight) }, [log])

  const run = async () => {
    setError(''); setLog([])
    try { setJob(await startJob(module.id, { ...values, out_dir: outDir })) }
    catch (e) { setError(String((e as Error).message)) }
  }

  return (
    <section>
      <h2>{module.title}</h2>
      <p className="muted">{module.description}</p>
      {!module.web ? (
        <p className="note">Для этого модуля пока нет веб-формы. Запуск из консоли: <code>python -m pxg_base {module.id}</code></p>
      ) : (
        <>
          {module.note && <p className="note">{module.note}</p>}
          <div className="form">
            {module.params.map(p => (
              <label key={p.id}>
                <span>{p.label}{p.required && ' *'}</span>
                {p.kind === 'choice' ? (
                  <select value={values[p.id]} onChange={e => setValues({ ...values, [p.id]: e.target.value })}>
                    {p.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : (
                  <input value={values[p.id]} placeholder={p.kind === 'folder' ? 'Путь к папке' : p.kind === 'file' ? 'Путь к файлу' : ''}
                    onChange={e => setValues({ ...values, [p.id]: e.target.value })} />
                )}
                {p.hint && <small>{p.hint}</small>}
              </label>
            ))}
            <label>
              <span>Папка результатов</span>
              <input value={outDir} placeholder="Пусто — новая папка pxg_runs/<дата и время>" onChange={e => setOutDir(e.target.value)} />
            </label>
            <button className="run" onClick={run} disabled={job?.status === 'running'}>
              {job?.status === 'running' ? 'Выполняется…' : 'Запустить'}
            </button>
          </div>
          {error && <p className="error">{error}</p>}
          {job && (
            <div className="result">
              <p>
                Статус: <b className={job.status}>{{ running: 'выполняется', done: 'готово', failed: 'завершено с ошибкой' }[job.status]}</b>
                {' · '}папка результатов: <code>{job.out_dir}</code>
              </p>
              <pre ref={logRef} className="log">{log.join('\n')}</pre>
              {job.files.length > 0 && (
                <>
                  <h3>Файлы результата</h3>
                  <ul>{job.files.map(f => <li key={f}><a href={fileUrl(job.id, f)}>{f}</a></li>)}</ul>
                </>
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}
