"""Месячный отчёт ПХГ (эксплуатация, бурение, ремонтный фонд, замеры давлений, межколонные давления) -> листы БД.

Вход — markdown распознавания (``pxg_ocr.engine``): таблицы HTML ``<table>`` с rowspan/colspan и ``| a | b |``. Один лист =
одна таблица одного вида; одинаковые таблицы из разных мест файла (например, межколонные давления на двух страницах)
идут на один лист. В каждую строку добавлены идентификаторы, которые видны из контекста: ПХГ, Период (ГГГГ-ММ),
Скважина, Дата. Программа только помощник: значение, которое не удалось разобрать, остаётся как есть, а в столбце
«Проверка» стоит причина — решает инженер. Только стандартная библиотека; запись — ``pxg_ocr.extract.write_xlsx``.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from pxg_ocr.extract import MONTHS, flat, pipe_tables, ru_date, unlatex

Sheets = Dict[str, Tuple[List[str], List[list]]]


# ----------------------------------------------------------------------------- таблицы с rowspan/colspan
class _Grid(HTMLParser):
    """HTML-таблицы -> прямоугольные сетки: объединённые по вертикали ячейки повторяются вниз, по горизонтали — пустые."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._rs = self._cs = 1
        self._pending: Dict[int, Tuple[int, str]] = {}  # колонка -> (сколько строк ещё повторять, текст)

    def _fill(self) -> None:
        while self._row is not None and len(self._row) in self._pending:
            left, text = self._pending[len(self._row)]
            self._row.append(text)
            if left <= 1:
                del self._pending[len(self._row) - 1]
            else:
                self._pending[len(self._row) - 1] = (left - 1, text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.tables.append([])
            self._pending = {}
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._fill()
            self._cell = []
            self._rs = max(1, int(a.get("rowspan") or 1))
            self._cs = max(1, int(a.get("colspan") or 1))

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            col = len(self._row)
            self._row.append(text)
            self._row.extend([""] * (self._cs - 1))
            if self._rs > 1:
                self._pending[col] = (self._rs - 1, text)
            self._cell = None
        elif tag == "tr" and self._row is not None and self.tables:
            self._fill()
            self.tables[-1].append(self._row)
            self._row = None


def grids(md: str) -> List[List[List[str]]]:
    p = _Grid()
    p.feed(html.unescape(md) if "&lt;table" in md else md)
    return p.tables


# ----------------------------------------------------------------------------- значения
def val(s: str):
    """«1 154,660» -> 1154.66; «-»/пусто -> None («нет данных» — пропуск); иное (например «44,5/45,05») — текст как есть."""
    t = unlatex(s or "").replace("\xa0", " ").strip()
    if t in ("", "-", "–", "—"):
        return None
    c = t.replace(" ", "").replace(",", ".").replace("−", "-")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", c):
        return t
    return int(c) if re.fullmatch(r"-?\d+", c) else float(c)


def _date(s: str):
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(20\d\d)", s or "")
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
    except ValueError:
        return None


def _well(s: str):
    t = re.sub(r"^(?:N[oо°]?|№)\s*", "", (s or "").strip(), flags=re.I)
    return int(t) if t.isdigit() else (t or None)


def context(md: str) -> Tuple[str, str, str]:
    """(ПХГ, период ГГГГ-ММ, режим закачка/отбор) из заголовков отчёта."""
    f = flat(md)
    m = re.search(r"([А-ЯЁ][а-яё]+(?:ское|ое))\s+ПХГ", f)
    pxg = m.group(1) if m else ""
    m = re.search(r"за\s+([а-я]+)\s+месяц\s+(20\d\d)", f, re.I) or re.search(r"([а-я]+)\s+(20\d\d)\s*г", f, re.I)
    mon = 0
    if m:  # «сентябрь» -> 9 по первым трём буквам (в тексте месяц в именительном падеже)
        w = "мая" if m.group(1).lower() == "май" else m.group(1).lower()
        mon = next((n for name, n in MONTHS.items() if name[:3] == w[:3]), 0)
    period = "%s-%02d" % (m.group(2), mon) if m and mon else ""
    low = f.lower()
    mode = "закачка" if "закачка газа" in low or "– закачка" in low else ("отбор" if "отбор газа" in low else "")
    return pxg, period, mode


def _is_int(s: str) -> bool:
    return bool(re.fullmatch(r"\d+", (s or "").strip()))


# ----------------------------------------------------------------------------- извлечение
def extract_monthly(md: str, source: str = "") -> Sheets:
    pxg, period, mode = context(md)
    ID = [pxg, period]
    idc = ["ПХГ", "Период"]
    out: Sheets = {}

    for tb in grids(md):
        head = " ".join(" ".join(r) for r in tb[:3]).lower()
        if "наименование показателей" in head:
            name = "Показатели ПХГ"
            cols = ["Режим", "№ п/п", "Показатель", "Ед. изм.", "Итого ПХГ", "Гдовский I пласт"]
            rows, main, num = [], "", ""
            # «Отбор» в шапке — пустой столбец распознавания: значения только в «Итого» и «Гдовский I пласт»
            for r in tb[2:]:
                if len(r) < 6 or not r[3].strip():
                    continue
                n, a, b = r[0].strip(), r[1].strip(), r[2].strip()
                if b:  # «в том числе» + подпоказатель под основным
                    label = "%s — %s" % (main, b)
                else:
                    main = label = a
                num = n if re.fullmatch(r"\d+\.?", n) else num
                rows.append([mode, num, label, r[3], val(r[4]), val(r[5])])
        elif "состав фонда скважин" in head:
            cols = ["Режим", "Состав фонда", "Всего на ПХГ, шт.", "На балансе ПХГ: кол. скв.", "На балансе ПХГ: № скважин",
                    "В других организациях: кол. скв.", "В других организациях: № скважин"]
            rows = []
            wells: List[list] = []
            for r in tb[2:]:
                if len(r) < 6 or not r[0].strip():
                    continue
                rows.append([mode, r[0], val(r[1]), val(r[2]), r[3] or None, val(r[4]), r[5] or None])
                for owner, lst in (("на балансе ПХГ", r[3]), ("в других организациях", r[5])):
                    for tok in re.split(r"[,;]", lst):
                        tok = tok.strip()
                        if tok and tok != "-":
                            wells.append([mode, r[0], owner, _well(tok)])
            out.setdefault("Фонд скважин", (idc + cols, []))[1].extend(ID + x for x in rows)
            out.setdefault("Фонд_по_скважинам", (idc + ["Режим", "Состав фонда", "Принадлежность", "Скважина"], []))[1].extend(ID + x for x in wells)
            continue
        elif "n строки" in head or "№ строки" in head or "строки" in head and "план" in head:
            cols = ["Показатель", "№ строки", "План", "Факт"]
            rows = [[r[0], _well(r[1]), val(r[2]), val(r[3])] for r in tb[2:] if len(r) >= 4 and r[0].strip()]
            name = "Проходка и скважины"
        elif "начала бурения" in head:
            cols = ["Площадь", "Скважина", "Начало бурения", "Окончание бурения", "Сдача ПХГ", "Окончательный забой", "Примечание"]
            rows = []
            for r in tb[2:]:
                if len(r) >= 8 and any(x.strip() not in ("", "-") for x in r[1:]):
                    rows.append([r[0], _well(r[1]), _date(r[2]), _date(r[3]), _date(r[4]), val(r[5]), r[7] or r[6] or None])
            name = "Движение скважин"
        elif "перечень необходимых работ" in head:
            cols = ["№ п/п", "Скважина", "Местоположение, горизонт", "Состояние, дефекты", "Перечень необходимых работ", "Дата ведомости"]
            m = re.search(r"бездействующего.{0,120}?по состоянию на\s+([^.]{5,30}?20\d\d)", flat(md))
            asof = _date(ru_date(m.group(1))) if m else None
            rows = [[r[0], _well(r[1]), r[2], r[3], r[4], asof] for r in tb[1:] if len(r) >= 5 and r[1].strip()]
            name = "Бездействующий фонд"
        elif "дата замера" in head and "пласт" in head:
            cols = ["Категория", "№ п/п", "Скважина", "Пласт", "Дата замера", "Р уст., кгс/см2 (как в отчёте)", "Р уст. 1", "Р уст. 2",
                    "Нст, м", "Рпл, ата", "Примечание", "Проверка"]
            rows, cat = [], ""
            for r in tb[1:]:
                if len(r) >= 8 and r[0].strip() and not any(x.strip() for x in r[1:]):
                    cat = r[0].strip()
                    continue
                if len(r) < 8 or not r[1].strip():
                    continue
                p = [x.strip() for x in r[4].split("/")]
                p1, p2 = (val(p[0]), val(p[1])) if len(p) == 2 else (val(r[4]), None)
                dte = _date(r[3])
                chk = []
                if dte is None:
                    chk.append("замера нет (дата «-»)" if r[3].strip() in ("-", "") else "дата не распознана: «%s»" % r[3])
                if val(r[6]) is not None and not isinstance(val(r[6]), (int, float)):
                    chk.append("Рпл не число: «%s»" % r[6])
                rows.append([cat, r[0].strip(), _well(r[1]), r[2], dte or r[3], r[4], p1, p2, val(r[5]), val(r[6]), r[7] or None, "; ".join(chk)])
            name = "Замеры давлений"
        elif "межколонное давление" in head:
            cols = ["№ п/п", "Скважина", "МКД, кгс/см2", "МКД, МПа", "Объём стравленного газа, м3", "Q мкп, тыс. м3/сут", "Проверка"]
            rows = []
            for r in tb:
                if len(r) >= 6 and _is_int(r[0]) and r[1].strip():
                    v = [val(x) for x in r[2:6]]
                    chk = "; ".join("не число: «%s»" % x for x, y in zip(r[2:6], v) if isinstance(y, str))
                    rows.append([int(r[0]), _well(r[1])] + v + [chk])
            name = "Межколонные давления"
        elif "поручение" in head and "срок выполнения" in head:
            cols = ["Протокол", "№ п/п", "Поручение", "Срок выполнения", "Срок (как в отчёте)", "Статус выполнения", "Примечание"]
            rows = [[r[0], r[1], r[2], _date(r[3]), r[3], r[4], r[5] or None] for r in tb[1:] if len(r) >= 6 and r[2].strip()]
            name = "Поручения комиссии"
        else:
            continue
        out.setdefault(name, (idc + cols, []))[1].extend(ID + x for x in rows)

    for tb in pipe_tables(md):
        if tb and len(tb[0]) >= 2 and "ремонта" in tb[0][1].lower():
            rows = []
            for r in tb[1:]:
                for i, w in enumerate(x.strip() for x in r[1].split(";") if x.strip()):
                    m = re.match(r"((?:КР|ИС|ТР)?\s*\d+\.\d+)\s+(.*)", w, re.S)
                    rows.append([_well(r[0]), i + 1, m.group(1) if m else None, (m.group(2) if m else w).strip(" .")])
            out.setdefault("Ремонтный фонд", (idc + ["Скважина", "№ работы", "Код работы", "Работа"], []))[1].extend(ID + x for x in rows)

    notes = []
    for ln in html.unescape(md).splitlines():
        t = unlatex(re.sub(r"^[\\*\s]+", "", ln)).strip()
        if re.match(r"(Ликвидированные в \d{4}|Количество газа, стравленного)", t):
            notes.append(t)
    if notes:
        out["Примечания"] = (idc + ["Текст"], [ID + [t] for t in notes])
    return out
