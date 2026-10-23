import { useMemo, useState } from 'react'
import { ChartView } from '../../../pxg_core/web-ui/chart/ChartView'
import { mkAxis, mkChart, mkSeries } from '../../../pxg_core/web-ui/chart/chartBuild'
import { HmBody, HmResult, HmSeason, ModelEntry, histModel, histModelXlsx, pickFile } from './api'

const fmt = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? '—' : x.toLocaleString('ru-RU', { maximumFractionDigits: d }))
const bad = (s: string) => s === 'недобор' || s === 'недозакачка' || s === 'нет в модели'

/** История против модели по газу: итоги по сезонам с эталоном узла учёта и разбор по скважинам. Пометки — подсказка, решает инженер. */
export default function HistModel({ models }: { models: ModelEntry[] }) {
  const [modelId, setModelId] = useState('')
  const [res, setRes] = useState<HmResult | null>(null)
  const [rel, setRel] = useState('5')
  const [abs, setAbs] = useState('1')
  const [unitK, setUnitK] = useState('')
  const [only, setOnly] = useState(true)
  const [pick, setPick] = useState('')
  const [sched, setSched] = useState('')
  const [atlasProj, setAtlasProj] = useState('')
  const [hu, setHu] = useState('auto')               // единицы истории: auto, 1, 0.001, 1000 или свой множитель
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const model = modelId || models[0]?.id || ''

  const body = (extra: Partial<HmBody> = {}): HmBody => ({ model, settings: { rel_pct: Number(rel.replace(',', '.')) || 5, abs_k: Number(abs.replace(',', '.')) || 1 },
    unit_k: Number(unitK.replace(',', '.')) || null, schedule_path: sched, atlas_project: atlasProj, hist_unit: hu, ...extra })
  const run = async (extra: Partial<HmBody> = {}) => {
    setBusy(true); setMsg('')
    try { const r = await histModel(body(extra)); setRes(r); setRel(String(r.settings.rel_pct)); setAbs(String(r.settings.abs_k)); setSched(r.saved.schedule_path || ''); setAtlasProj(r.saved.atlas_project || ''); setHu(r.saved.hist_unit || 'auto') } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const excluded = res?.saved.excluded || []
  const toggle = (key: string, well: string, all: boolean) => {
    const k = all ? '*|' + well : key
    run({ excluded: excluded.includes(k) ? excluded.filter(x => x !== k) : [...excluded, k] })
  }
  // сезоны, правка границ: в проект уходит весь список, пока идёт ручной (кнопка «Подобрать заново» сбрасывает)
  const editSeason = (s: HmSeason, patch: Partial<{ start: string; end: string; kind: string }>) => {
    const list = (res?.seasons || []).map(x => ({ name: x.name, kind: x.kind, start: x.start, end: x.end }))
    run({ seasons: list.map(x => (x.name === s.name ? { ...x, ...patch } : x)) })
  }
  const seasons = (res?.seasons || []).filter(s => s.total)
  const sel = seasons.find(s => s.name === pick) || seasons.find(s => bad(s.total!.label)) || seasons[0]

  const bySeason = useMemo(() => {
    if (!seasons.length) return null
    const names = seasons.map(s => s.name)
    const pts = (f: (s: HmSeason) => number | null) => seasons.map(s => f(s) ?? 0)
    return mkChart('gdm-hm-seasons', 'Средний расход по сезонам: история и модель', mkAxis('Сезон', '', 'category', { categories: names }), mkAxis('Расход', 'тыс. м³/сут'),
      [mkSeries({ name: 'История', kind: 'bar', slot: 0, x: names, y: pts(s => s.total!.hist_avg) }),
        mkSeries({ name: 'Модель', kind: 'bar', slot: 1, x: names, y: pts(s => s.total!.model_avg) }),
        ...(seasons.some(s => s.total!.ref_avg !== null) ? [mkSeries({ name: 'Эталон (узел учёта)', kind: 'bar', slot: 2, x: names, y: pts(s => s.total!.ref_avg) })] : [])])
  }, [res]) // eslint-disable-line
  const byWell = useMemo(() => {
    if (!sel) return null
    const rows = sel.rows.filter(r => !r.excluded)
    const names = rows.map(r => r.well)
    return mkChart('gdm-hm-wells-' + sel.name, 'По скважинам: ' + sel.name, mkAxis('Скважина', '', 'category', { categories: names }), mkAxis('Средний расход', 'тыс. м³/сут'),
      [mkSeries({ name: 'История', kind: 'bar', slot: 0, x: names, y: rows.map(r => r.hist_avg) }), mkSeries({ name: 'Модель', kind: 'bar', slot: 1, x: names, y: rows.map(r => r.model_avg) })])
  }, [res, pick]) // eslint-disable-line

  if (!models.length) return <section className="card"><h2>История и модель по газу</h2><p className="muted">Отметьте модель в разделе «Результаты расчёта».</p></section>
  return (
    <section className="card">
      <h2>История и модель по газу</h2>
      <p className="muted small">Дебит отбора (WGPR) и приёмистость (WGIR) модели против истории из базы расходов и эталона с узла учёта, по сезонам и скважинам. Сезоны подобраны по остановкам
        между ними (≥ 5 суток без объёма) — их границы можно поправить. «Недобор» (отбор) и «недозакачка» (закачка) — подсказка: модель ниже истории больше допуска; причина показана в таблице.
        Строку можно исключить, тогда она не входит в итог сезона. Единицы: тыс. м³ и тыс. м³/сут.</p>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <select value={model} onChange={e => { setModelId(e.target.value); setRes(null) }}>{models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
        <span className="muted small">Допуск, %:</span><input style={{ width: 60 }} value={rel} onChange={e => setRel(e.target.value)} />
        <span className="muted small">и не меньше, тыс. м³/сут:</span><input style={{ width: 60 }} value={abs} onChange={e => setAbs(e.target.value)} />
        <span className="muted small" title="Только если единицы сводки не распознаны: множитель к м³/сут">Множитель единиц:</span><input style={{ width: 70 }} placeholder="авто" value={unitK} onChange={e => setUnitK(e.target.value)} />
        <button className="primary" disabled={busy || !model} onClick={() => run()}>Сопоставить</button>
        {res && <button disabled={busy} onClick={() => run({ seasons: [] })} title="Сбросить ручные границы сезонов">Подобрать сезоны заново</button>}
        {res && <button disabled={busy} onClick={() => histModelXlsx(body()).catch(e => setMsg((e as Error).message))}>Выгрузить в Excel</button>}
        {busy && <span className="muted small">считаю…</span>}
      </div>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <span className="muted small" title="Пусто — история и эталон берутся сами: из проекта Газового Атласа, а если его нет, из базы расходов проекта или файла schedule в папке модели">Файл schedule с историей (вручную):</span>
        <input style={{ width: 360 }} placeholder="пусто — подтянется сама" value={sched} onChange={e => setSched(e.target.value)} />
        <button disabled={busy} onClick={async () => { const r = await pickFile(sched); if (r.path) setSched(r.path) }}>Выбрать…</button>
      </div>
      {res && <p className="muted small">История: {res.history_source}</p>}
      {res && <div className="row" style={{ flexWrap: 'wrap' }}><span className="muted small" title="Шапка файла может не совпадать с содержимым (например, м³ вместо тыс. м³). Авто сравнивает порядок величины истории с эталоном узла учёта (без него — с моделью)">Единицы истории:</span>
        <select value={['auto', '1', '0.001', '1000'].includes(hu) ? hu : 'custom'} onChange={e => { const v = e.target.value === 'custom' ? '1' : e.target.value; setHu(v); run({ hist_unit: v }) }}>
          <option value="auto">определить по порядку величины</option><option value="1">как прочитано из источника (×1)</option>
          <option value="0.001">значения в 1000 раз больше: в источнике м³, а не тыс. м³ (÷1000)</option><option value="1000">значения в 1000 раз меньше, чем нужно (×1000)</option><option value="custom">свой множитель…</option></select>
        {!['auto', '1', '0.001', '1000'].includes(hu) && <input style={{ width: 80 }} value={hu} onChange={e => setHu(e.target.value)} onBlur={() => run()} />}
        <span className="small">Сейчас ×{res.hist_unit.factor}: {res.hist_unit.reason}</span></div>}
      {res && res.atlas.projects.length > 1 && <div className="row"><span className="muted small">Проект Атласа:</span>
        <select value={atlasProj} onChange={e => { setAtlasProj(e.target.value); run({ atlas_project: e.target.value }) }}><option value="">самый свежий</option>
          {res.atlas.projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>}
      {msg && <p className="note warn">{msg}</p>}
      {res?.notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
      {res && <>
        <div style={{ overflowX: 'auto' }}><table className="raw"><thead><tr><th>Сезон</th><th>Вид</th><th>С</th><th>По</th><th>Сравнено, сут</th><th>История, тыс. м³</th><th>Модель, тыс. м³</th><th>Эталон, тыс. м³</th>
          <th>Модель − эталон, тыс. м³</th><th>История − эталон, тыс. м³</th><th>Пометка</th><th>Причина</th></tr></thead>
          <tbody>{res.seasons.map(s => { const t = s.total; return <tr key={s.name} style={t && bad(t.label) ? { background: 'rgba(220,80,60,.12)' } : undefined}>
            <td><button className="link" onClick={() => setPick(s.name)}>{s.name}</button></td><td>{s.kind}</td>
            <td><input type="date" style={{ width: 140 }} value={s.start} disabled={busy} onChange={e => e.target.value && editSeason(s, { start: e.target.value })} /></td>
            <td><input type="date" style={{ width: 140 }} value={s.end} disabled={busy} onChange={e => e.target.value && editSeason(s, { end: e.target.value })} /></td>
            <td className="num">{s.compared?.days ?? '—'}</td>
            <td className="num">{fmt(t?.hist, 0)}</td><td className="num">{fmt(t?.model, 0)}</td><td className="num">{fmt(t?.ref, 0)}</td>
            <td className="num">{t && t.ref !== null ? fmt(t.model - t.ref, 0) : '—'}</td><td className="num">{fmt(t?.hist_vs_ref, 0)}</td>
            <td>{t?.label || '—'}</td><td className="small">{(t?.why || s.notes.join('; ')) || ''}</td></tr> })}</tbody></table></div>
        {bySeason && <ChartView chart={bySeason} excludeMode={false} onExclude={() => {}} />}
        {sel && <>
          <h3>Скважины: {sel.name}</h3>
          <div className="row"><select value={sel.name} onChange={e => setPick(e.target.value)}>{seasons.map(s => <option key={s.name}>{s.name}</option>)}</select>
            <label><input type="checkbox" checked={only} onChange={e => setOnly(e.target.checked)} /> только с пометкой</label>
            <span className="muted small">период сравнения {sel.compared?.start} — {sel.compared?.end}</span></div>
          {sel.notes.map((n, i) => <p key={i} className="note warn">{n}</p>)}
          {byWell && <ChartView chart={byWell} excludeMode={false} onExclude={() => {}} />}
          <div style={{ overflowX: 'auto' }}><table className="raw"><thead><tr><th>В итоге</th><th>Скважина</th><th>Группа</th><th>История, тыс. м³/сут</th><th>Модель, тыс. м³/сут</th><th>Разница, тыс. м³/сут</th>
            <th>История, тыс. м³</th><th>Модель, тыс. м³</th><th>Разница, %</th><th>Пометка</th><th>Причина</th></tr></thead>
            <tbody>{sel.rows.filter(r => !only || bad(r.label) || r.status === 'превышение').map(r => <tr key={r.key} style={r.excluded ? { opacity: 0.5 } : undefined}>
              <td><input type="checkbox" checked={!r.excluded} onChange={() => toggle(r.key, r.well, false)} aria-label="Учитывать в итоге" />
                <button title="Исключить скважину из всех сезонов" disabled={busy} onClick={() => toggle(r.key, r.well, true)}>{excluded.includes('*|' + r.well) ? '↺' : '∅'}</button></td>
              <td>{r.well}</td><td>{r.group || '—'}</td><td className="num">{fmt(r.hist_avg)}</td><td className="num">{fmt(r.model_avg)}</td><td className="num">{fmt(r.diff_avg)}</td>
              <td className="num">{fmt(r.hist, 0)}</td><td className="num">{fmt(r.model, 0)}</td><td className="num">{fmt(r.pct, 0)}</td><td>{r.label}</td><td className="small">{r.why}</td></tr>)}</tbody></table></div>
          {sel.groups.length > 0 && <div style={{ overflowX: 'auto' }}><table className="raw"><thead><tr><th>Группа</th><th>История, тыс. м³</th><th>Модель, тыс. м³</th><th>Разница, тыс. м³</th><th>%</th></tr></thead>
            <tbody>{sel.groups.map(g => <tr key={g.group}><td>{g.group}</td><td className="num">{fmt(g.hist, 0)}</td><td className="num">{fmt(g.model, 0)}</td><td className="num">{fmt(g.diff, 0)}</td><td className="num">{fmt(g.pct, 0)}</td></tr>)}</tbody></table></div>}
        </>}
      </>}
    </section>
  )
}
