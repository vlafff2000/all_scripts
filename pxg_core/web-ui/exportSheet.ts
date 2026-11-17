// Выгрузка рисунка (SVG-элемента) на лист: PNG, SVG, PDF; «как на экране», А5/А4/А3, альбомная или книжная.
// Общее для всех программ: свою копию в модуле не делаем. PDF — страница нужного размера с картинкой высокого разрешения
// (кириллица и шрифты сохраняются как нарисованы; без сторонних пакетов, чтобы переносная сборка не зависела от npm-пакетов PDF).

export type SheetFormat = 'png' | 'svg' | 'pdf'
export type SheetPaper = 'screen' | 'A5' | 'A4' | 'A3'
export type SheetOrientation = 'auto' | 'landscape' | 'portrait'
export interface SheetOptions { format: SheetFormat; paper: SheetPaper; orientation: SheetOrientation; dpi: number }

export const SHEET_DEFAULTS: SheetOptions = { format: 'png', paper: 'A4', orientation: 'auto', dpi: 300 }
export const PAPER_LABELS: [SheetPaper, string][] = [['screen', 'Как на экране'], ['A5', 'A5'], ['A4', 'A4'], ['A3', 'A3']]
export const ORIENT_LABELS: [SheetOrientation, string][] = [['auto', 'Как у карты'], ['landscape', 'Альбомная'], ['portrait', 'Книжная']]
/** Короткие (ширина) и длинные (высота) стороны листа, мм. */
const PAPER_MM: Record<Exclude<SheetPaper, 'screen'>, [number, number]> = { A5: [148, 210], A4: [210, 297], A3: [297, 420] }
const MARGIN_MM = 8
const PX_PER_MM = 96 / 25.4
const MAX_SIDE = 12000

export interface SheetGeometry {
  /** Размер листа в мм (для «как на экране» — размер рисунка при 96 dpi). */
  mmW: number; mmH: number
  /** Размер листа в пикселях рисования (1 пикс = 1/96 дюйма). */
  pxW: number; pxH: number
  /** Положение и размер рисунка внутри листа, пикс. */
  x: number; y: number; w: number; h: number
}

/** Раскладка рисунка (w × h пикселей экрана) на листе: вписывается в поля по центру с сохранением пропорций. */
export function sheetGeometry(w: number, h: number, o: Pick<SheetOptions, 'paper' | 'orientation'>): SheetGeometry {
  if (o.paper === 'screen') return { mmW: w / PX_PER_MM, mmH: h / PX_PER_MM, pxW: w, pxH: h, x: 0, y: 0, w, h }
  const [a, b] = PAPER_MM[o.paper]
  const land = o.orientation === 'auto' ? w >= h : o.orientation === 'landscape'
  const mmW = land ? b : a, mmH = land ? a : b
  const pxW = mmW * PX_PER_MM, pxH = mmH * PX_PER_MM, m = MARGIN_MM * PX_PER_MM
  const s = Math.min((pxW - 2 * m) / w, (pxH - 2 * m) / h)
  return { mmW, mmH, pxW, pxH, x: (pxW - w * s) / 2, y: (pxH - h * s) / 2, w: w * s, h: h * s }
}

/** Лист как SVG: белый фон и рисунок, вложенный с нужным положением; `px` — размер растра по длинной стороне (0 — размер в мм). */
export function sheetSvg(src: SVGSVGElement, w: number, h: number, o: Pick<SheetOptions, 'paper' | 'orientation'>, target: 'mm' | { w: number; h: number }): { svg: string; geo: SheetGeometry } {
  const geo = sheetGeometry(w, h, o)
  const inner = src.cloneNode(true) as SVGSVGElement
  inner.setAttribute('x', String(geo.x)); inner.setAttribute('y', String(geo.y))
  inner.setAttribute('width', String(geo.w)); inner.setAttribute('height', String(geo.h))
  inner.setAttribute('viewBox', `0 0 ${w} ${h}`)
  const size = target === 'mm' ? `width="${geo.mmW.toFixed(2)}mm" height="${geo.mmH.toFixed(2)}mm"` : `width="${target.w}" height="${target.h}"`
  const body = new XMLSerializer().serializeToString(inner)
  const svg = `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" ${size} viewBox="0 0 ${geo.pxW.toFixed(2)} ${geo.pxH.toFixed(2)}"><rect width="100%" height="100%" fill="#ffffff"/>${body}</svg>`
  return { svg, geo }
}

