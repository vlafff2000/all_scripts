// Общая сворачиваемая группа (заголовок со счётчиком + содержимое). Используется для списков, разбитых на группы
// (сессии распознавания и т.п.); свой вариант в модуле не делаем. Состояние «открыто» держит вызывающий код,
// чтобы оно не сбрасывалось при обновлении списка.
import type { ReactNode } from 'react'
import './collapsible.css'

export function CollapsibleGroup({ title, count, hint, open, onToggle, children }: {
  title: string; count?: number; hint?: string; open: boolean; onToggle: (open: boolean) => void; children: ReactNode
}) {
  return (
    <details className="cgroup" open={open} onToggle={e => { const o = (e.currentTarget as HTMLDetailsElement).open; if (o !== open) onToggle(o) }}>
      <summary className="cgroup-head">
        <span className="cgroup-title">{title}</span>
        {count !== undefined && <span className="cgroup-count">{count}</span>}
        {hint && <small className="cgroup-hint">{hint}</small>}
      </summary>
      <div className="cgroup-body">{children}</div>
    </details>
  )
}
