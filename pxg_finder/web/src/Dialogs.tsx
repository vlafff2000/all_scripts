import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { baseName, dirName, fmtSize, getJson, op, post, watchJob } from './api'
import type { IndexRoot, TrashItem } from './api'
import type { Meta } from './api'
import { COLOR_HEX, COLOR_NAME } from './types'

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [onClose])
  return (
    <div className="fx-back" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className={'fx-modal' + (wide ? ' wide' : '')} role="dialog" aria-label={title}>
        <div className="fx-mhead"><b>{title}</b><button className="fx-x" onClick={onClose}>✕</button></div>
        <div className="fx-mbody">{children}</div>
      </div>
    </div>
  )
}

export function Prompt({ title, label, value, ok, onDone }: { title: string; label: string; value: string; ok: string; onDone: (v: string | null) => void }) {
  const [v, setV] = useState(value)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { const el = ref.current; if (el) { el.focus(); const dot = value.lastIndexOf('.'); el.setSelectionRange(0, dot > 0 ? dot : value.length) } }, [value])
  return (
    <Modal title={title} onClose={() => onDone(null)}>
      <label className="fx-fld">{label}<input ref={ref} value={v} onChange={e => setV(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && v.trim()) onDone(v.trim()) }} /></label>
      <div className="fx-btns"><button onClick={() => onDone(null)}>Отмена</button><button className="primary" disabled={!v.trim()} onClick={() => onDone(v.trim())}>{ok}</button></div>
    </Modal>
  )
}

export function Confirm({ title, text, ok, danger, onDone, list }: { title: string; text: string; ok: string; danger?: boolean; onDone: (ok: boolean) => void; list?: string[] }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); onDone(true) } }
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [onDone])
  return (
    <Modal title={title} onClose={() => onDone(false)}>
      <p>{text}</p>
      {list && <ul className="fx-ul">{list.slice(0, 12).map(x => <li key={x}>{x}</li>)}{list.length > 12 && <li>…и ещё {list.length - 12}</li>}</ul>}
      <div className="fx-btns"><button onClick={() => onDone(false)}>Отмена</button><button className={danger ? 'danger' : 'primary'} onClick={() => onDone(true)}>{ok}</button></div>
    </Modal>
  )
}

export function Conflict({ names, onDone }: { names: string[]; onDone: (c: 'skip' | 'overwrite' | 'rename' | null) => void }) {
  return (
    <Modal title="Файлы уже есть в папке назначения" onClose={() => onDone(null)}>
      <ul className="fx-ul">{names.slice(0, 10).map(x => <li key={x}>{x}</li>)}{names.length > 10 && <li>…и ещё {names.length - 10}</li>}</ul>
      <div className="fx-btns">
        <button onClick={() => onDone(null)}>Отмена</button>
        <button onClick={() => onDone('skip')}>Пропустить</button>
        <button onClick={() => onDone('rename')}>Оставить оба (новое имя)</button>
        <button className="danger" onClick={() => onDone('overwrite')}>Заменить…</button>
      </div>
    </Modal>
  )
}

export function MetaDialog({ path, meta, colors, onDone }: { path: string; meta: Meta; colors: string[]; onDone: (m: Meta | null) => void }) {
  const [color, setColor] = useState(meta.color || '')
  const [tags, setTags] = useState((meta.tags || []).join(', '))
  const [note, setNote] = useState(meta.note || '')
  return (
    <Modal title={'Метки: ' + baseName(path)} onClose={() => onDone(null)}>
      <div className="fx-colors">
        <button className={'fx-sw none' + (!color ? ' on' : '')} title="Без цвета" onClick={() => setColor('')}>∅</button>
        {colors.map(c => <button key={c} className={'fx-sw' + (color === c ? ' on' : '')} style={{ background: COLOR_HEX[c] }} title={COLOR_NAME[c]} onClick={() => setColor(c)} />)}
      </div>
      <label className="fx-fld">Теги через запятую<input value={tags} onChange={e => setTags(e.target.value)} placeholder="отчёт, 2026, на проверку" /></label>
      <label className="fx-fld">Заметка<input value={note} onChange={e => setNote(e.target.value)} /></label>
      <div className="fx-btns"><button onClick={() => onDone(null)}>Отмена</button>
        <button className="primary" onClick={() => onDone({ color, tags: tags.split(',').map(t => t.trim()).filter(Boolean), note })}>Сохранить</button></div>
    </Modal>
  )
}

