"""Вывод OCR (MinerU: ``*content_list.json`` или markdown с HTML-таблицами) → те же блоки (абзацы и таблицы с геометрией ячеек), что даёт ``word_tables``.

Дальше работает прежний разбор отчёта ГИС (``gis_report.parse_blocks``): Word, PDF с текстовым слоем и сканы дают одну и ту же БД.
JSON предпочтительнее markdown: в нём есть номер страницы каждого блока (источник значения «стр. N») и таблица приходит отдельным полем.

Что читается (форматы MinerU разных версий; незнакомые поля пропускаются, а не ломают разбор):
* список блоков ``{"type": "text"|"table"|…, "text", "text_level", "table_body", "page_idx"}``;
* список страниц (список блоков на страницу) и обёртки ``{"pdf_info": …}`` / ``{"content_list": …}``;
* блоки нового вида ``{"type": "paragraph"|"table"|"title", "content": {…}}``.
Таблица: HTML с ``rowspan``/``colspan``; ширины столбцов в OCR нет, колонки равные — важно только взаимное положение ячеек и объединений.
Сетка не угадывается сверх того, что вернул OCR; число, прочитанное с ошибкой, программа не исправляет — подозрительные места подсвечивает ``gis_report``.
"""
from __future__ import annotations

import html
import json
import os
import re
from html.parser import HTMLParser
from typing import Any, List, Optional, Tuple

from . import word_tables as wt

COL = 1000.0                  # ширина одного столбца сетки, твипы (OCR ширин не даёт)
OCR_NAME = re.compile(r"(content_list.*\.json|\.ocr\.md|(^|[\\/])full\.md)$", re.I)


def ocr_stem(path: str) -> str:
    """Имя исходного документа по имени файла OCR: ``отчёт_content_list.json`` / ``отчёт.ocr.md`` → ``отчёт`` (путь без расширения, в нижнем регистре)."""
    base = os.path.splitext(path)[0]
    base = re.sub(r"([_.]content_list.*|\.ocr)$", "", base, flags=re.I)
    return base.lower()


def is_ocr_file(path: str) -> bool:
    """Файл вывода OCR, который берётся при просмотре папки: ``*content_list.json``, ``*.ocr.md``, ``full.md``. Любой иной json/md без явной просьбы не трогается."""
    return bool(OCR_NAME.search(path))


# ------------------------------------------------------------------------------------------------ чистка текста

_SUB = re.compile(r"</?(sub|sup)>", re.I)
_TAG = re.compile(r"<[^>]+>")
_TEX_SCRIPT = re.compile(r"[_^]\{([^{}]*)\}|[_^](\w)")
_LATIN_K = re.compile(r"(?<![A-Za-z])K(?=[гпГП](?![а-яa-z]))|(?<![A-Za-z])K(?=\s?(гтек|гср|гэф))")


def clean_text(text: Any) -> str:
    """Теги и TeX → простой текст (``K<sub>г</sub>`` и ``$K_{г}$`` → «Кг», ``<br>`` → перенос), латинская K перед индексом г/п → русская К."""
    s = html.unescape(str(text or "")).replace("\x00", "")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _SUB.sub("", s)
    s = _TAG.sub("", s)
    s = re.sub(r"\$([^$]*)\$", lambda m: _TEX_SCRIPT.sub(lambda g: g.group(1) if g.group(1) is not None else g.group(2), m.group(1)), s)
    s = re.sub(r"\\(?:text|mathrm|mathbf)\{([^{}]*)\}", r"\1", s).replace("\\%", "%").replace("\\,", " ").replace("\\ ", " ")
    s = s.replace("\u00a0", " ")
    lines = (" ".join(p.split()) for p in s.split("\n"))
    s = "\n".join(p for p in lines if p)
    return _LATIN_K.sub("К", s)


# ------------------------------------------------------------------------------------------------ HTML-таблица

