"""Выгрузка распознанного (OCR): документ Word и сводные таблицы xlsx. Только стандартная библиотека + openpyxl (как ``pxg_ocr.extract``).

* ``markdown_to_docx`` — прочитанный markdown (абзацы, заголовки, таблицы с объединением ячеек, картинки из папки результата) → ``.docx``.
* ``collect`` / ``write_tables_xlsx`` — таблицы из одного или многих файлов OCR → xlsx: один тип таблицы = один лист; одинаковые типы
  из разных файлов лежат на одном листе с идентификаторами «Скважина» и «Дата» (из шапки отчёта), «Файл» и «№ таблицы».

Тип таблицы определяет ``gis_report.table_kind`` (комплекс, термобарика, заполнение ствола, интервалы Кг, история ГВК); остальные таблицы
группируются по одинаковой шапке. Число в ячейке записывается числом, всё прочее — как прочитано: ошибки OCR программа не исправляет;
в реестре файлов для каждого файла написано, что в шапке не найдено (скважина, дата) — решает инженер.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from . import ocr_blocks as ob
from . import word_tables as wt

KIND_LABEL = {"complex": "Комплекс ГИС", "gvk_history": "История ГВК", "thermo": "Термобарика", "filling": "Заполнение ствола", "intervals": "Интервалы Кг"}
KIND_ORDER = list(KIND_LABEL.values())
ID_COLS = ["Скважина", "Дата", "Файл", "№ таблицы"]
_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


# ------------------------------------------------------------------------------------------------ сетка таблицы

def _bounds(tbl: wt.Table) -> List[float]:
    """Границы столбцов сетки: уникальные x0/x1 ячеек с допуском 1 % ширины таблицы."""
    xs = sorted({v for r in tbl.rows for c in r.cells for v in (c.x0, c.x1)})
    if not xs:
        return []
    tol = max(1.0, (xs[-1] - xs[0]) * 0.01)
    out = [xs[0]]
    for x in xs[1:]:
        if x - out[-1] > tol:
            out.append(x)
    return out


def _col(bounds: List[float], x: float, end: bool = False) -> int:
    best = min(range(len(bounds)), key=lambda i: abs(bounds[i] - x))
    return best


def _spans(tbl: wt.Table) -> Tuple[int, List[List[Tuple[int, int, wt.Cell]]]]:
    """(число столбцов сетки, по строкам: [(первый столбец, после последнего, ячейка)])."""
    b = _bounds(tbl)
    n = max(len(b) - 1, 1)
    rows = []
    for r in tbl.rows:
        rows.append([(min(_col(b, c.x0), n - 1), max(_col(b, c.x1), min(_col(b, c.x0), n - 1) + 1), c) for c in r.cells])
    return n, rows


def _header_rows(tbl: wt.Table) -> int:
    from .gis_report import header_rows
    nh = header_rows(tbl)
    return nh if nh < len(tbl.rows) else (1 if len(tbl.rows) > 1 else 0)


def flat_table(tbl: wt.Table) -> Tuple[List[str], List[List[str]]]:
    """Таблица → (подписи столбцов, строки текста). Шапка из нескольких строк склеивается «верх / низ»; пустые столбцы-тени объединённых ячеек убираются."""
    n, rows = _spans(tbl)
    nh = _header_rows(tbl)
    grid: List[List[str]] = []
    labels: List[List[str]] = [[] for _ in range(n)]
    for i, spans in enumerate(rows):
        line = [""] * n
        for a, b, c in spans:
            if i < nh:
                if c.text and not c.vcont:
                    for k in range(a, min(b, n)):
                        if c.text not in labels[k]:
                            labels[k].append(c.text)
            elif a < n and c.text and not c.vcont:
                line[a] = c.text
        if i >= nh and any(line):
            grid.append(line)
    heads = [" / ".join(p) for p in labels]
    keep = [k for k in range(n) if any(r[k] for r in grid) or (heads[k] and not (k > 0 and heads[k] == heads[k - 1] and not any(r[k] for r in grid)))]
    if nh == 0 or not any(heads[k] for k in keep):
        heads = ["Столбец %d" % (i + 1) for i in range(n)]
    out_h: List[str] = []
    for k in keep:
        h, base, i = heads[k] or "Столбец %d" % (k + 1), heads[k] or "Столбец %d" % (k + 1), 2
        while h in out_h:
            h = "%s (%d)" % (base, i)
            i += 1
        out_h.append(h)
    return out_h, [[r[k] for k in keep] for r in grid]


def _value(text: str) -> Any:
    s = text.strip()
    if _NUM.fullmatch(s) and not re.fullmatch(r"0\d+", s):
        v = float(s.replace(",", "."))
        return int(v) if v.is_integer() and "." not in s and "," not in s else v
    return text


def _signature(heads: List[str]) -> str:
    return re.sub(r"[^а-яёa-z]+", " ", " ".join(heads).lower()).strip()[:80]


# ------------------------------------------------------------------------------------------------ сбор таблиц

def sources(paths: List[str], prefer: str = ".json") -> List[str]:
    """Файлы OCR из файлов и папок: на документ один файл (по умолчанию content_list.json предпочтительнее markdown; ``prefer=".md"`` — наоборот)."""
    found: Dict[str, str] = {}
    for p in paths:
        names = [p] if os.path.isfile(p) else [os.path.join(r, f) for r, _d, fs in os.walk(p) for f in sorted(fs)] if os.path.isdir(p) else []
        for f in names:
            if not (os.path.isfile(p) or ob.is_ocr_file(f)):
                continue
            base = os.path.basename(f).lower()
            key = os.path.dirname(f) if base == "full.md" or "content_list" in base else ob.ocr_stem(f)
            if key not in found or (f.lower().endswith(prefer) and not found[key].lower().endswith(prefer)):
                found[key] = f
    return sorted(found.values())


def read_header(blocks: List[wt.Block], file: str) -> Tuple[str, Optional[dt.date], str]:
    """(скважина, дата, замечание) по шапке отчёта; не найдено — пусто и замечание."""
    from . import gis_report
    rep = gis_report.Report(file=os.path.basename(file), path=file)
    try:
        gis_report.read_header(rep, blocks)
    except Exception as e:  # noqa: BLE001 - файл не пропадает из сводки, причина пишется в реестр
        return "", None, "шапка не прочитана: %s" % e
    notes = []
    if not rep.well:
        notes.append("номер скважины не найден")
    if rep.date is None:
        notes.append("дата не найдена")
    elif rep.date_note:
        notes.append(rep.date_note)
    return rep.well, rep.date, "; ".join(notes)


def collect(paths: List[str]) -> Dict[str, Any]:
    """Таблицы из файлов OCR → {"sheets": {имя: (столбцы, строки)}, "files": [...], "types": [...]}. Первые столбцы — ID_COLS."""
    groups: Dict[str, Dict[str, Any]] = {}
    files: List[List[Any]] = []
    for f in sources(paths):
        try:
            blocks, _notes = ob.read_ocr(f)
        except Exception as e:  # noqa: BLE001
            files.append([os.path.basename(f), "", None, 0, "файл не прочитан: %s" % e])
            continue
        well, date, note = read_header(blocks, f)
        count = 0
        for b in blocks:
            if not isinstance(b, wt.Table):
                continue
            from .gis_report import table_kind
            heads, rows = flat_table(b)
            if not rows:
                continue
            kind = table_kind(b)[0]
            if kind:
                label = KIND_LABEL[kind]
            elif len(heads) == 2 and all(h.startswith("Столбец") for h in heads):
                label = "Реквизиты и шапка"
            else:
                label = "Прочее " + (_signature(heads)[:18] or "без шапки")
            g = groups.setdefault(label, {"sig": {}, "cols": [], "rows": [], "files": set(), "tables": 0})
            g["sig"].setdefault(_signature(heads), heads)
            for h in heads:
                if h not in g["cols"]:
                    g["cols"].append(h)
            for r in rows:
                g["rows"].append([well, date, os.path.basename(f), b.index + 1, dict(zip(heads, r))])
            g["files"].add(f)
            g["tables"] += 1
            count += 1
        files.append([os.path.basename(f), well, date, count, note])
    order = sorted(groups, key=lambda k: (KIND_ORDER.index(k) if k in KIND_ORDER else (len(KIND_ORDER) if not k.startswith("Прочее") else len(KIND_ORDER) + 1), -len(groups[k]["rows"]), k))
    sheets: Dict[str, Tuple[List[str], List[List[Any]]]] = {}
    types: List[List[Any]] = []
    for label in order:
        g = groups[label]
        name, k = label[:31], 2
        while name in sheets:
            name = "%s %d" % (label[:27], k)
            k += 1
        cols = ID_COLS + g["cols"]
        sheets[name] = (cols, [[w, d, fn, t] + [_value(m.get(c, "")) for c in g["cols"]] for w, d, fn, t, m in g["rows"]])
        types.append([name, len(g["sig"]), g["tables"], len(g["files"]), len(g["rows"])])
    return {"sheets": sheets, "files": files, "types": types}


def write_tables_xlsx(paths: List[str], out: str) -> Dict[str, Any]:
    """Сводная книга: «Оглавление» (листы), «Файлы» (реестр с замечаниями), затем по листу на тип таблицы. Возвращает счётчики."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    res = collect(paths)
    wb = Workbook()
    wb.remove(wb.active)
    book = {"Оглавление": (["Лист", "Вариантов шапки", "Таблиц", "Файлов", "Строк"], res["types"]),
            "Файлы": (["Файл", "Скважина", "Дата", "Таблиц", "Проверка"], res["files"])}
    book.update(res["sheets"])
    for name, (cols, rows) in book.items():
        ws = wb.create_sheet(name[:31])
        ws.append(cols)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append(r)
        for i, c in enumerate(cols, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(60, max(12, len(str(c)) + 2))
        ws.freeze_panes = "A2"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    wb.save(out)
    return {"files": len(res["files"]), "sheets": [{"name": t[0], "tables": t[2], "files": t[3], "rows": t[4]} for t in res["types"]]}


# ------------------------------------------------------------------------------------------------ Word

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_TABLE_RX = ob._TABLE_RX
_IMG = re.compile(r"!\[[^\]]*\]\(([^)\s]+)[^)]*\)")
CM = 360000          # EMU в сантиметре
TEXT_WIDTH_TW = 15136  # ширина текста A4 альбомной с полями 1,5 см, twips


def _p(text: str, style: str = "", bold: bool = False) -> str:
    ppr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ""
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    runs = []
    for i, line in enumerate(_xml_text(text).split("\n")):
        runs.append("%s<w:r>%s<w:t xml:space=\"preserve\">%s</w:t></w:r>" % ("<w:r><w:br/></w:r>" if i else "", rpr, line))
    return "<w:p>%s%s</w:p>" % (ppr, "".join(runs))


def _xml_text(text: str) -> str:
    return escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text))


