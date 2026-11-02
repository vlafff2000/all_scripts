"""Конструкции скважин по датам из Word-перечня («Перечень ИС экспл. фонд»): строки «скважина — конструкция — дата — комплекс ГИС — интервал — примечание»
→ таблицы для Газового Атласа: конструкции на каждую дату, методы исследований, текущий забой, пометка «Ресурс».

Каждая строка перечня — снимок конструкции на дату исследования; ничего не склеивается и не отбрасывается молча: идентичные снимки остаются,
а лист «Изменения» показывает, где конструкцию заменили целиком и где поменялись только глубины. Глубины — по стволу (MD), от стола ротора.
Автоматика — подсказка: спорное попадает в «Проверку» с причиной, перфорации глубже порога — в «Исключено» (вернуть можно вручную).
Разбор только .docx (без Word и LibreOffice); .doc сначала переведите «Конвертером форматов Office».
"""
from __future__ import annotations

import datetime as dt
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DEFAULT_MAX_PERF_DEPTH = 950.0
OUT_FILE = "Конструкции_из_Word_для_Атласа.xlsx"        # то, что загружается в Атлас: листы «Конструкция» и «Замеры забоя»
REPORT_FILE = "Конструкции_из_Word_разбор.xlsx"          # разбор для инженера: методы, скважины, изменения, исключено, проверка (Атлас их не читает)

CONS_COLUMNS = ["Скважина", "Дата конструкции", "Элемент", "Верх интервала, м", "Низ интервала, м", "Наружный диаметр, мм",
                "Внутренний диаметр, мм", "Комментарий", "Комплект", "Ресурс", "Строка перечня"]
BOTTOM_COLUMNS = ["Скважина", "Дата", "Текущий забой, м", "Диаметр шаблона, мм", "Метод замера", "Комментарий"]
METHOD_COLUMNS = ["Скважина", "Дата", "Методы", "Цель", "Интервал от, м", "Интервал до, м", "Примечание", "Источник"]

NUM = r"\d+(?:[.,]\d+)?"
DASH = r"[–—−-]"
STRINGS = {"эк": "Эксплуатационная колонна", "э/к": "Эксплуатационная колонна", "нкт": "НКТ", "тк": "Техническая колонна",
           "кондуктор": "Кондуктор", "направление": "Направление", "хвостовик": "Потайная колонна", "потайная колонна": "Потайная колонна"}
POINTS = {"ко": "Клапан-отсекатель", "цк": "Циркуляционный клапан", "пакер": "Пакер", "ик": "Ингибиторный клапан"}
INTERVALS = {"фильтр": "Фильтр", "расширка": "Расширка", "перфорация": "Интервал перфорации"}
DEPTH_LIMITED = ("Фильтр", "Интервал перфорации")      # порог глубины, как в своде скважин (#366)
LEVELS = ("ошибка", "предупреждение", "заметка")


@dataclass
class Issue:
    level: str
    code: str
    message: str
    well: str = ""
    source: str = ""


@dataclass
class Snapshot:
    well: str
    date: Optional[dt.date]
    source: str
    kit: str = ""                         # комплект оборудования («Ресурс-4»)
    resource: bool = False
    elements: List[dict] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    purpose: str = ""
    interval: Tuple[Optional[float], Optional[float]] = (None, None)
    note: str = ""
    bottom: Optional[float] = None         # текущий (отбитый) забой, м от стола
    artificial: Optional[float] = None     # искусственный забой (пробка), м от стола; в конструкцию попадает элементом «Искусственный забой»
    raw_cons: str = ""


@dataclass
class Result:
    path: str
    snapshots: List[Snapshot] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    excluded: List[dict] = field(default_factory=list)
    max_perf: Optional[float] = DEFAULT_MAX_PERF_DEPTH

    def add(self, level, code, message, well="", source=""):
        self.issues.append(Issue(level, code, message, well, source))