class _Html(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[List[dict]] = []
        self._cell: Optional[dict] = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            if not self.rows:
                self.rows.append([])
            self._cell = {"text": [], "rs": _int(a.get("rowspan")), "cs": _int(a.get("colspan"))}
            self.rows[-1].append(self._cell)
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append("\n")
        elif tag in ("sub", "sup"):
            pass

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"].append(data)


def _int(v) -> int:
    try:
        return max(1, int(str(v).strip()))
    except (TypeError, ValueError):
        return 1


def table_from_html(src: str, index: int = 0) -> Optional[wt.Table]:
    """HTML ``<table>`` → ``Table``: colspan растягивает ячейку по сетке, rowspan оставляет под ней пустые ``vcont``-ячейки (как объединение в Word)."""
    p = _Html()
    p.feed(src)
    if not p.rows or not any(p.rows):
        return None
    taken: dict = {}                 # (строка, столбец) → занято rowspan сверху
    grid_rows: List[List[Tuple[int, int, str, bool]]] = []
    width = 0
    for r, row in enumerate(p.rows):
        c = 0
        out: List[Tuple[int, int, str, bool]] = []
        for cell in row:
            while (r, c) in taken:
                c += 1
            out.append((c, c + cell["cs"], clean_text("".join(cell["text"])), False))
            for dr in range(1, cell["rs"]):
                for dc in range(cell["cs"]):
                    taken[(r + dr, c + dc)] = (c, c + cell["cs"])
            c += cell["cs"]
        width = max(width, c)
        grid_rows.append(out)
    rows: List[wt.TRow] = []
    for r, out in enumerate(grid_rows):
        cells = [wt.Cell(t, a * COL, b * COL) for a, b, t, _v in out]
        # места под объединением сверху: по одной vcont-ячейке на каждую объединённую ячейку выше
        for span in sorted({v for (rr, _c), v in taken.items() if rr == r}):
            cells.append(wt.Cell("", span[0] * COL, span[1] * COL, vcont=True))
        cells.sort(key=lambda x: x.x0)
        rows.append(wt.TRow(cells))
    return wt.Table(rows=rows, index=index)


def table_from_pipes(lines: List[str], index: int = 0) -> Optional[wt.Table]:
    """Markdown-таблица ``| a | b |`` (без объединений) → ``Table``."""
    rows = []
    for ln in lines:
        s = ln.strip()
        if re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", s):
            continue
        cells = [clean_text(x) for x in s.strip("|").split("|")]
        rows.append(wt.TRow([wt.Cell(t, i * COL, (i + 1) * COL) for i, t in enumerate(cells)]))
    return wt.Table(rows=rows, index=index) if rows else None


# ------------------------------------------------------------------------------------------------ JSON

def _flatten(data: Any, page: Optional[int] = None) -> List[Tuple[dict, Optional[int]]]:
    """Любая из обёрток → плоский список (блок, номер страницы с 1 или None)."""
    if isinstance(data, dict):
        for key in ("content_list", "pdf_info", "pages", "blocks", "para_blocks"):
            if key in data:
                return _flatten(data[key], page)
        return [(data, _page(data, page))] if "type" in data else []
    out: List[Tuple[dict, Optional[int]]] = []
    if isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, list):                            # список страниц
                out += _flatten(item, i + 1)
            elif isinstance(item, dict) and "type" not in item and any(k in item for k in ("para_blocks", "blocks", "content_list")):
                p = item.get("page_idx", item.get("page_no"))
                out += _flatten(item, (p + 1) if isinstance(p, int) and "page_no" not in item else (p if isinstance(p, int) else i + 1))
            elif isinstance(item, dict):
                out.append((item, _page(item, page)))
    return out


def _page(block: dict, default: Optional[int]) -> Optional[int]:
    p = block.get("page_idx")
    if isinstance(p, int):
        return p + 1
    p = block.get("page_no", block.get("page"))
    return p if isinstance(p, int) else default


def _block_text(b: dict) -> str:
    c = b.get("content")
    if isinstance(c, dict):
        for key in ("paragraph_content", "title_content", "text", "content"):
            v = c.get(key)
            if isinstance(v, list):
                return "".join(str(x.get("content", x.get("text", ""))) if isinstance(x, dict) else str(x) for x in v)
            if isinstance(v, str):
                return v
        return ""
    if isinstance(c, str):
        return c
    t = b.get("text")
    if isinstance(t, list):
        return " ".join(str(x) for x in t)
    return str(t or "")


def _table_html(b: dict) -> str:
    for key in ("table_body", "html", "table_html"):
        v = b.get(key)
        if isinstance(v, str) and "<t" in v.lower():
            return v
    c = b.get("content")
    if isinstance(c, dict):
        for key in ("html", "table_body", "table_content"):
            v = c.get(key)
            if isinstance(v, str) and "<t" in v.lower():
                return v
    return ""


