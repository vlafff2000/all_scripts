import { useEffect, useState } from 'react'
import { ORIENT_LABELS, PAPER_LABELS, SHEET_DEFAULTS, type SheetFormat, type SheetOptions } from './exportSheet'
import { pref, usePref } from './pref'
import './exportsheet.css'

const sheetPref = pref<SheetOptions>('pxg.exportsheet', SHEET_DEFAULTS, raw => {
  const o = (raw && typeof raw === 'object' ? raw : {}) as Partial<SheetOptions>
  return {
    format: o.format === 'svg' || o.format === 'pdf' ? o.format : 'png',
    paper: PAPER_LABELS.some(([k]) => k === o.paper) ? o.paper! : 'A4',
    orientation: ORIENT_LABELS.some(([k]) => k === o.orientation) ? o.orientation! : 'auto',
    dpi: o.dpi === 150 || o.dpi === 600 ? o.dpi : 300,
  }
})

/** Окно «Скачать картинку»: формат, лист, ориентация, разрешение. Выбор помнится и общий для программ. */
export default function ExportSheetDialog({ title = 'Скачать картинку', busy, error, onGo, onClose }: { title?: string; busy: boolean; error: string; onGo: (o: SheetOptions) => void; onClose: () => void }) {
  const o = usePref(sheetPref)
  const [local, setLocal] = useState(o)
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }; document.addEventListener('keydown', k); return () => document.removeEventListener('keydown', k) }, [onClose])
  const set = (p: Partial<SheetOptions>) => { const n = { ...local, ...p }; setLocal(n); sheetPref.set(n) }
  const raster = local.format !== 'svg'
  return (
    <div className="xs-back" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="xs-win" role="dialog" aria-label={title}>
        <h3>{title}</h3>
        <label className="xs-row"><span>Формат</span>
          <select value={local.format} onChange={e => set({ format: e.target.value as SheetFormat })} aria-label="Формат файла">
            <option value="png">PNG (картинка)</option><option value="svg">SVG (вектор)</option><option value="pdf">PDF (страница)</option></select></label>
        <label className="xs-row"><span>Лист</span>
          <select value={local.paper} onChange={e => set({ paper: e.target.value as SheetOptions['paper'] })} aria-label="Размер листа">
            {PAPER_LABELS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
        {local.paper !== 'screen' && <label className="xs-row"><span>Ориентация</span>
          <select value={local.orientation} onChange={e => set({ orientation: e.target.value as SheetOptions['orientation'] })} aria-label="Ориентация листа">
            {ORIENT_LABELS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>}
        {raster && local.paper !== 'screen' && <label className="xs-row"><span>Разрешение</span>
          <select value={local.dpi} onChange={e => set({ dpi: Number(e.target.value) })} aria-label="Разрешение, dpi">
            {[150, 300, 600].map(d => <option key={d} value={d}>{d} dpi</option>)}</select></label>}
        <p className="muted small">Карта вписывается в лист с полями 8 мм по центру. PDF — страница выбранного размера с картинкой высокого разрешения; SVG остаётся векторным.</p>
        {error && <p className="field-error" role="alert">{error}</p>}
        <div className="xs-btns"><button type="button" className="quiet" onClick={onClose}>Отмена</button>
          <button type="button" className="primary" disabled={busy} onClick={() => onGo(local)}>{busy ? 'Готовлю файл…' : `Скачать ${local.format.toUpperCase()}`}</button></div>
      </div>
    </div>
  )
}
