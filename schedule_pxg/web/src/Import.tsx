import { useEffect, useState } from 'react'
import PageHead from './PageHead'
import ColumnWizard from './ColumnWizard'
import { AppState, SourcesCheck, SourcesView, buildSources, getSources, pickFile, pickFiles, setSources } from './api'

const base = (p: string) => p.split(/[\\/]/).pop() || p

function Row({ n, title, help, status, children }: { n: number; title: string; help: string; status?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="card step">
      <div className="step-head"><span className="step-n">{n}</span><h2>{title}</h2></div>
      {children}
      <p className="muted small src-help">{help}</p>
      {status && <p className="src-status">{status}</p>}
    </section>
  )
}

export default function Import({ st, setSt }: { st: AppState; setSt: (s: AppState) => void }) {
  const [sv, setSv] = useState<SourcesView | null>(null)
  const [qc, setQc] = useState<SourcesCheck | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [wizard, setWizard] = useState('')
  const [addPath, setAddPath] = useState('')
  const [gPath, setGPath] = useState('')
  const [dPath, setDPath] = useState('')

  const guard = async (f: () => Promise<void>) => {
    setBusy(true); setMsg('')
    try { await f() } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const apply = (v: SourcesView) => {
    setSv(v); setGPath(v.sources.groups?.path || ''); setDPath(v.sources.daily_total?.path || '')
  }
  useEffect(() => { getSources().then(apply).catch(e => setMsg(e.message)) }, [])

  const flows = sv?.sources.flows?.paths || []
  const gMode = sv?.sources.groups?.mode || 'file'
  const unit = sv?.sources.daily_total?.unit || 'м3/сут'
  const saveFlows = (paths: string[]) => guard(async () => {
    const f = sv?.sources.flows
    apply(await setSources({ flows: { paths, template: f?.template || '', kind_default: f?.kind_default || '' } })); setQc(null)
  })
  const addFlows = (ps: string[]) => {
    const clean = ps.map(s => s.trim().replace(/^"|"$/g, '')).filter(Boolean)
    if (clean.length) saveFlows(Array.from(new Set([...flows, ...clean])))
    setAddPath('')
  }
  const saveGroups = (mode: string, path: string) => guard(async () => { apply(await setSources({ groups: { mode, path: path.trim().replace(/^"|"$/g, '') } })); setQc(null) })
  const saveTotal = (path: string, u: string) => guard(async () => { apply(await setSources({ daily_total: { path: path.trim().replace(/^"|"$/g, ''), unit: u } })) })
  const check = () => guard(async () => { const r = await buildSources(); apply(r); setQc(r) })

  return (
    <main className="workspace">
      <PageHead title="Импорт" lede="Три источника, от которых считается всё остальное: база расходов, разбивка скважин на группы и эталонный суточный объём." />
      {msg && <p className="note warn">{msg}</p>}

      <Row n={1} title="База расходов по скважинам"
        help="Суточные расходы скважин по датам: из них считаются доли скважин в группе. Можно несколько файлов (например, по годам или по закачке и отбору)."
        status={flows.length ? <>Файлов: <b>{flows.length}</b>. Скважин в проекте: <b>{sv?.wells ?? 0}</b>.</> : 'Файл пока не выбран.'}>
        {flows.map(f => (
          <div key={f} className="chip"><span title={f}>{base(f)}</span><span className="muted small">{f}</span>
            <button className="x" title="Убрать файл" aria-label={'Убрать ' + base(f)} onClick={() => saveFlows(flows.filter(x => x !== f))}>×</button></div>
        ))}
        <div className="row">
          <input className="grow" value={addPath} placeholder="Нажмите «Добавить файлы…» или вставьте путь и нажмите Enter" onChange={e => setAddPath(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addFlows([addPath])} />
          <button onClick={() => guard(async () => addFlows(await pickFiles(flows[flows.length - 1] || '')))} disabled={busy}>Добавить файлы…</button>
          <button className="primary" onClick={check} disabled={busy || !flows.length}>Проверить</button>
          <button onClick={() => setWizard(flows[0] || '')} disabled={busy || !flows.length}>Настроить столбцы</button>
        </div>
      </Row>

      <Row n={2} title="Разбивка скважин на группы"
        help="Какая скважина в какой группе (ГСП, СП и т. д.). Названия групп берутся ровно такими, как в файле. Нужно два столбца: «Скважина» и «Группа»."
        status={sv && sv.sources.groups ? <>Групп: <b>{sv.groups}</b>. Скважин без группы: <b>{sv.withoutGroup}</b>.</> : 'Источник пока не задан.'}>
        <div className="segmented" role="radiogroup" aria-label="Откуда берём группы">
          <button type="button" role="radio" aria-checked={gMode === 'file'} onClick={() => saveGroups('file', gPath)}>Отдельный файл</button>
          <button type="button" role="radio" aria-checked={gMode === 'column'} onClick={() => saveGroups('column', '')}>Столбец в базе расходов</button>
        </div>
        {gMode === 'file' ? (
          <div className="row">
            <input className="grow" value={gPath} placeholder="Нажмите «Выбрать файл…» или вставьте путь" onChange={e => setGPath(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && saveGroups('file', gPath)} onBlur={() => gPath !== (sv?.sources.groups?.path || '') && saveGroups('file', gPath)} />
            <button onClick={() => guard(async () => { const r = await pickFile(gPath); if (r.path) await saveGroups('file', r.path) })} disabled={busy}>Выбрать файл…</button>
            <a className="btn" href="/api/sources/sample" download>Скачать образец формата</a>
            <button className="primary" onClick={check} disabled={busy || !gPath.trim()}>Проверить</button>
          </div>
        ) : (
          <div className="row">
            <span className="muted">Группа читается из столбца самой базы расходов. Столбец укажите в «Настроить столбцы» (поле «Группа скважины»).</span>
            <button className="primary" onClick={check} disabled={busy || !flows.length}>Проверить</button>
          </div>
        )}
      </Row>

      <Row n={3} title="Эталонный суточный объём газа по объекту"
        help="Суточный объём с узла коммерческого учёта: два столбца, дата и объём. Расходы скважин подгоняются так, чтобы за каждые сутки сложиться ровно в него."
        status={sv?.daily ? (sv.daily.error ? <span className="warn">{sv.daily.error}</span> : sv.daily.days ? <>Суток: <b>{sv.daily.days}</b>, с {sv.daily.from} по {sv.daily.to}.</> : 'В файле нет строк с датой и объёмом.') : 'Файл пока не выбран.'}>
        <div className="row">
          <input className="grow" value={dPath} placeholder="Нажмите «Выбрать файл…» или вставьте путь" onChange={e => setDPath(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && saveTotal(dPath, unit)} onBlur={() => dPath !== (sv?.sources.daily_total?.path || '') && saveTotal(dPath, unit)} />
          <button onClick={() => guard(async () => { const r = await pickFile(dPath); if (r.path) await saveTotal(r.path, unit) })} disabled={busy}>Выбрать файл…</button>
          <label>Единицы<select value={unit} onChange={e => saveTotal(dPath, e.target.value)}>{st.units.map(u => <option key={u}>{u}</option>)}</select></label>
        </div>
      </Row>

      <p className="muted src-help">Тех.карты (утверждённые объёмы по группам и месяцам) загружаются на своём экране: <a href="#/techmaps">Тех.карты</a>, загружено: <b>{sv?.techmaps ?? st.techmaps.length}</b>.</p>

      {qc && <section className="card">
        <h2>Результат проверки</h2>
        <p>{qc.summary}</p>
        {qc.issues.length > 0 ? <ul className="issues">{qc.issues.map((i, k) => <li key={k} className={i.level}>{i.message}{i.well ? ' (' + i.well + ')' : ''}</li>)}</ul> : <p className="muted">Замечаний нет.</p>}
      </section>}

      {wizard && <ColumnWizard st={st} setSt={setSt} initialPath={wizard} onClose={() => setWizard('')} />}
    </main>
  )
}