def _table_xml(tbl: wt.Table) -> str:
    n, rows = _spans(tbl)
    nh = _header_rows(tbl)
    w = TEXT_WIDTH_TW // n
    out = ['<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblBorders>%s</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>' % (
        w * n, "".join('<w:%s w:val="single" w:sz="4" w:space="0" w:color="808080"/>' % s for s in ("top", "left", "bottom", "right", "insideH", "insideV"))),
        "<w:tblGrid>%s</w:tblGrid>" % (("<w:gridCol w:w=\"%d\"/>" % w) * n)]
    for i, spans in enumerate(rows):
        cells, col = [], 0
        nxt = {a for a, _b, c in rows[i + 1] if c.vcont} if i + 1 < len(rows) else set()
        for a, b, c in sorted(spans, key=lambda s: s[0]):
            if a < col:
                continue
            if a > col:
                cells.append('<w:tc><w:tcPr><w:gridSpan w:val="%d"/></w:tcPr><w:p/></w:tc>' % (a - col) if a - col > 1 else "<w:tc><w:p/></w:tc>")
            b = max(b, a + 1)
            pr = ('<w:gridSpan w:val="%d"/>' % (b - a) if b - a > 1 else "") + ("<w:vMerge/>" if c.vcont else '<w:vMerge w:val="restart"/>' if a in nxt else "")
            paras = "".join(_p(line, bold=i < nh) for line in (c.text.split("\n") if c.text else [""]))
            cells.append("<w:tc>%s%s</w:tc>" % ("<w:tcPr>%s</w:tcPr>" % pr if pr else "", paras))
            col = b
        if col < n:
            cells.append('<w:tc><w:tcPr><w:gridSpan w:val="%d"/></w:tcPr><w:p/></w:tc>' % (n - col) if n - col > 1 else "<w:tc><w:p/></w:tc>")
        out.append("<w:tr>%s%s</w:tr>" % ("<w:trPr><w:tblHeader/></w:trPr>" if i < nh else "", "".join(cells)))
    out.append("</w:tbl><w:p/>")
    return "".join(out)