def blocks_from_json(data: Any) -> Tuple[List[wt.Block], List[str]]:
    """Список блоков MinerU → (блоки, заметки). Рисунки без текста пропускаются, нераспознанные таблицы названы в заметках."""
    blocks: List[wt.Block] = []
    notes: List[str] = []
    count = 0
    last_table: Optional[Tuple[int, int, int]] = None        # (индекс в blocks, страница, число столбцов)
    for b, page in _flatten(data):
        kind = str(b.get("type", "")).lower()
        if kind == "table" or (kind not in ("text", "paragraph", "title", "list", "equation", "header", "footer", "page_number", "page_footnote") and _table_html(b)):
            src = _table_html(b)
            tbl = table_from_html(src, count) if src else None
            if tbl is None:
                notes.append("%sтаблица не разобрана (OCR вернул её без HTML, например картинкой)" % ("стр. %d: " % page if page else ""))
                last_table = None
                continue
            tbl.row_pages = [page or 0] * len(tbl.rows) if page else []
            ncols = round(tbl.x1 / COL)
            if last_table and page and last_table[1] + 1 == page and last_table[2] == ncols and isinstance(blocks[last_table[0]], wt.Table):
                prev = blocks[last_table[0]]            # таблица продолжается на следующей странице: склеиваем (подсказка, в заметке)
                prev.rows.extend(tbl.rows)
                prev.row_pages.extend(tbl.row_pages)
                notes.append("стр. %d: таблица продолжена с предыдущей страницы (склеена)" % page)
                last_table = (last_table[0], page, ncols)
            else:
                blocks.append(tbl)
                last_table = (len(blocks) - 1, page or 0, ncols)
                count += 1
            continue
        if kind in ("header", "footer", "page_number", "page_footnote", "image", "figure", "chart", "seal"):
            continue
        text = clean_text(_block_text(b))
        if text:
            blocks.append(wt.Para(text))
            last_table = None
    return blocks, notes


# ------------------------------------------------------------------------------------------------ markdown

_TABLE_RX = re.compile(r"<table\b.*?</table>", re.I | re.S)


def blocks_from_markdown(text: str) -> Tuple[List[wt.Block], List[str]]:
    """Markdown (HTML-таблицы или ``|``-таблицы + абзацы). Номеров страниц в markdown нет: источник — «таблица N, строка M»."""
    blocks: List[wt.Block] = []
    count = 0

    def paras(chunk: str) -> None:
        pipe: List[str] = []

        def flush() -> None:
            nonlocal count
            if pipe:
                t = table_from_pipes(pipe, count)
                if t is not None:
                    blocks.append(t)
                    count += 1
                pipe.clear()
        for part in re.split(r"\n\s*\n", chunk):
            for ln in part.split("\n"):
                if ln.strip().startswith("|"):
                    pipe.append(ln)
                    continue
                flush()
                s = clean_text(re.sub(r"^\s*#+\s*", "", ln))
                if s:
                    blocks.append(wt.Para(s))
            flush()
    pos = 0
    for m in _TABLE_RX.finditer(text):
        paras(text[pos:m.start()])
        t = table_from_html(m.group(0), count)
        if t is not None:
            blocks.append(t)
            count += 1
        pos = m.end()
    paras(text[pos:])
    return blocks, []


# ------------------------------------------------------------------------------------------------ вход

def find_for_pdf(pdf_path: str) -> str:
    """Вывод OCR рядом с PDF: ``<имя>.ocr.md``, ``<имя>_content_list.json``, ``<имя>/…content_list.json`` (как кладёт MinerU). Пустая строка, если нет."""
    base, _ext = os.path.splitext(pdf_path)
    for cand in (base + "_content_list.json", base + ".content_list.json", base + ".ocr.md"):
        if os.path.isfile(cand):
            return cand
    if os.path.isdir(base):
        for root, _d, files in os.walk(base):
            for f in sorted(files):
                if f.lower().endswith("content_list.json"):
                    return os.path.join(root, f)
    return ""


def read_ocr(path: str) -> Tuple[List[wt.Block], List[str]]:
    """Файл вывода OCR → (блоки, заметки)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8-sig", errors="replace")
    if path.lower().endswith(".json"):
        return blocks_from_json(json.loads(text))
    return blocks_from_markdown(text)
