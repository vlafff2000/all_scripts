"""Результат OCR MinerU (content_list.json или markdown) → страницы текстовой сетки для разбора отчётов ГДИС.

Разбор отчёта (`гдис_pdf.scan_pages`) работает по строкам с сохранёнными позициями символов. У скана текстового слоя нет,
поэтому блоки текста и таблицы (HTML) из вывода MinerU раскладываются в такие же строки: клетки таблицы встают в столбцы
по ширине, пустая клетка сохраняет своё место. Дальше — прежний разбор без изменений.

Сам MinerU здесь не запускается: модуль читает только готовые файлы (`*_content_list.json`, `*.md`).
"""
from __future__ import annotations

import json
import os
import re
from html import unescape
from html.parser import HTMLParser
from typing import List, Optional

HEADER_STUB = " "      # первая строка страницы в разборе считается колонтитулом; у OCR его нет — пустая заглушка


class _Tables(HTMLParser):
    """HTML-таблица → прямоугольная сетка строк (colspan/rowspan раскрыты)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: List[List[str]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._span = (1, 1)
        self._pending: dict = {}      # (строка, столбец) → текст, занятый rowspan сверху

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
            try:
                self._span = (max(1, int(a.get("colspan", 1))), max(1, int(a.get("rowspan", 1))))
            except ValueError:
                self._span = (1, 1)
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = re.sub(r"\s+", " ", unescape("".join(self._cell))).strip()
            r = len(self.rows)
            while (r, len(self._row)) in self._pending:
                self._row.append(self._pending.pop((r, len(self._row))))
            cs, rs = self._span
            c0 = len(self._row)
            for k in range(cs):
                self._row.append(text if k == 0 else "")
            for dr in range(1, rs):
                for k in range(cs):
                    self._pending[(r + dr, c0 + k)] = ""
            self._cell = None
        elif tag == "tr" and self._row is not None:
            r = len(self.rows)
            while (r, len(self._row)) in self._pending:
                self._row.append(self._pending.pop((r, len(self._row))))
            self.rows.append(self._row)
            self._row = None


def html_table(html: str) -> List[List[str]]:
    p = _Tables()
    p.feed(html or "")
    width = max((len(r) for r in p.rows), default=0)
    return [r + [""] * (width - len(r)) for r in p.rows]


def grid_lines(rows: List[List[str]], gap: int = 3) -> List[str]:
    """Строки таблицы, выровненные по столбцам; в клетке не бывает двух пробелов подряд (иначе это разные клетки)."""
    if not rows:
        return []
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    lines = []
    for r in rows:
        line, pos = "", 0
        for c, text in enumerate(r):
            if text:
                line += " " * max(0, pos - len(line)) + text
            pos += widths[c] + gap
        if line.strip():
            lines.append(line.rstrip())
    return lines


def _md_rows(block: List[str]) -> List[List[str]]:
    rows = []
    for ln in block:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and any(cells):
            continue
        rows.append(cells)
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


def pages_from_content_list(data) -> List[List[str]]:
    """content_list MinerU (список блоков с `page_idx`, `type` text/table/…) → страницы строк."""
    if isinstance(data, dict):
        data = data.get("content_list") or data.get("blocks") or []
    pages: dict = {}
    for b in data:
        if not isinstance(b, dict):
            continue
        out = pages.setdefault(int(b.get("page_idx", 0) or 0), [])
        kind = b.get("type", "")
        if kind == "table":
            body = b.get("table_body") or b.get("html") or ""
            out += [t for t in [*([b["table_caption"]] if isinstance(b.get("table_caption"), str) else
                                  b.get("table_caption") or [])] if t]
            out += grid_lines(html_table(body))
        elif kind in ("text", "title", "header", "list"):
            texts = b.get("list_items") if kind == "list" else [b.get("text", "")]
            for t in texts or []:
                out += [re.sub(r"\s{2,}", " ", ln).strip() for ln in str(t).split("\n") if ln.strip()]
    return [[HEADER_STUB] + [ln for ln in pages[k] if ln.strip()] for k in sorted(pages)]


def pages_from_markdown(text: str) -> List[List[str]]:
    """Markdown MinerU: страницы разделяются формфидом или `---` на отдельной строке; таблицы — HTML или `| a | b |`."""
    pages: List[List[str]] = []
    for chunk in re.split(r"\f|\n-{3,}\n", text):
        lines: List[str] = []
        raw = chunk.split("\n")
        i = 0
        while i < len(raw):
            ln = raw[i]
            if "<table" in ln.lower():
                html = ln
                while "</table>" not in html.lower() and i + 1 < len(raw):
                    i += 1
                    html += raw[i]
                lines += grid_lines(html_table(html))
            elif ln.lstrip().startswith("|"):
                j = i
                while j < len(raw) and raw[j].lstrip().startswith("|"):
                    j += 1
                lines += grid_lines(_md_rows(raw[i:j]))
                i = j - 1
            elif ln.strip():
                lines.append(re.sub(r"\s{2,}", " ", ln.strip().lstrip("#").strip()))
            i += 1
        if lines:
            pages.append([HEADER_STUB] + lines)
    return pages


def is_ocr_output(path: str) -> bool:
    low = path.lower()
    return low.endswith("_content_list.json") or low.endswith(".md")


def read_ocr_pages(path: str) -> List[List[str]]:
    with open(path, encoding="utf-8") as f:
        if path.lower().endswith(".json"):
            return pages_from_content_list(json.load(f))
        return pages_from_markdown(f.read())


def sidecar(pdf_path: str) -> Optional[str]:
    """Готовый результат OCR рядом с PDF: `имя_content_list.json` или `имя.md` (приоритет у JSON)."""
    base, _ = os.path.splitext(pdf_path)
    for cand in (base + "_content_list.json", base + ".md"):
        if os.path.isfile(cand):
            return cand
    return None