async function rasterize(svg: string, cw: number, ch: number): Promise<HTMLCanvasElement> {
  const img = new Image()
  await new Promise<void>((ok, fail) => { img.onload = () => ok(); img.onerror = () => fail(new Error('Не удалось собрать картинку')); img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg) })
  const cv = document.createElement('canvas'); cv.width = cw; cv.height = ch
  const ctx = cv.getContext('2d')!
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cw, ch); ctx.drawImage(img, 0, 0, cw, ch)
  return cv
}

const toBlob = (cv: HTMLCanvasElement, type: string, q?: number) => new Promise<Blob>((ok, fail) => cv.toBlob(b => (b ? ok(b) : fail(new Error('Пустая картинка'))), type, q))

/** Размер растра в пикселях: «как на экране» — вдвое плотнее экрана (как прежний PNG), на листе — по dpi, не больше MAX_SIDE по стороне. */
export function rasterSize(geo: SheetGeometry, paper: SheetPaper, dpi: number): { w: number; h: number } {
  const k = paper === 'screen' ? 2 : dpi / 96
  const f = Math.min(1, MAX_SIDE / Math.max(geo.pxW * k, geo.pxH * k))
  return { w: Math.max(1, Math.round(geo.pxW * k * f)), h: Math.max(1, Math.round(geo.pxH * k * f)) }
}

/** Минимальный PDF: одна страница размера листа, на всю страницу — JPEG (без сторонних библиотек). */
export function pdfFromJpeg(jpeg: Uint8Array, imgW: number, imgH: number, mmW: number, mmH: number): Blob {
  const enc = new TextEncoder(), pt = (mm: number) => (mm * 72 / 25.4).toFixed(2)
  const W = pt(mmW), H = pt(mmH)
  const chunks: Uint8Array[] = [], offs: number[] = []
  let len = 0
  const put = (u: Uint8Array | string) => { const b = typeof u === 'string' ? enc.encode(u) : u; chunks.push(b); len += b.length }
  const obj = (n: number, body: string | (() => void)) => { offs[n] = len; put(`${n} 0 obj\n`); if (typeof body === 'string') put(body); else body(); put('\nendobj\n') }
  put('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')
  obj(1, '<< /Type /Catalog /Pages 2 0 R >>')
  obj(2, '<< /Type /Pages /Kids [3 0 R] /Count 1 >>')
  obj(3, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${W} ${H}] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>`)
  const content = `q ${W} 0 0 ${H} 0 0 cm /Im0 Do Q`
  obj(4, `<< /Length ${content.length} >>\nstream\n${content}\nendstream`)
  obj(5, () => { put(`<< /Type /XObject /Subtype /Image /Width ${imgW} /Height ${imgH} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`); put(jpeg); put('\nendstream') })
  const xref = len
  put(`xref\n0 6\n0000000000 65535 f \n` + [1, 2, 3, 4, 5].map(n => String(offs[n]).padStart(10, '0') + ' 00000 n \n').join(''))
  put(`trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)
  return new Blob(chunks as BlobPart[], { type: 'application/pdf' })
}

/** Файл выгрузки рисунка на лист. `src` — SVG на экране (уже без служебных элементов), `w`, `h` — его размер в пикселях. */
export async function renderSheet(src: SVGSVGElement, w: number, h: number, o: SheetOptions): Promise<Blob> {
  if (o.format === 'svg') return new Blob([sheetSvg(src, w, h, o, 'mm').svg], { type: 'image/svg+xml' })
  const geo = sheetGeometry(w, h, o), r = rasterSize(geo, o.paper, o.dpi)
  const cv = await rasterize(sheetSvg(src, w, h, o, r).svg, r.w, r.h)
  if (o.format === 'png') return toBlob(cv, 'image/png')
  const jpg = new Uint8Array(await (await toBlob(cv, 'image/jpeg', 0.95)).arrayBuffer())
  return pdfFromJpeg(jpg, r.w, r.h, geo.mmW, geo.mmH)
}

/** Часть имени файла: «A4_альбомная», «как_на_экране». */
export function sheetNamePart(o: SheetOptions, w: number, h: number): string {
  if (o.paper === 'screen') return 'как_на_экране'
  const land = o.orientation === 'auto' ? w >= h : o.orientation === 'landscape'
  return `${o.paper}_${land ? 'альбомная' : 'книжная'}`
}
