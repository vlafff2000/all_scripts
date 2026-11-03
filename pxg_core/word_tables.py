"""Структура документа Word: абзацы и таблицы с настоящими границами ячеек (.docx и старый .doc), без Word и LibreOffice.

`word_doc` отдаёт только плоский текст: пустые ячейки и объединения в нём теряются. Здесь у каждой ячейки есть текст, границы по
горизонтали (x0, x1, в твипах), и признак «продолжение вертикального объединения», поэтому ячейку шапки (например,
«РИГИС от 10.2026г») можно сопоставить со значениями под ней, а ячейку на всю ширину таблицы (название пачки) — узнать по ширине.

.doc: таблицы берутся из свойств абзацев (PAPX: «в таблице», «конец строки») и описания строки (sprmTDefTable); если разбор не
удался, пробуется LibreOffice (`word_doc._via_office` для текста там не годится, поэтому конвертация в .docx через `office_convert`).
"""
from __future__ import annotations

import bisect
import os
import struct
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Union

from . import word_doc

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class Cell:
    text: str
    x0: float
    x1: float
    vcont: bool = False        # продолжение вертикального объединения (текст пуст)

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class TRow:
    cells: List[Cell]

    @property
    def width(self) -> float:
        return (self.cells[-1].x1 - self.cells[0].x0) if self.cells else 0.0

    def texts(self) -> List[str]:
        return [c.text for c in self.cells]


@dataclass
class Table:
    rows: List[TRow]
    index: int = 0             # номер таблицы в документе (с 0)
    row_pages: List[int] = field(default_factory=list)   # PDF: страница каждой строки (для источника значения)

    @property
    def x0(self) -> float:
        return min((c.x0 for r in self.rows for c in r.cells), default=0.0)

    @property
    def x1(self) -> float:
        return max((c.x1 for r in self.rows for c in r.cells), default=0.0)

    def is_full_width(self, row: TRow, tol: float = 0.9) -> bool:
        """Ячейка на всю ширину таблицы (объединённая строка-заголовок)."""
        return len(row.cells) == 1 or (self.x1 > self.x0 and row.width >= tol * (self.x1 - self.x0) and len([c for c in row.cells if c.text.strip()]) == 1
                                       and len(row.cells) <= 2 and row.cells[0].text.strip() != "")


@dataclass
class Para:
    text: str


Block = Union[Para, Table]


# ------------------------------------------------------------------------------------------------ .docx

def _tidy(text: str) -> str:
    """Пробелы внутри строк схлопываются, пустые строки убираются."""
    return "\n".join(" ".join(x.split()) for x in text.split("\n") if x.strip())


def _docx_cell_text(tc) -> str:
    paras = []
    for p in tc.iter(W + "p"):
        buf = []
        for el in p.iter():
            if el.tag == W + "t":
                buf.append(el.text or "")
            elif el.tag == W + "tab":
                buf.append(" ")
            elif el.tag in (W + "br", W + "cr"):
                buf.append("\n")
        paras.append("".join(buf).replace("\xa0", " "))
    return _tidy("\n".join(paras))


def _docx_table(tbl, index: int) -> Table:
    grid = [int(g.get(W + "w", "0") or 0) for g in tbl.findall(W + "tblGrid/" + W + "gridCol")]
    xs = [0.0]
    for g in grid:
        xs.append(xs[-1] + g)
    rows: List[TRow] = []
    for tr in tbl.findall(W + "tr"):
        pos = 0
        cells: List[Cell] = []
        pr = tr.find(W + "trPr")
        if pr is not None:
            gb = pr.find(W + "gridBefore")
            if gb is not None:
                pos = int(gb.get(W + "val", "0") or 0)
        for tc in tr.findall(W + "tc"):
            tcpr = tc.find(W + "tcPr")
            span = 1
            vm = None
            if tcpr is not None:
                gs = tcpr.find(W + "gridSpan")
                if gs is not None:
                    span = max(int(gs.get(W + "val", "1") or 1), 1)
                v = tcpr.find(W + "vMerge")
                if v is not None:
                    vm = v.get(W + "val", "continue")
            a = xs[min(pos, len(xs) - 1)]
            b = xs[min(pos + span, len(xs) - 1)]
            cont = vm == "continue"
            cells.append(Cell("" if cont else _docx_cell_text(tc), a, b, cont))
            pos += span
        rows.append(TRow(cells))
    return Table(rows, index)


def read_docx_blocks(path: str) -> List[Block]:
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    out: List[Block] = []
    n = 0
    for el in (body if body is not None else []):
        if el.tag == W + "p":
            text = "".join((x.text or "") if x.tag == W + "t" else (" " if x.tag == W + "tab" else "") for x in el.iter()).replace("\xa0", " ").strip()
            if text:
                out.append(Para(text))
        elif el.tag == W + "tbl":
            out.append(_docx_table(el, n))
            n += 1
    return out