def _image_xml(rid: str, n: int, width_px: int, height_px: int) -> str:
    cx = min(width_px / 96 * 2.54, 20.0) * CM            # не шире 20 см
    cy = cx * height_px / max(width_px, 1)
    return ('<w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"><wp:extent cx="%d" cy="%d"/>'
            '<wp:docPr id="%d" name="Рисунок %d"/><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="%d" name="img%d"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>') % (cx, cy, n, n, n, n, rid, cx, cy)


def _image_size(path: str) -> Optional[Tuple[int, int]]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001 - картинка не вставляется, остаётся подпись
        return None


STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="%s">'
          '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="20"/><w:lang w:val="ru-RU"/></w:rPr></w:rPrDefault>'
          '<w:pPrDefault><w:pPr><w:spacing w:after="60"/></w:pPr></w:pPrDefault></w:docDefaults>'
          '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
          '%s</w:styles>') % (W, "".join(
              '<w:style w:type="paragraph" w:styleId="Heading%d"><w:name w:val="heading %d"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="%d"/></w:pPr>'
              '<w:rPr><w:b/><w:sz w:val="%d"/></w:rPr></w:style>' % (i, i, i - 1, s) for i, s in ((1, 32), (2, 28), (3, 24))))


def markdown_to_docx(md: str, out: str, base_dir: str = "") -> Dict[str, int]:
    """Markdown результата OCR → .docx. Возвращает счётчики: абзацы, таблицы, картинки. Картинки ищутся относительно ``base_dir``."""
    body: List[str] = []
    media: List[Tuple[str, str]] = []             # (имя в архиве, путь на диске)
    stats = {"paragraphs": 0, "tables": 0, "images": 0}

    def text_chunk(chunk: str) -> None:
        pipe: List[str] = []

        def flush() -> None:
            if pipe:
                t = ob.table_from_pipes(pipe)
                if t is not None:
                    body.append(_table_xml(t))
                    stats["tables"] += 1
                pipe.clear()
        for ln in chunk.split("\n"):
            if ln.strip().startswith("|"):
                pipe.append(ln)
                continue
            flush()
            s = ln.strip()
            if not s:
                continue
            for m in _IMG.finditer(s):
                path = os.path.normpath(os.path.join(base_dir, m.group(1))) if base_dir and not m.group(1).startswith(("http:", "https:")) else ""
                size = _image_size(path) if path and os.path.isfile(path) else None
                if size:
                    name = "image%d%s" % (len(media) + 1, os.path.splitext(path)[1].lower() or ".png")
                    media.append((name, path))
                    body.append(_image_xml("rImg%d" % len(media), len(media), *size))
                    stats["images"] += 1
                else:
                    body.append(_p("[рисунок: %s]" % os.path.basename(m.group(1))))
            s = _IMG.sub("", s).strip()
            if not s:
                continue
            h = re.match(r"^(#{1,6})\s*(.*)$", s)
            text = ob.clean_text(h.group(2) if h else s)
            if text:
                body.append(_p(text, "Heading%d" % min(len(h.group(1)), 3) if h else ""))
                stats["paragraphs"] += 1
        flush()
    pos = 0
    for m in _TABLE_RX.finditer(md):
        text_chunk(md[pos:m.start()])
        t = ob.table_from_html(m.group(0))
        if t is not None:
            body.append(_table_xml(t))
            stats["tables"] += 1
        pos = m.end()
    text_chunk(md[pos:])
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>%s'
           '<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/><w:pgMar w:top="850" w:right="850" w:bottom="850" w:left="850" w:header="400" w:footer="400" w:gutter="0"/></w:sectPr></w:body></w:document>') % (W, "".join(body))
    rels = "".join('<Relationship Id="rImg%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/%s"/>' % (i + 1, n) for i, (n, _p_) in enumerate(media))
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
              '<Default Extension="png" ContentType="image/png"/><Default Extension="jpg" ContentType="image/jpeg"/><Default Extension="jpeg" ContentType="image/jpeg"/>'
              '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/_rels/document.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rIdS" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>%s</Relationships>' % rels)
        for name, path in media:
            z.write(path, "word/media/" + name)
    return stats