export function TrashDialog({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [items, setItems] = useState<TrashItem[] | null>(null)
  const [err, setErr] = useState('')
  const [ask, setAsk] = useState(false)
  const load = () => getJson<{ items: TrashItem[] }>('/api/finder/trash').then(r => setItems(r.items))
  useEffect(() => { void load() }, [])
  const restore = async (id: string) => { const r = await op({ op: 'restore', id }); if (r.error) setErr(r.error); else onChanged(); void load() }
  return (
    <Modal title="Корзина программы" onClose={onClose} wide>
      <p className="muted">Сюда попадают удалённые в программе файлы. Из корзины их можно вернуть на прежнее место.</p>
      {err && <p className="bad">{err}</p>}
      <div className="fx-tbl">
        {items?.map(i => (
          <div key={i.id} className="fx-trow"><span className="fx-ico">{i.dir ? '📁' : '▫️'}</span><span className="grow" title={i.orig}>{i.name}<small>{dirName(i.orig)}</small></span><span className="muted">{i.when}</span><button onClick={() => restore(i.id)}>Вернуть</button></div>
        ))}
        {items && !items.length && <p className="muted">Корзина пуста.</p>}
      </div>
      <div className="fx-btns"><button className="danger" disabled={!items?.length} onClick={() => setAsk(true)}>Очистить корзину…</button><button onClick={onClose}>Закрыть</button></div>
      {ask && <Confirm title="Очистить корзину" text={`Навсегда удалить файлов: ${items?.length}? Вернуть их будет нельзя.`} ok="Удалить навсегда" danger
        onDone={async ok => { setAsk(false); if (ok) { await op({ op: 'empty_trash', confirm: true }); void load() } }} />}
    </Modal>
  )
}

export function IndexDialog({ onClose, current, onChanged }: { onClose: () => void; current: string; onChanged: (roots: IndexRoot[]) => void }) {
  const [roots, setRoots] = useState<IndexRoot[]>([])
  const [path, setPath] = useState(current)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const load = () => getJson<{ roots: IndexRoot[] }>('/api/finder/index').then(r => { setRoots(r.roots); onChanged(r.roots) })
  useEffect(() => { void load() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const run = async (action: string, p: string) => {
    setErr(''); setBusy(p)
    const r = await post<{ job?: string; error?: string }>('/api/finder/index', { action, path: p })
    if (r.error) { setErr(r.error); setBusy(''); return }
    if (r.job) await watchJob(r.job, s => setBusy(`${p} — проиндексировано ${(s.info.indexed || s.info.scanned || 0).toLocaleString('ru')}`), 500)
    setBusy(''); void load()
  }
  return (
    <Modal title="Индекс — мгновенный поиск по выбранным папкам" onClose={onClose} wide>
      <p className="muted">Индекс хранит только имена файлов и папок. Построение по сетевому диску может занять минуты, но идёт в фоне, а поиск по готовому индексу занимает доли секунды. Обновляйте индекс, когда нужен свежий список.</p>
      {err && <p className="bad">{err}</p>}
      <div className="fx-tbl">
        {roots.map(r => (
          <div key={r.root} className="fx-trow"><span className="grow" title={r.root}>{r.network ? '🌐 ' : ''}{r.root}<small>{r.count ? `${r.count.toLocaleString('ru')} эл., построен ${r.built}, ${r.secs} с` : 'ещё не построен'}</small></span>
            <button disabled={!!busy} onClick={() => run('rebuild', r.root)}>Обновить</button>
            <button disabled={!!busy} onClick={() => run('remove', r.root).then(() => void load())}>Убрать</button></div>
        ))}
        {!roots.length && <p className="muted">Папок в индексе нет.</p>}
      </div>
      {busy && <p>Идёт индексация: {busy}</p>}
      <label className="fx-fld">Добавить папку в индекс<input value={path} onChange={e => setPath(e.target.value)} placeholder="D:\PHG  или  \\сервер\папка" /></label>
      <div className="fx-btns"><button className="primary" disabled={!path.trim() || !!busy} onClick={() => run('add', path.trim())}>Добавить и построить</button><button onClick={onClose}>Закрыть</button></div>
    </Modal>
  )
}

export function DupsDialog({ folder, onClose, onShow }: { folder: string; onClose: () => void; onShow: (path: string) => void }) {
  const [groups, setGroups] = useState<{ size: number; paths: string[]; full: boolean }[]>([])
  const [state, setState] = useState<{ running: boolean; stage: string; text: string }>({ running: false, stage: '', text: '' })
  const [minSize, setMinSize] = useState('1mb')
  const [full, setFull] = useState(false)
  const job = useRef('')
  const start = async () => {
    setGroups([])
    const r = await op({ op: 'duplicates', path: folder, minSize: parseMin(minSize), full })
    if (r.error) { setState({ running: false, stage: '', text: r.error }); return }
    job.current = r.job
    setState({ running: true, stage: 'обход папок', text: '' })
    await watchJob(r.job, s => {
      if (s.items.length) setGroups(g => g.concat(s.items))
      setState({ running: !s.done, stage: s.info.stage || '', text: s.error || (s.done ? '' : `просмотрено ${(s.info.scanned || 0).toLocaleString('ru')}${s.info.candidates ? `, проверено ${s.info.checked || 0} из ${s.info.candidates}` : ''}`) })
    }, 500)
  }
  useEffect(() => () => { if (job.current) void post('/api/finder/job/cancel', { id: job.current }) }, [])
  const wasted = groups.reduce((a, g) => a + g.size * (g.paths.length - 1), 0)
  return (
    <Modal title={'Дубликаты в ' + folder} onClose={onClose} wide>
      <div className="fx-row-form">
        <label>Файлы от <input value={minSize} style={{ width: 70 }} onChange={e => setMinSize(e.target.value)} /></label>
        <label><input type="checkbox" checked={full} onChange={e => setFull(e.target.checked)} /> сравнивать файл целиком (точнее, но медленно на сети)</label>
        <button className="primary" disabled={state.running} onClick={start}>Искать</button>
        {state.running && <button onClick={() => void post('/api/finder/job/cancel', { id: job.current })}>Стоп</button>}
      </div>
      {state.running || state.text ? <p className="muted">{state.stage}{state.text ? ': ' + state.text : ''}</p> : null}
      {groups.length > 0 && <p>Групп: {groups.length}, лишнего места: {fmtSize(wasted)}{groups.some(g => !g.full) ? ' (совпали размер, начало и конец файла)' : ''}</p>}
      <div className="fx-tbl tall">
        {groups.map((g, i) => (
          <div key={i} className="fx-dgrp"><b>{fmtSize(g.size)}</b>{g.paths.map(p => <div key={p} className="fx-trow"><span className="grow" title={p}>{p}</span><button onClick={() => onShow(p)}>Показать</button></div>)}</div>
        ))}
      </div>
      <p className="muted">Удалить лишнее можно из окна поиска: «Показать», затем «Удалить в корзину».</p>
    </Modal>
  )
}
const parseMin = (s: string) => {
  const m = /^([\d.,]+)\s*(кб|kb|k|мб|mb|m|гб|gb|g|б|b)?$/i.exec(s.trim())
  if (!m) return 1 << 20
  const u: Record<string, number> = { '': 1, б: 1, b: 1, k: 1024, кб: 1024, kb: 1024, m: 1 << 20, мб: 1 << 20, mb: 1 << 20, g: 1 << 30, гб: 1 << 30, gb: 1 << 30 }
  return Math.floor(parseFloat(m[1].replace(',', '.')) * (u[(m[2] || '').toLowerCase()] || 1))
}

export function Help({ onClose }: { onClose: () => void }) {
  const keys: [string, string][] = [
    ['Ctrl+K', 'палитра команд (всё из меню и переход по папкам)'], ['Ctrl+F', 'поиск'], ['Ctrl+L', 'ввести путь'], ['Ctrl+T / Ctrl+W', 'новая / закрыть вкладку'],
    ['Ctrl+Tab', 'следующая вкладка'], ['Tab', 'переключить панель'], ['F3 / Пробел', 'предпросмотр'], ['F2', 'переименовать'], ['F5 / F6', 'копировать / переместить в другую панель'],
    ['F7', 'новая папка'], ['Delete', 'в корзину программы'], ['Enter', 'открыть'], ['Backspace', 'вверх'], ['Alt+← / Alt+→', 'назад / вперёд'],
    ['Ctrl+Shift+C', 'копировать путь'], ['Ctrl+B', 'в избранное'], ['Ctrl+клик, Shift+клик, рамка мышью', 'выбор нескольких'], ['Перетаскивание', 'в другую панель или папку (Ctrl — копировать)'],
    ['Ctrl+D', 'две панели'], ['Ctrl+H', 'скрытые файлы'],
  ]
  return (
    <Modal title="Горячие клавиши и поиск" onClose={onClose} wide>
      <div className="fx-keys">{keys.map(([k, d]) => <div key={k}><kbd>{k}</kbd><span>{d}</span></div>)}</div>
      <h4>Запрос в строке поиска</h4>
      <ul className="fx-ul">
        <li><code>отчёт гсп</code> — оба слова в имени (в любом порядке)</li>
        <li><code>*.xlsx</code>, <code>отчёт_??.docx</code> — маски; <code>"точная фраза"</code> — в кавычках</li>
        <li><code>отчёт !черновик</code> — исключить слово</li>
        <li><code>ext:xlsx,csv</code> — расширения; <code>size:&gt;10mb</code> — размер; <code>date:&gt;2026-01-01</code> — дата изменения</li>
        <li>Галочка «Регулярное выражение» — шаблон целиком, например <code>^ГСП-\d+.*\.xlsx$</code></li>
      </ul>
    </Modal>
  )
}

export function IntegrationDialog({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { void getJson<{ status: string }>('/api/finder/integration').then(r => setStatus(r.status)) }, [])
  const run = async (action: string) => {
    setBusy(true); setMsg('')
    const r = await post<{ text?: string; status?: string; error?: string }>('/api/finder/integration', { action })
    setBusy(false)
    setMsg(r.error ? 'Ошибка: ' + r.error : r.text || '')
    if (r.status) setStatus(r.status)
  }
  return (
    <Modal title="Поисковик как проводник по умолчанию" onClose={onClose} wide>
      <p>Папки в других программах и ярлыки можно настроить прямо здесь, без терминала.</p>
      <p className="muted">Состояние: Поисковик для папок {status || '…'}</p>
      <div className="fx-btns" style={{ justifyContent: 'flex-start' }}>
        <button className="primary" disabled={busy} onClick={() => run('folders_on')}>Открывать папки в Поисковике</button>
        <button disabled={busy} onClick={() => run('folders_off')}>Вернуть прежний проводник</button>
        <button disabled={busy} onClick={() => run('shortcuts')}>Создать ярлыки на рабочем столе</button>
      </div>
      {msg && <p className={msg.startsWith('Ошибка') ? 'bad' : ''}>{msg}</p>}
      <p className="muted">Windows: добавляется пункт «Открыть в Поисковике» в меню правой кнопки на папке. РЕД ОС: Поисковик назначается программой для папок, прежняя запоминается.</p>
      <div className="fx-btns"><button onClick={onClose}>Закрыть</button></div>
    </Modal>
  )
}
