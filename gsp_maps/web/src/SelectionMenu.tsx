// Что сделать с выделенными на карте скважинами (рамка Shift+мышь, Ctrl/Shift+щелчок): выгрузить номера, оставить только их
// фильтром вкладки или сохранить пресет. Пресеты общие у всех программ (pxg_core/web-ui/wellPresets.ts), файл — через общий проводник.
// Решение за инженером: список можно менять до и после; фильтр снимается в «Фильтре скважин».
import { useState } from 'react'
import { presetSource } from '../../../pxg_core/web-ui/wellPresets'
import { saveFileWithPicker } from '../../../pxg_core/web-ui/desktopDownload'

export function SelectionMenu({ wells, onFilter }: { wells: number[]; onFilter?: (wells: string[]) => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [msg, setMsg] = useState('')
  const sorted = [...wells].sort((a, b) => a - b).map(String)
  const say = (t: string) => setMsg(t)
  const copy = async () => {
    try { await navigator.clipboard.writeText(sorted.join(', ')); say(`Скопировано номеров: ${sorted.length}`) }
    catch { say('Не удалось скопировать: разрешите доступ к буферу обмена.') }
  }
  const toFile = async () => {
    try {
      const path = await saveFileWithPicker(new Blob([sorted.join('\n') + '\n'], { type: 'text/plain;charset=utf-8' }), 'Скважины_выбранные.txt')
      say(path ? `Сохранено: ${path}` : '')
    } catch (e) { say(String((e as Error).message || e)) }
  }
  const preset = async () => {
    try { await presetSource().save(name.trim(), sorted); say(`Пресет «${name.trim()}» сохранён (${sorted.length} скв.), он виден во всех вкладках и программах.`); setName('') }
    catch (e) { say(String((e as Error).message || e)) }
  }
  return (
    <span className="sel-menu">
      <button type="button" className="quiet" aria-expanded={open} onClick={() => { setOpen(o => !o); setMsg('') }}
        title="Выгрузить номера, сделать фильтр или пресет по выделенным скважинам">Номера ▾</button>
      {open && (
        <div className="popover sel-menu-panel" role="dialog" aria-label="Выделенные скважины">
          <p className="muted small">{sorted.length} скв.: {sorted.slice(0, 12).join(', ')}{sorted.length > 12 ? '…' : ''}</p>
          <div className="well-filter-actions">
            <button type="button" onClick={copy}>Копировать номера</button>
            <button type="button" onClick={toFile}>В файл…</button>
            {onFilter && <button type="button" onClick={() => { onFilter(sorted); setOpen(false) }} title="Фильтр действует на этой вкладке; снимается в «Фильтре скважин»">Оставить только их</button>}
          </div>
          <div className="well-filter-actions">
            <input type="text" value={name} placeholder="Название пресета" aria-label="Название пресета" onChange={e => setName(e.target.value)} />
            <button type="button" className="primary" onClick={preset} disabled={!name.trim()}>Сохранить пресет</button>
          </div>
          {msg && <p className="small" role="status">{msg}</p>}
        </div>
      )}
    </span>
  )
}
