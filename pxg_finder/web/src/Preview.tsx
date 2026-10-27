import { useEffect, useState } from 'react'
import { baseName, fmtSize, getJson } from './api'
import type { Preview as PV } from './api'

export default function Preview({ path, isDir }: { path: string; isDir: boolean }) {
  const [pv, setPv] = useState<PV | null>(null)
  const [sheet, setSheet] = useState('')
  useEffect(() => { setSheet('') }, [path])
  useEffect(() => {
    if (!path) { setPv(null); return }
    let alive = true
    setPv(null)
    const t = window.setTimeout(() => {
      getJson<PV>('/api/finder/preview?path=' + encodeURIComponent(path) + (sheet ? '&sheet=' + encodeURIComponent(sheet) : ''))
        .then(r => { if (alive) setPv(r) }).catch(() => { if (alive) setPv({ kind: 'error', error: 'Нет связи с сервером' }) })
    }, 120) // не читаем файл, пока выделение прыгает по списку
    return () => { alive = false; window.clearTimeout(t) }
  }, [path, sheet])

  if (!path) return <div className="fx-pv empty">Выберите файл, чтобы увидеть его содержимое</div>
  const raw = '/api/finder/raw?path=' + encodeURIComponent(path)
  return (
    <div className="fx-pv">
      <div className="fx-pvh" title={path}><b>{baseName(path)}</b>{pv?.size != null && !isDir && <span className="muted"> · {fmtSize(pv.size)}</span>}</div>
      {!pv && <div className="muted pad">Загрузка…</div>}
      {pv?.kind === 'error' && <div className="bad pad">{pv.error}</div>}
      {pv?.kind === 'none' && <div className="muted pad">{pv.note}</div>}
      {pv?.kind === 'image' && <div className="fx-pvimg"><img src={raw} alt={baseName(path)} /></div>}
      {pv?.kind === 'pdf' && <iframe className="fx-pvpdf" src={raw} title="PDF" />}
      {pv?.kind === 'text' && <pre className="fx-pvtext">{pv.text}{pv.truncated ? '\n… (показано начало файла)' : ''}</pre>}
      {pv?.kind === 'folder' && <div className="pad"><div className="muted">Элементов: {pv.count}</div>{pv.names?.map(n => <div key={n} className="fx-pvn">{n}</div>)}{(pv.count || 0) > 80 && <div className="muted">…</div>}</div>}
      {pv?.kind === 'table' && (
        <div className="fx-pvtbl">
          {!!pv.sheets?.length && <div className="fx-sheets">{pv.sheets.map(s => <button key={s} className={s === pv.sheet ? 'on' : ''} onClick={() => setSheet(s)}>{s}</button>)}</div>}
          <div className="fx-scroll"><table><tbody>{pv.rows?.map((r, i) => <tr key={i}><th>{i + 1}</th>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table></div>
          {pv.more && <div className="muted pad">… показаны первые строки</div>}
        </div>
      )}
    </div>
  )
}
