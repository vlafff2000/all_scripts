import { ATLAS_AGGS } from './model'
import type { ModelKeyword, ModelsView } from './api'

export interface ModelPickerProps {
  view: ModelsView | null
  keywords: ModelKeyword[]
  keyword: string
  agg: string
  /** Сообщение о том, как считана разность или что не так (пусто — не показываем). */
  note: string
  onKeyword: (keyword: string) => void
  onAgg: (agg: string) => void
  onSelect: (ids: string[]) => void
  onFolders: (folders: string[]) => void
  onAddFolder: () => void
}

/** Выбор моделей tNavigator для раскраски карты: папки из общего списка, отметки моделей, вектор и агрегат. */
export default function ModelPicker(p: ModelPickerProps) {
  const { view } = p
  if (!view) return <div className="hint">Список моделей загружается…</div>
  const toggle = (id: string, on: boolean) => {
    const next = on ? [...view.selected, id] : view.selected.filter(x => x !== id)
    p.onSelect(next)
  }
  return (
    <div className="model-picker">
      <div className="model-folders">
        {view.folders.length === 0 && <span className="hint">Папки не добавлены: укажите папку с результатами расчёта.</span>}
        {view.folders.map(f => (
          <div className="row" key={f} title={f}>
            <span className="model-folder">{f}</span>
            <button type="button" className="quiet" aria-label={'Убрать папку ' + f} onClick={() => p.onFolders(view.folders.filter(x => x !== f))}>×</button>
          </div>
        ))}
        <button type="button" className="quiet" onClick={p.onAddFolder}>Добавить папку…</button>
      </div>
      <div className="model-list" role="group" aria-label="Модели">
        {view.models.length === 0 && view.folders.length > 0 && <span className="hint">В папках нет моделей (нужны файлы SMSPEC и UNSMRY).</span>}
        {view.models.map(m => (
          <label className="check" key={m.id} title={m.folder + ' · ' + (m.missing.length ? 'нет файлов: ' + m.missing.join(', ') : 'все файлы есть')}>
            <input type="checkbox" checked={m.selected} disabled={!m.summary} onChange={e => toggle(m.id, e.target.checked)} />
            <span>{m.name}</span>
            {!m.summary && <span className="hint"> · нет сводки</span>}
          </label>
        ))}
      </div>
      <label className="row"><span>Вектор</span>
        <select value={p.keyword} onChange={e => p.onKeyword(e.target.value)} aria-label="Вектор модели" disabled={!p.keywords.length}>
          {!p.keywords.length && <option value={p.keyword}>{p.keyword || 'нет векторов'}</option>}
          {p.keywords.map(k => <option key={k.keyword} value={k.keyword}>{k.keyword} · {k.unit} · скважин: {k.wells}</option>)}
        </select></label>
      <label className="row"><span>За окно</span>
        <select value={p.agg} onChange={e => p.onAgg(e.target.value)} aria-label="Агрегация модели">
          {ATLAS_AGGS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
        </select></label>
      {p.note && <p className="hint">{p.note}</p>}
    </div>
  )
}
