"""Разбор месячных файлов «Результаты замеров по скважинам»: две таблицы рядом, разделы скважин, три замерные величины.

Формат образца (Касимовское ПХГ): в шапке «№№ п/п | №№ скв, категория | Пласт | Дата замера | Руст, кгс/см2 | Нст, м | Рпл, кгс/см2»,
таблица повторяется справа; разделы «Эксплуатационные», «Наблюдательные», «Контрольные», «Поглотительные» идут строкой-заголовком.
Общий код для модуля «База давлений по замерам» и его проверки исходников.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import qc

CATEGORIES = (("эксплуат", "Эксплуатационные"), ("наблюд", "Наблюдательные"), ("контрол", "Контрольные"),
              ("поглот", "Поглотительные"))
# Категории, у которых малое значение Руст — избыточное давление, а не рабочее устьевое
NON_EXPLOIT = ("Наблюдательные", "Контрольные", "Поглотительные")
EXCESS_LIMIT = 20.0   # кгс/см²: Руст ниже этого у скважин не эксплуатационной категории считается избыточным давлением

FIELDS = (("well", ("скв",)), ("layer", ("пласт", "горизонт")), ("date", ("дата",)), ("p_wh", ("руст", "устьев")),
          ("level", ("нст", "уровень")), ("p_res", ("рпл", "пластов")))

COLUMNS = ["Скважина", "Дата", "Горизонт", "Категория", "Руст", "Избыточное давление", "Рпл", "Уровень жидкости",
           "Примечание", "Источник"]


@dataclass
class Row:
    well: int
    category: str
    layer: str
    date: Optional[datetime]
    p_wh: Optional[float]
    excess: Optional[float]
    p_res: Optional[float]
    level: Optional[float]
    note: str
    source: str
    sheet: str = ""
    row: int = 0
    raw: Dict[str, object] = field(default_factory=dict)


@dataclass
class Parsed:
    rows: List[Row] = field(default_factory=list)
    problems: List[Tuple[str, str, str]] = field(default_factory=list)   # (код, текст, где)
    title: str = ""
    tables: int = 0


def _text(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _category(text: str) -> str:
    low = text.lower()
    for key, name in CATEGORIES:
        if key in low:
            return name
    return ""


def _field_of(header: str) -> str:
    low = header.lower().replace("\n", " ")
    if "п/п" in low:
        return "num"
    for name, keys in FIELDS:
        if any(k in low for k in keys):
            return name
    return ""


def _blocks(header_cells: List[str]) -> List[Dict[str, int]]:
    """Таблицы в строке шапки: поле -> номер столбца; новая таблица начинается с «№№ п/п» или повторного поля."""
    blocks: List[Dict[str, int]] = []
    cur: Dict[str, int] = {}
    for col, head in enumerate(header_cells):
        f = _field_of(head)
        if not f:
            continue
        if f == "num" or f in cur:
            if cur:
                blocks.append(cur)
            cur = {}
        cur[f] = col
    if cur:
        blocks.append(cur)
    return [b for b in blocks if "well" in b and ("p_wh" in b or "level" in b or "p_res" in b)]


def _well_number(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and not pd.isna(v) and float(v) == int(v):
        return int(v)
    m = re.match(r"^\s*(\d+)\s*(?:[,;/]|$)", str(v)) if v is not None else None
    return int(m.group(1)) if m else None


def _read(path: str) -> Dict[str, pd.DataFrame]:
    from .расходы_файлы import excel_engines
    last: Optional[Exception] = None
    for engine in excel_engines(path):
        try:
            return pd.read_excel(path, sheet_name=None, header=None, engine=engine)
        except Exception as e:   # другой движок может открыть
            last = e
    raise last or RuntimeError("нет движка чтения")


def parse_file(path: str, excess_limit: float = EXCESS_LIMIT) -> Parsed:
    """Строки замеров из одного файла. Всё, что не удалось разобрать, — в problems, а не молча."""
    out = Parsed()
    src = os.path.basename(path)
    try:
        sheets = _read(path)
    except Exception as e:
        out.problems.append(("FILE", "Книга не открывается: %s" % str(e)[:200], src))
        return out
    for sheet, df in sheets.items():
        cells = [[_text(v) for v in r] for r in df.itertuples(index=False, name=None)]
        values = df.values.tolist()
        blocks: List[Dict[str, int]] = []
        sections: List[str] = []
        for i, row in enumerate(cells):
            if not out.title and any("результаты замеров" in c.lower() for c in row if c):
                out.title = next(c for c in row if "результаты замеров" in c.lower())
            found = _blocks(row) if sum(1 for c in row if c) >= 3 else []
            if found and any("дат" in c.lower() for c in row):
                blocks, sections = found, [""] * len(found)
                out.tables += len(found)
                continue
            if not blocks:
                continue
            for b, block in enumerate(blocks):
                cols = sorted(block.values())
                span = range(block.get("num", cols[0]), cols[-1] + 1)
                texts = [row[c] for c in span if c < len(row) and row[c]]
                well = _well_number(values[i][block["well"]]) if block["well"] < len(values[i]) else None
                title = _category(" ".join(texts)) if texts else ""
                if title and (well is None or not any(_well_number(values[i][c]) for c in cols if c < len(values[i]))):
                    sections[b] = title
                    continue
                if well is None:
                    num = values[i][block["num"]] if "num" in block and block["num"] < len(values[i]) else None
                    if texts and isinstance(num, (int, float)) and not pd.isna(num):
                        out.problems.append(("WELL", "Строка таблицы без номера скважины: «%s»" % "; ".join(texts)[:80],
                                             "%s, лист %s, строка %d" % (src, sheet, i + 1)))
                    continue
                raw_well = values[i][block["well"]] if block["well"] < len(values[i]) else None
                if isinstance(raw_well, str) and re.search(r"\d+\s*[/;]\s*\d+", raw_well):
                    out.problems.append(("WELL", "Объединённая скважина «%s»: замер записан на %d, а не на обе" % (raw_well.strip(), well),
                                         "%s, лист %s, строка %d" % (src, sheet, i + 1)))
                out.rows.append(_row(values[i], block, well, sections[b], src, sheet, i + 1, excess_limit))
    if not out.rows:
        out.problems.append(("HEADER", "Таблицы замеров не найдены: нет шапки с «Дата замера» и «Руст/Нст/Рпл»", src))
    return out


def _row(vals, block, well, category, src, sheet, rownum, excess_limit) -> Row:
    def cell(name):
        c = block.get(name)
        return vals[c] if c is not None and c < len(vals) else None

    notes: List[str] = []
    nums: Dict[str, Optional[float]] = {}
    for name, label in (("p_wh", "Руст"), ("p_res", "Рпл"), ("level", "Нст")):
        v = cell(name)
        num, kind = qc.to_number(v)
        if kind in ("text", "excel"):
            notes.append("%s: %s" % (label, _text(v)))
            num = None
        nums[name] = num
    raw_date = cell("date")
    date = qc.parse_date(raw_date)
    if date is None and _text(raw_date):
        notes.append("Дата: %s" % _text(raw_date))
    p_wh, excess = nums["p_wh"], None
    if p_wh is not None and category in NON_EXPLOIT and p_wh < excess_limit:
        p_wh, excess = None, nums["p_wh"]
    return Row(well, category, _text(cell("layer")), date, p_wh, excess, nums["p_res"], nums["level"], "; ".join(notes),
               src, sheet, rownum,
               {"p_wh": cell("p_wh"), "p_res": cell("p_res"), "level": cell("level"), "date": raw_date})


def to_frame(rows: List[Row]) -> pd.DataFrame:
    return pd.DataFrame([[r.well, r.date, r.layer, r.category, r.p_wh, r.excess, r.p_res, r.level, r.note, r.source]
                         for r in rows], columns=COLUMNS)


def merge(old: Optional[pd.DataFrame], new: pd.DataFrame) -> pd.DataFrame:
    """Новые строки заменяют старые с тем же ключом (скважина + дата + горизонт); строки без даты — по скважине и источнику."""
    if old is None or old.empty:
        out = new.copy()
    else:
        old = old.copy()
        for col in COLUMNS:
            if col not in old.columns:
                old[col] = None
        out = pd.concat([old[COLUMNS], new[COLUMNS]], ignore_index=True)
    out["Дата"] = pd.to_datetime(out["Дата"], errors="coerce")
    key = out["Дата"].dt.strftime("%Y-%m-%d").fillna("без даты:" + out["Источник"].astype(str))
    out["_k"] = out["Скважина"].astype(str) + "|" + key + "|" + out["Горизонт"].astype(str)
    before = len(out)
    out = out.drop_duplicates("_k", keep="last").drop(columns="_k")
    out = out.sort_values(["Скважина", "Дата"], na_position="last").reset_index(drop=True)
    out.attrs["replaced"] = before - len(out)      # сколько строк с тем же ключом заменено новыми (или совпало)
    return out


def by_month(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Скважины по строкам, месяцы по столбцам (последний замер месяца)."""
    d = df.dropna(subset=["Дата", column]).copy()
    if d.empty:
        return pd.DataFrame()
    d["Месяц"] = d["Дата"].dt.strftime("%Y-%m")
    d = d.sort_values("Дата").drop_duplicates(["Скважина", "Месяц"], keep="last")
    return d.pivot(index="Скважина", columns="Месяц", values=column).sort_index(axis=1)