# ------------------------------------------------------------------------------------------------ .doc

def _sprm_size(data: bytes, i: int) -> int:
    sprm = struct.unpack_from("<H", data, i)[0]
    if sprm == 0xD608:                     # sprmTDefTable: длина uint16 (включает сам байт-счётчик)
        return 2 + 2 + struct.unpack_from("<H", data, i + 2)[0] - 1 + 1 - 1
    spra = sprm >> 13
    if spra in (0, 1):
        return 3
    if spra in (2, 4, 5):
        return 4
    if spra == 3:
        return 6
    if spra == 7:
        return 5
    return 3 + data[i + 2]                 # 6: длина в первом байте


def _grpprl(data: bytes):
    i = 0
    while i + 2 <= len(data):
        try:
            size = _sprm_size(data, i)
        except (struct.error, IndexError):
            return
        sprm = struct.unpack_from("<H", data, i)[0]
        yield sprm, data[i + 2:i + size]
        i += size


def _tdef(operand: bytes):
    """sprmTDefTable → (границы столбцов, флаги ячеек): [x0..xn], [(first_merged, merged, vert_merge, vert_restart)]."""
    cb = struct.unpack_from("<H", operand, 0)[0]       # operand[0:2] — длина; дальше itcMac
    body = operand[2:]
    n = body[0]
    xs = list(struct.unpack_from("<%dh" % (n + 1), body, 1))
    flags = []
    base = 1 + 2 * (n + 1)
    for k in range(n):
        o = base + k * 20
        if o + 2 > len(body):
            flags.append((False, False, False, False))
            continue
        g = struct.unpack_from("<H", body, o)[0]
        flags.append((bool(g & 1), bool(g & 2), bool(g & 0x20), bool(g & 0x40)))
    _ = cb
    return xs, flags


def _papx_map(word: bytes, table: bytes, data: bytes = b""):
    """PlcfBtePapx → отсортированные границы fc и свойства абзаца для каждого куска: (in_table, ttp, tdef)."""
    fc, lcb = struct.unpack_from("<II", word, 0x102)
    plc = table[fc:fc + lcb]
    n = (len(plc) - 4) // 8
    pns = [struct.unpack_from("<I", plc, (n + 1) * 4 + k * 4)[0] & 0x3FFFFF for k in range(n)]
    starts: List[int] = []
    props = []
    for pn in pns:
        page = word[pn * 512:(pn + 1) * 512]
        if len(page) < 512:
            continue
        crun = page[511]
        fcs = struct.unpack_from("<%dI" % (crun + 1), page, 0)
        for k in range(crun):
            boff = page[(crun + 1) * 4 + k * 13]
            in_table = ttp = False
            tdef = None
            if boff:
                o = boff * 2
                cb = page[o]
                if cb == 0:
                    cb2 = page[o + 1]
                    body = page[o + 2:o + 2 + cb2 * 2]
                else:
                    body = page[o + 1:o + 1 + (2 * cb - 1)]
                sprms = list(_grpprl(body[2:]))
                for sprm, operand in list(sprms):
                    if sprm == 0x6646 and len(operand) == 4 and data:       # sprmPHugePapx: свойства лежат в потоке Data
                        pos = struct.unpack("<I", operand)[0]
                        if pos + 2 <= len(data):
                            size = struct.unpack_from("<H", data, pos)[0]
                            sprms += list(_grpprl(data[pos + 2:pos + 2 + size]))
                for sprm, operand in sprms:
                    if sprm == 0x2416:
                        in_table = bool(operand[0])
                    elif sprm == 0x2417:
                        ttp = bool(operand[0])
                    elif sprm == 0xD608:
                        try:
                            tdef = _tdef(operand)
                        except (struct.error, IndexError):
                            tdef = None
            starts.append(fcs[k])
            props.append((in_table, ttp, tdef, fcs[k + 1]))
    return starts, props


