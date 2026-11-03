"""PDF с текстовым слоем → те же блоки (абзацы и таблицы с геометрией ячеек), что даёт ``word_tables``; дальше работает прежний разбор отчёта.

Библиотека pdfplumber (чистый Python + pdfminer.six + pypdfium2 с колёсами manylinux2014: работает на РЕД ОС 7.3). Таблицы берутся по линиям
сетки; объединённые ячейки получают прежние признаки (``x0``/``x1``, ``vcont``), поэтому пачки, шапки замеров и ГВК читаются так же, как в Word.
Страница без текстового слоя (скан) не угадывается: она попадает в ``notes`` как «нужен OCR / не прочитано»."""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Tuple

from . import word_tables as wt

TWIPS = 20.0                 # 1 пункт PDF = 20 twips, как в Word-блоках (пороги разбора общие)
WRAP = 0.86                  # правый край строки правее этой доли ширины страницы — строка перенесена
GAP = 1.6                    # разрыв между строками текста больше GAP × высоты строки — новый абзац


_SUBSCRIPT = re.compile(r"К\n(г|п|гтек|гср|гэф)(?=\n|$)")     # индекс «Кг», «Кп» PDF режет на отдельную строку


def _clean(text) -> str:
    """Пробелы схлопываются, переносы строк внутри ячейки остаются (как «\\n» в Word)."""
    lines = (" ".join(p.split()) for p in str(text or "").replace("\x00", "").split("\n"))
    return _SUBSCRIPT.sub(r"К\1", "\n".join(p for p in lines if p))


def _table(page_tbl, number: int) -> Tuple[wt.Table, float]:
    """Таблица pdfplumber → ``Table`` с ячейками по геометрии; пустые места под объединением сверху — ``vcont``."""
    texts = page_tbl.extract()
    rows: List[wt.TRow] = []
    spans: List[Tuple[float, float, float]] = []        # (x0, x1, низ ячейки), тянущиеся вниз
    for r, row in enumerate(page_tbl.rows):
        cells = []
        top = row.bbox[1]
        spans = [s for s in spans if s[2] > top + 1]
        for (x0, x1, _b) in spans:
            cells.append(wt.Cell("", x0 * TWIPS, x1 * TWIPS, vcont=True))
        for j, box in enumerate(row.cells):
            if box is None:
                continue
            text = _clean(texts[r][j]) if j < len(texts[r]) else ""
            cells.append(wt.Cell(text, box[0] * TWIPS, box[2] * TWIPS))
            if box[3] > row.bbox[3] + 1:
                spans.append((box[0], box[2], box[3]))
        cells.sort(key=lambda c: c.x0)
        rows.append(wt.TRow(cells))
    return wt.Table(rows=rows, index=number), page_tbl.bbox[3]


def _paragraphs(lines, page_width: float) -> List[Tuple[float, str]]:
    """Строки → абзацы: строка продолжается следующей, только если дошла почти до правого края (перенос), иначе абзац кончился — как в Word."""
    out: List[Tuple[float, str]] = []
    prev = None
    for ln in lines:
        text = _clean(ln["text"])
        if not text:
            continue
        wrapped = prev is not None and prev["x1"] >= page_width * WRAP and 0 <= ln["top"] - prev["bottom"] <= GAP * (prev["bottom"] - prev["top"]) * 0.5
        if wrapped:
            out[-1] = (out[-1][0], out[-1][1] + "\n" + text)
        else:
            out.append((ln["top"], text))
        prev = ln
    return out


def _edge_lines(pdf) -> set:
    """Колонтитулы: строки у верхнего/нижнего края, повторяющиеся на страницах (цифры не в счёт: «стр. 2 из 5»)."""
    seen: Counter = Counter()
    for page in pdf.pages:
        keys = set()
        for ln in page.extract_text_lines():
            if ln["top"] < page.height * 0.12 or ln["bottom"] > page.height * 0.88:
                keys.add(re.sub(r"\d+", "#", _clean(ln["text"])))
        seen.update(keys)
    return {k for k, n in seen.items() if n >= 2 and len(pdf.pages) >= 2}


def read_pdf(path: str) -> Tuple[List[wt.Block], List[str]]:
    """(блоки по порядку, заметки). Таблица, продолжающаяся на следующей странице, склеивается в одну."""
    import pdfplumber
    blocks: List[wt.Block] = []
    notes: List[str] = []
    count = 0
    tail = None                       # (индекс таблицы в blocks, низ последней таблицы страницы, высота страницы)
    with pdfplumber.open(path) as pdf:
        edges = _edge_lines(pdf)
        for number, page in enumerate(pdf.pages, 1):
            if not page.chars:
                notes.append("стр. %d: нет текстового слоя (скан) — нужен OCR, страница не прочитана" % number)
                tail = None
                continue
            found = page.find_tables()
            boxes = [t.bbox for t in found]
            outside = page.filter(lambda o: not any(b[0] - 1 <= o.get("x0", 0) and o.get("x1", 0) <= b[2] + 1 and b[1] - 1 <= o.get("top", 0) and o.get("bottom", 0) <= b[3] + 1
                                                     for b in boxes)) if boxes else page
            items: List[Tuple[float, str, object]] = [(t.bbox[1], "t", t) for t in found]
            items += [(top, "p", text) for top, text in _paragraphs([ln for ln in outside.extract_text_lines()
                                                  if re.sub(r"\d+", "#", _clean(ln["text"])) not in edges], page.width)]
            items.sort(key=lambda x: x[0])
            first = True
            for top, kind, obj in items:
                if kind == "p":
                    blocks.append(wt.Para(obj))
                    first = False
                    continue
                tbl, bottom = _table(obj, count)
                pages = [number] * len(tbl.rows)
                if first and tail is not None and tail[1] > tail[2] * 0.8 and top < page.height * 0.2 and isinstance(blocks[tail[0]], wt.Table):
                    prev = blocks[tail[0]]
                    prev.rows.extend(tbl.rows)
                    prev.row_pages.extend(pages)
                    tail = (tail[0], bottom, page.height)
                else:
                    tbl.row_pages = pages
                    blocks.append(tbl)
                    tail = (len(blocks) - 1, bottom, page.height)
                    count += 1
                first = False
            if not any(k == "t" for _t, k, _o in items):
                tail = None
    return blocks, notes
