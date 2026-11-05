// Мини-показ markdown результата MinerU: заголовки, абзацы, картинки и HTML-таблицы (без внешних библиотек).
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** Оставляет в HTML-таблице только безопасные теги и атрибуты colspan/rowspan. */
export function cleanTable(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const ok = new Set(['TABLE', 'THEAD', 'TBODY', 'TR', 'TD', 'TH', 'CAPTION', 'BR'])
  doc.body.querySelectorAll('*').forEach((el) => {
    if (!ok.has(el.tagName)) { el.replaceWith(doc.createTextNode(el.textContent || '')); return }
    Array.from(el.attributes).forEach((a) => { if (!['colspan', 'rowspan'].includes(a.name)) el.removeAttribute(a.name) })
  })
  return doc.body.innerHTML
}

export function renderMarkdown(md: string, fileUrl: (rel: string) => string): string {
  const out: string[] = []
  const para: string[] = []
  const flush = () => { if (para.length) { out.push('<p>' + para.join('<br>') + '</p>'); para.length = 0 } }
  const inline = (s: string) => esc(s).replace(/!\[[^\]]*\]\(([^)]+)\)/g, (_m, u) => `<img src="${fileUrl(String(u).replace(/&amp;/g, '&'))}" alt="">`)
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
  const lines = md.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i]
    if (/^\s*<table/i.test(ln)) {
      flush()
      let buf = ln
      while (!/<\/table>/i.test(buf) && i + 1 < lines.length) buf += '\n' + lines[++i]
      out.push(cleanTable(buf))
      continue
    }
    if (/^\s*\|.*\|\s*$/.test(ln)) {  // таблица markdown: строки с | и разделитель |---|
      flush()
      const rows: string[][] = []
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        const cells = lines[i].trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells)
        i++
      }
      i--
      out.push('<table>' + rows.map((r, k) => '<tr>' + r.map((c) => `<${k ? 'td' : 'th'}>${inline(c)}</${k ? 'td' : 'th'}>`).join('') + '</tr>').join('') + '</table>')
      continue
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(ln)
    if (h) { flush(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); continue }
    if (/^\s*!\[/.test(ln)) { flush(); out.push('<p>' + inline(ln.trim()) + '</p>'); continue }
    if (!ln.trim()) { flush(); continue }
    para.push(inline(ln))
  }
  flush()
  return out.join('\n')
}