def _doc_blocks(data: bytes) -> List[Block]:
    streams = word_doc.ole_streams(data)
    word = streams.get("WordDocument")
    if word is None:
        raise word_doc.DocError("в файле нет потока WordDocument")
    flags = struct.unpack_from("<H", word, 0x0A)[0]
    table = streams.get("1Table" if flags & 0x0200 else "0Table")
    if table is None:
        raise word_doc.DocError("в файле нет таблицы текста Word")
    if struct.unpack_from("<H", word, 0)[0] != 0xA5EC:
        raise word_doc.DocError("не файл Word 97–2003 (другая версия формата)")
    ccp = struct.unpack_from("<i", word, 0x4C)[0]
    fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x1A2)
    clx = table[fc_clx:fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 1:
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (len(plc) - 4) // 12
    cps = struct.unpack_from("<%dI" % (n + 1), plc, 0)
    chars: List[str] = []
    fcs: List[int] = []
    for k in range(n):
        fcv = struct.unpack_from("<I", plc, (n + 1) * 4 + k * 8 + 2)[0]
        count = cps[k + 1] - cps[k]
        if fcv & 0x40000000:
            o = (fcv & 0x3FFFFFFF) // 2
            chars += list(word[o:o + count].decode("cp1252", "replace"))
            fcs += [o + j for j in range(count)]
        else:
            chars += list(word[fcv:fcv + count * 2].decode("utf-16le", "replace"))
            fcs += [fcv + 2 * j for j in range(count)]
    if ccp > 0:
        chars, fcs = chars[:ccp], fcs[:ccp]
    starts, props = _papx_map(word, table, streams.get("Data", b""))

    def prop_at(fc: int):
        k = bisect.bisect_right(starts, fc) - 1
        if k < 0 or fc >= props[k][3]:
            return False, False, None
        return props[k][:3]

    out: List[Block] = []
    buf: List[str] = []
    field_stack: List[bool] = []
    cells: List[str] = []
    row_cells: List[str] = []
    trows: List[TRow] = []
    ntab = 0

    def end_row(tdef):
        nonlocal row_cells
        texts = row_cells
        row_cells = []
        if tdef is None:
            xs = [float(j * 1000) for j in range(len(texts) + 1)]
            tflags = [(False, False, False, False)] * len(texts)
        else:
            xs, tflags = tdef
        out_cells: List[Cell] = []
        k = 0
        for j in range(len(xs) - 1):
            first_merged, merged, vmerge, vrestart = tflags[j] if j < len(tflags) else (False, False, False, False)
            if merged and out_cells:
                out_cells[-1].x1 = float(xs[j + 1])
                continue
            text = texts[k] if k < len(texts) else ""
            k += 1
            out_cells.append(Cell(text, float(xs[j]), float(xs[j + 1]), bool(vmerge and not vrestart)))
        trows.append(TRow(out_cells))

    def flush_table():
        nonlocal trows, ntab
        if trows:
            out.append(Table(trows, ntab))
            ntab += 1
            trows = []

    for ch, fc in zip(chars, fcs):
        o = ord(ch)
        if o == 0x13:
            field_stack.append(True)
            continue
        if o == 0x14 and field_stack:
            field_stack[-1] = False
            continue
        if o == 0x15 and field_stack:
            field_stack.pop()
            continue
        if any(field_stack):
            continue
        if ch == "\x07":
            in_table, ttp, tdef = prop_at(fc)
            if in_table or ttp:
                if ttp:
                    if buf:
                        row_cells.append(_tidy("".join(buf)))
                        buf = []
                    end_row(tdef)
                else:
                    row_cells.append(_tidy("".join(buf)))
                    buf = []
                continue
            ch = "\r"
        in_table = prop_at(fc)[0] if ch in "\r\x0b" else False
        if ch in "\r\x0b\x0c":
            if in_table or (ch == "\x0b" and (trows or row_cells)):
                buf.append("\n")
                continue
            flush_table()
            text = "".join(buf).strip()
            buf = []
            if text:
                out.append(Para(text))
            continue
        if ch == "\xa0":
            buf.append(" ")
        elif o >= 32 or ch == "\t":
            buf.append(" " if ch == "\t" else ch)
    flush_table()
    text = "".join(buf).strip()
    if text:
        out.append(Para(text))
    return out


def _sane(blocks: List[Block]) -> bool:
    tabs = [b for b in blocks if isinstance(b, Table)]
    return all(r.cells for t in tabs for r in t.rows)


def read_blocks(path: str) -> List[Block]:
    """Абзацы и таблицы документа по порядку. .doc: свой разбор, при неудаче — через LibreOffice (если установлен)."""
    low = path.lower()
    if low.endswith(".docx"):
        return read_docx_blocks(path)
    with open(path, "rb") as f:
        data = f.read()
    err: Optional[Exception] = None
    try:
        blocks = _doc_blocks(data)
        if _sane(blocks):
            return blocks
    except (word_doc.DocError, struct.error, IndexError, ValueError) as e:
        err = e
    try:
        from . import office_convert
        exe = office_convert.find_soffice() if data[:8] == bytes.fromhex("d0cf11e0a1b11ae1") else None     # LibreOffice — только для настоящих .doc
        if exe:
            with tempfile.TemporaryDirectory() as tmp:
                dst = os.path.join(tmp, "x.docx")
                office_convert.convert_file(path, "docx", dst, exe)
                return read_docx_blocks(dst)
    except Exception:
        pass
    raise word_doc.DocError("файл .doc не разобран: %s" % (err or "таблицы не распознаны"))