def num(text) -> Optional[float]:
    try:
        return float(str(text).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def parse_date(text) -> Optional[dt.date]:
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\b", text or "")
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y += 2000 if y < 100 else 0
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


# ---------------------------------------------------------------- чтение таблиц docx

def read_tables(path: str) -> List[List[List[str]]]:
    """Таблицы docx: строки → ячейки (текст, абзацы через перевод строки). Объединённые по горизонтали повторяются,
    продолжение вертикального объединения берёт текст верхней ячейки."""
    if not path.lower().endswith(".docx"):
        raise ValueError("Нужен файл .docx (для .doc сначала запустите «Конвертер форматов Office»): %s" % path)
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    tables = []
    for tbl in root.iter(W + "tbl"):
        rows, above = [], []
        for tr in tbl.findall(W + "tr"):
            cells = []
            for tc in tr.findall(W + "tc"):
                pr = tc.find(W + "tcPr")
                span, vm = 1, None
                if pr is not None:
                    gs = pr.find(W + "gridSpan")
                    span = int(gs.get(W + "val", "1")) if gs is not None else 1
                    vme = pr.find(W + "vMerge")
                    if vme is not None:
                        vm = vme.get(W + "val", "continue")
                paras = []
                for p in tc.findall(W + "p"):
                    buf = []
                    for el in p.iter():
                        if el.tag == W + "t":
                            buf.append(el.text or "")
                        elif el.tag == W + "tab":
                            buf.append(" ")
                        elif el.tag in (W + "br", W + "cr"):
                            buf.append("\n")
                    paras.append("".join(buf))
                text = "\n".join(paras).strip()
                idx = len(cells)
                if vm == "continue" and idx < len(above):
                    text = above[idx]
                cells.extend([text] * span)
            rows.append(cells)
            above = cells
        tables.append(rows)
    return tables


COLS = {"well": r"№\s*скв", "cons": r"конструкц", "date": r"дата", "kit": r"комплекс", "int": r"интервал", "note": r"примечан"}


def header_map(row: List[str]) -> Optional[Dict[str, int]]:
    found: Dict[str, int] = {}
    for i, text in enumerate(row):
        low = re.sub(r"\s+", " ", text.lower())
        for key, rx in COLS.items():
            if key not in found and re.search(rx, low):
                found[key] = i
    return found if {"well", "cons", "date"} <= set(found) else None


# ---------------------------------------------------------------- конструкция

def parse_construction(text: str, snap: Snapshot, res: Result) -> None:
    """Строки ячейки «Конструкция скважины»: колонны/НКТ с диаметром и глубиной, точечные узлы, интервалы, комплект «Ресурс»."""
    for raw in text.replace("\r", "").split("\n"):
        line = re.sub(r"\s+", " ", re.sub("[\ue000-\uf8ff]", " ", raw)).strip().rstrip(";")      # знак диаметра Ø приходит символом из частной области
        if not line:
            continue
        low = line.lower()
        if "ресурс" in low:
            snap.resource = True
            m = re.search(r"[«\"“]([^»\"”]+)[»\"”]", line)
            snap.kit = (m.group(1) if m else line.rstrip(":")).strip()
            continue
        if low.startswith("все глубины"):
            continue
        m = re.match(r"^(эк|э/к|нкт|тк|кондуктор|направление|хвостовик|потайная колонна)\s*(?:(%s)\s*мм)?\s*%s\s*(%s)\s*м?$" % (NUM, DASH, NUM), low)
        if m:
            snap.elements.append(el(STRINGS[m.group(1)], 0.0, num(m.group(3)), num(m.group(2)), line))
            continue
        m = re.match(r"^(ко|цк|пакер|ик)\b[^–—−\-]*%s\s*(%s)\s*м?$" % (DASH, NUM), low)
        if m:
            d = num(m.group(2))
            snap.elements.append(el(POINTS[m.group(1)], d, d, None, line))
            continue
        m = re.match(r"^(фильтр|расширка|перфорация)\b.*?%s\s*(%s)\s*%s\s*(%s)\s*м?" % (DASH, NUM, DASH, NUM), low)
        if m:
            snap.elements.append(el(INTERVALS[m.group(1)], num(m.group(2)), num(m.group(3)), None, line))
            continue
        m = re.match(r"^(искусственный |текущий )?забой\s*%s\s*(%s)\s*м?$" % (DASH, NUM), low)
        if m:
            d = num(m.group(2))
            artificial = bool(m.group(1)) and m.group(1).startswith("искусств")
            snap.elements.append(el("Искусственный забой" if artificial else "Забой", d, d, None, line))
            continue
        if re.match(r"^(расширка|фильтр)\s*%s?\s*$" % DASH, low):
            continue        # элемент назван без глубин
        res.add("предупреждение", "LINE", "Строка конструкции не разобрана: «%s»" % line, snap.well, snap.source)


def el(name, top, bottom, d, comment):
    if top is not None and bottom is not None and top > bottom:
        top, bottom = bottom, top
    return {"Элемент": name, "Верх": top, "Низ": bottom, "Диаметр": d if d and d > 0 else None, "Комментарий": comment}


# ---------------------------------------------------------------- методы и забой

def parse_methods(text: str, snap: Snapshot) -> None:
    """Графа «Выполненный комплекс ГИС»: короткие слова-аббревиатуры (ГК, НГК, ЛМ…) — методы, остальное — цель исследования."""
    methods, purpose = [], []
    for part in re.split(r"[\n,;]", text or ""):
        p = part.strip().strip(".")
        if not p:
            continue
        (methods if re.fullmatch(r"[А-ЯЁA-Z][А-ЯЁA-Z0-9/\-]{0,7}", p) else purpose).append(p)
    snap.methods, snap.purpose = methods, "; ".join(purpose)


def parse_interval(text: str, snap: Snapshot) -> None:
    m = re.search(r"(%s)\s*%s\s*(%s)" % (NUM, DASH, NUM), text or "")
    if m:
        snap.interval = (num(m.group(1)), num(m.group(2)))


def parse_bottom(text: str, snap: Snapshot) -> None:
    """«Текущий забой – N м» — отбитый забой; «Искусственный забой» — отдельная величина (см. parse_artificial)."""
    m = re.search(r"текущий\s+забой\s*%s?\s*(%s)\s*м" % (DASH, NUM), (text or "").lower())
    if m:
        snap.bottom = num(m.group(1))


def parse_artificial(text: str, snap: Snapshot) -> None:
    m = re.search(r"искусственный\s+забой\s*%s?\s*(%s)\s*м" % (DASH, NUM), (text or "").lower())
    if m:
        snap.artificial = num(m.group(1))


# ---------------------------------------------------------------- файл целиком

def well_key(text: str) -> str:
    m = re.match(r"\s*(\d+)\s*([А-Яа-яA-Za-z]?)\s*$", text or "")
    return (m.group(1) + m.group(2)) if m else ""


def read(path: str, max_perf: Optional[float] = DEFAULT_MAX_PERF_DEPTH, fix_years: bool = True) -> Result:
    res = Result(path, max_perf=max_perf if max_perf else None)
    cols: Optional[Dict[str, int]] = None
    seen = set()
    for t, rows in enumerate(read_tables(path), 1):
        for r, cells in enumerate(rows, 1):
            hm = header_map(cells)
            if hm:
                cols = hm
                continue
            if cols is None or len(cells) <= max(cols.values()):
                continue
            well = well_key(cells[cols["well"]])
            if not well:
                continue            # список скважин, пустые строки
            source = "таблица %d, строка %d" % (t, r)
            date = parse_date(cells[cols["date"]])
            snap = Snapshot(well, date, source, raw_cons=cells[cols["cons"]])
            if date is None:
                res.add("предупреждение", "DATE", "Нет даты исследования: конструкция без даты", well, source)
            parse_construction(cells[cols["cons"]], snap, res)
            if "kit" in cols:
                parse_methods(cells[cols["kit"]], snap)
            if "int" in cols:
                parse_interval(cells[cols["int"]], snap)
            if "note" in cols:
                snap.note = cells[cols["note"]].strip()
                parse_bottom(snap.note, snap)
                parse_artificial(snap.note, snap)
                if snap.artificial is not None and not any(e["Элемент"] == "Искусственный забой" for e in snap.elements):
                    snap.elements.append(el("Искусственный забой", snap.artificial, snap.artificial, None, "из примечания: " + snap.note.strip()))
            if not snap.elements:
                res.add("предупреждение", "EMPTY", "В строке не найдено ни одного элемента конструкции", well, source)
            keep = []
            for e in snap.elements:
                if res.max_perf and e["Элемент"] in DEPTH_LIMITED and e["Низ"] is not None and e["Низ"] > res.max_perf:
                    res.excluded.append(dict(e, Скважина=well, Дата=date, Источник=source,
                                             Причина="глубже порога %g м: похоже на ошибку в перечне; вернуть можно вручную" % res.max_perf))
                else:
                    keep.append(e)
            snap.elements = keep
            if snap.bottom is None and "note" in cols:
                res.add("заметка", "BOTTOM", "В примечании нет «Текущий забой – … м»", well, source)
            key = (well, date, snap.raw_cons.strip())
            if key in seen:
                res.add("заметка", "DUP", "Повтор строки той же скважины на ту же дату с той же конструкцией", well, source)
            seen.add(key)
            res.snapshots.append(snap)
    if not res.snapshots:
        raise ValueError("В файле не найдено таблицы с графами «№ скв», «Конструкция», «Дата»")
    if fix_years:
        fix_year_typos(res)
    res.snapshots.sort(key=lambda s: (_wk(s.well), s.date or dt.date.min))
    return res


MIN_YEAR = 1990


def year_candidates(year: int, max_year: int) -> List[int]:
    """Годы из перестановки цифр опечатки, попадающие в [MIN_YEAR, max_year]: 2091 → 2019."""
    from itertools import permutations
    digits = str(year)
    return sorted({int("".join(p)) for p in permutations(digits) if MIN_YEAR <= int("".join(p)) <= max_year} - {year})


def fix_year_typos(res: Result, today: Optional[dt.date] = None) -> None:
    """Даты с невозможным годом (2091 вместо 2019, раньше 1990 или позже текущего года) исправляются перестановкой цифр. Однозначный вариант применяется,
    из нескольких берётся ближайший к годам других снимков той же скважины; каждое исправление — предупреждение в «Проверке» (подсказка: верна ли замена, решает инженер).
    Не нашлось варианта — дата не меняется, остаётся предупреждение."""
    max_year = (today or dt.date.today()).year
    for s in res.snapshots:
        if s.date is None or MIN_YEAR <= s.date.year <= max_year:
            continue
        near = [o.date.year for o in res.snapshots if o.well == s.well and o.date and MIN_YEAR <= o.date.year <= max_year]
        cands = year_candidates(s.date.year, max_year)
        if not cands:
            res.add("предупреждение", "YEAR", "Год %d похож на опечатку, подходящей замены нет: дата оставлена как есть" % s.date.year, s.well, s.source)
            continue
        new = min(cands, key=lambda y: (min((abs(y - n) for n in near), default=0), y)) if len(cands) > 1 else cands[0]
        try:
            fixed = s.date.replace(year=new)
        except ValueError:                      # 29 февраля
            fixed = s.date.replace(year=new, day=28)
        res.add("предупреждение", "YEAR", "Опечатка в годе: %s → %s (перестановка цифр%s). Проверьте" % (
            s.date.strftime("%d.%m.%Y"), fixed.strftime("%d.%m.%Y"), "; вариантов несколько, взят ближайший к другим датам скважины" if len(cands) > 1 else ""), s.well, s.source)
        s.date = fixed


def _wk(well: str):
    m = re.match(r"(\d+)(.*)", well)
    return (int(m.group(1)), m.group(2)) if m else (10 ** 9, well)


# ---------------------------------------------------------------- таблицы

def signature(s: Snapshot) -> tuple:
    return tuple(sorted((e["Элемент"], e["Верх"], e["Низ"], e["Диаметр"]) for e in s.elements))


def cons_table(res: Result) -> pd.DataFrame:
    rows = []
    for s in res.snapshots:
        for e in s.elements:
            rows.append([s.well, s.date, e["Элемент"], e["Верх"], e["Низ"], e["Диаметр"], None, e["Комментарий"], s.kit,
                         "Да" if s.resource else "", s.source])
    return pd.DataFrame(rows, columns=CONS_COLUMNS)


def bottom_table(res: Result) -> pd.DataFrame:
    rows = [[s.well, s.date, s.bottom, None, ", ".join(s.methods), "MD, от стола ротора; " + s.source]
            for s in res.snapshots if s.bottom is not None]
    return pd.DataFrame(rows, columns=BOTTOM_COLUMNS)


def methods_table(res: Result) -> pd.DataFrame:
    rows = [[s.well, s.date, ", ".join(s.methods), s.purpose, s.interval[0], s.interval[1], s.note, s.source] for s in res.snapshots]
    return pd.DataFrame(rows, columns=METHOD_COLUMNS)


def changes_table(res: Result) -> pd.DataFrame:
    """Что изменилось между соседними снимками одной скважины: без изменений / частично (какие элементы) / заменена целиком."""
    rows, prev = [], {}
    for s in res.snapshots:
        p = prev.get(s.well)
        if p is None:
            kind, what = "первая", ""
        else:
            a, b = set(signature(p)), set(signature(s))
            if a == b:
                kind, what = "без изменений", ""
            else:
                names = sorted({x[0] for x in a ^ b})
                kind = "заменена целиком" if len(a & b) == 0 else "частично"
                what = ", ".join(names)
        rows.append([s.well, p.date if p else None, s.date, kind, what, "Да" if s.resource else ""])
        prev[s.well] = s
    return pd.DataFrame(rows, columns=["Скважина", "Предыдущая дата", "Дата", "Изменение", "Что изменилось", "Ресурс"])


def wells_table(res: Result) -> pd.DataFrame:
    rows, by = [], {}
    for s in res.snapshots:
        by.setdefault(s.well, []).append(s)
    for w, ss in by.items():
        dated = [s for s in ss if s.date]
        last = max(dated, key=lambda s: s.date) if dated else ss[-1]
        bottoms = [s for s in dated if s.bottom is not None]
        lb = max(bottoms, key=lambda s: s.date) if bottoms else None
        rows.append([w, len(ss), last.date, lb.bottom if lb else None, lb.date if lb else None,
                     "Да" if any(s.resource for s in ss) else "", ", ".join(sorted({s.kit for s in ss if s.kit}))])
    return pd.DataFrame(rows, columns=["Скважина", "Снимков", "Последняя конструкция", "Текущий забой, м (MD)", "Дата забоя", "Ресурс", "Комплекты"])


def resource_table(res: Result) -> pd.DataFrame:
    rows = [[s.well, s.date, s.kit, s.source] for s in res.snapshots if s.resource]
    return pd.DataFrame(rows, columns=["Скважина", "Дата", "Пометка", "Источник"])


def issues_table(res: Result) -> pd.DataFrame:
    rows = [[i.level, i.code, i.well, i.source, i.message] for i in sorted(res.issues, key=lambda i: LEVELS.index(i.level))]
    return pd.DataFrame(rows, columns=["Уровень", "Код", "Скважина", "Источник", "Сообщение"])


def excluded_table(res: Result) -> pd.DataFrame:
    cols = ["Скважина", "Дата", "Элемент", "Верх", "Низ", "Источник", "Причина"]
    return pd.DataFrame([[e[c] for c in cols] for e in res.excluded], columns=cols)


def _write(path: str, sheets) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets:
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for i, col in enumerate(df.columns, 1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(width, 60)


def export(res: Result, out_dir: str) -> List[str]:
    """Два файла: для загрузки в Атлас («Конструкция», «Замеры забоя» с методами) и разбор для инженера (остальные листы)."""
    import os
    atlas = os.path.join(out_dir, OUT_FILE)
    report = os.path.join(out_dir, REPORT_FILE)
    _write(atlas, [("Конструкция", cons_table(res)), ("Замеры забоя", bottom_table(res))])
    _write(report, [("Методы исследований", methods_table(res)), ("Скважины", wells_table(res)), ("Ресурс", resource_table(res)),
                    ("Изменения", changes_table(res)), ("Исключено", excluded_table(res)), ("Проверка", issues_table(res))])
    return [atlas, report]
