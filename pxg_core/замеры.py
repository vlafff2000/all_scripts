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
          ("level", ("нст", "уровень")), ("p_res", ("рпл", "пластов")), ("group", ("гсп", "групп")))

COLUMNS = ["Скважина", "Дата", "Горизонт", "Категория", "Руст", "Избыточное давление", "Рпл", "Уровень жидкости",
           "Примечание", "Источник", "L", "ES", "Плотность воды", "ГСП"]

# Группа (ГСП) эксплуатационных скважин, если в строке файла её нет: ЭЛПРО-файлы 2022–2025 и исходная база давлений
# (проверено 2026-10-15). Скважины 127 в ЭЛПРО нет — группа пустая, её надо указать.
WELL_GROUPS = {56: "ГСП-1", 83: "ГСП-2", 182: "ГСП-3", 220: "ГСП-3", 237: "ГСП-4", 264: "ГСП-5", 437: "ГСП-8", 520: "ГСП-9"}
_GROUP_RE = re.compile(r"ГСП\s*-?\s*(\d+)", re.IGNORECASE)


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
    length: Optional[float] = None      # «L» в старых шаблонах (глубина замера, м)
    es: Optional[float] = None          # «ES» в старых шаблонах
    density: Optional[float] = None     # «плотность» воды, г/см³: считается и сравнивается с кодом пересчёта
    sheet: str = ""
    row: int = 0
    raw: Dict[str, object] = field(default_factory=dict)
    group: str = ""                     # «ГСП-N» из строки или из справочника скважин (только эксплуатационные)


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


_LATIN = str.maketrans("PpHhCcTtXxAaBbEeKkMmOo", "РрНнСсТтХхАаВвЕеКкМмОо")   # в старых файлах «Pуст», «Hст», «Pпл» набраны латиницей


def _field_of(header: str) -> str:
    plain = " ".join(header.split()).lower().rstrip(",.")
    if plain == "l":
        return "length"
    if plain == "es":
        return "es"
    if plain.replace(" ", "").startswith("плот"):
        return "density"
    low = header.translate(_LATIN).lower().replace("\n", " ")
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


def group_name(text) -> str:
    """Название группы в единой схеме: «ГСП 1», «гсп-1», «ГСП1» → «ГСП-1»; без номера — пусто."""
    m = _GROUP_RE.search(_text(text))
    return "ГСП-%d" % int(m.group(1)) if m else ""


def _well_number(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and not pd.isna(v) and float(v) == int(v):
        return int(v)
    m = re.match(r"^\s*(\d+)\s*(?:[,;/]|$)", str(v)) if v is not None else None
    return int(m.group(1)) if m else None


def _combined_wells(v) -> List[int]:
    """«54/80», «54;80» → [54, 80]; одиночный номер и не строка → пусто (обрабатывается как обычно)."""
    if not isinstance(v, str):
        return []
    m = re.match(r"^\s*(\d+)\s*[/;]\s*(\d+)\s*$", v)
    return [int(m.group(1)), int(m.group(2))] if m else []


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
                # первая таблица захватывает и столбцы левее своей шапки: подпись раздела в старых файлах стоит в столбце A
                start = 0 if b == 0 else block.get("num", cols[0])
                span = range(start, cols[-1] + 1)
                texts = [row[c] for c in span if c < len(row) and row[c]]
                well = _well_number(values[i][block["well"]]) if block["well"] < len(values[i]) else None
                title = _category(" ".join(texts)) if texts else ""
                if title and (well is None or not any(_well_number(values[i][c]) for c in cols if c < len(values[i]))):
                    sections = [title] * len(blocks)     # подпись раздела относится ко всем таблицам листа
                    break
                if well is None:
                    num = values[i][block["num"]] if "num" in block and block["num"] < len(values[i]) else None
                    if texts and isinstance(num, (int, float)) and not pd.isna(num):
                        out.problems.append(("WELL", "Строка таблицы без номера скважины: «%s»" % "; ".join(texts)[:80],
                                             "%s, лист %s, строка %d" % (src, sheet, i + 1)))
                    continue
                raw_well = values[i][block["well"]] if block["well"] < len(values[i]) else None
                parts = _combined_wells(raw_well)
                if len(parts) > 1:      # «54/80»: один замер на двух скважинах — запись на каждую
                    out.problems.append(("WELL", "Объединённая скважина «%s»: замер записан на каждую (%s)"
                                         % (str(raw_well).strip(), ", ".join(map(str, parts))),
                                         "%s, лист %s, строка %d" % (src, sheet, i + 1)))
                for w in parts if len(parts) > 1 else [well]:
                    out.rows.append(_row(values[i], block, w, sections[b], src, sheet, i + 1, excess_limit))
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
    extra = {name: qc.to_number(cell(name))[0] for name in ("length", "es", "density")}
    group = group_name(cell("group")) or (WELL_GROUPS.get(well, "") if category == "Эксплуатационные" else "")
    return Row(well, category, _text(cell("layer")), date, p_wh, excess, nums["p_res"], nums["level"], "; ".join(notes),
               src, extra["length"], extra["es"], extra["density"], sheet, rownum,
               {"p_wh": cell("p_wh"), "p_res": cell("p_res"), "level": cell("level"), "date": raw_date}, group)


def parse_weekly(path: str) -> Parsed:
    """«Итоговая таблица 2006–2026»: еженедельные замеры эксплуатационных скважин, Руст и Рпл по датам.

    Формат: столбец A — дата; дальше пары столбцов «Р устье» / «Р пл.» под заголовком «Скв.№ NNN»; последний
    столбец «Р среднее по ПХГ» читает `pc.read_average` (пересчёт давлений), здесь не нужен. Логика чтения перенесена
    из модуля «Итоговая таблица давлений 2006–2025» без изменений в разборе.
    """
    out = Parsed()
    src = os.path.basename(path)
    try:
        sheets = _read(path)
    except Exception as e:
        out.problems.append(("FILE", "Книга не открывается: %s" % str(e)[:200], src))
        return out
    if not sheets:
        out.problems.append(("HEADER", "Книга пустая", src))
        return out
    sheet, df = next(iter(sheets.items()))
    cells = [[_text(v) for v in r] for r in df.itertuples(index=False, name=None)]
    values = df.values.tolist()
    head = cells[0] if cells else []
    sub = cells[1] if len(cells) > 1 else []
    wells: List[Tuple[int, int, int]] = []          # (номер скважины, столбец Руст, столбец Рпл)
    for col, text in enumerate(head):
        m = re.search(r"(\d+)", text) if re.search("скв", text, re.IGNORECASE) else None
        if m and col + 1 < len(sub) and "пл" in sub[col + 1].lower():
            wells.append((int(m.group(1)), col, col + 1))
    if not wells:
        out.problems.append(("HEADER", "Скважины не найдены: нет шапки «Скв.№ …» с парами «Р устье» / «Р пл.»", src))
        return out
    out.tables = len(wells)
    for i in range(2, len(values)):
        date = qc.parse_date(values[i][0])
        if date is None:
            if cells[i][0]:
                out.problems.append(("DATE", "Дата не распознана: «%s»" % cells[i][0][:40], "%s, строка %d" % (src, i + 1)))
            continue
        for well, c_wh, c_res in wells:
            notes: List[str] = []
            nums: Dict[str, Optional[float]] = {}
            for name, c, label in (("p_wh", c_wh, "Руст"), ("p_res", c_res, "Рпл")):
                v = values[i][c] if c < len(values[i]) else None
                num, kind = qc.to_number(v)
                if kind in ("text", "excel"):
                    notes.append("%s: %s" % (label, _text(v)))
                    num = None
                nums[name] = num
            if nums["p_wh"] is None and nums["p_res"] is None:
                continue
            out.rows.append(Row(well, "Эксплуатационные", "", date, nums["p_wh"], None, nums["p_res"], None,
                                "; ".join(notes), src, sheet=sheet, row=i + 1, group=WELL_GROUPS.get(well, "")))
    if not out.rows:
        out.problems.append(("HEADER", "Замеров по скважинам не найдено", src))
    return out


def to_frame(rows: List[Row]) -> pd.DataFrame:
    return pd.DataFrame([[r.well, r.date, r.layer, r.category, r.p_wh, r.excess, r.p_res, r.level, r.note, r.source,
                          r.length, r.es, r.density, r.group] for r in rows], columns=COLUMNS)


def combine(frames: List[Optional[pd.DataFrame]], fill: bool = True, whole_rows: bool = False) -> pd.DataFrame:
    """Объединение источников в одну базу без дублей.

    Порядок `frames` — приоритет: при одном ключе (скважина, день, горизонт) берётся значение из более раннего источника,
    пустые поля дополняются из следующих. Горизонт сначала дополняется по скважине (`fill_layers`), иначе строка
    без горизонта не совпала бы с той же строкой из месячного файла. Строки без даты — по скважине и источнику.
    Счётчики: attrs["replaced"] — строк, слитых с другими (дубли), attrs["layer_*"] — см. `fill_layers`.
    """
    parts = []
    for rank, f in enumerate(frames):
        if f is None or f.empty:
            continue
        g = f.copy()
        for col in COLUMNS:
            if col not in g.columns:
                g[col] = None
        g = g[COLUMNS].copy()
        g["_rank"] = rank
        parts.append(g)
    if not parts:
        out = pd.DataFrame(columns=COLUMNS)
        out.attrs["replaced"] = 0
        return out
    out = pd.concat(parts, ignore_index=True)
    out["Дата"] = pd.to_datetime(out["Дата"], errors="coerce")
    for col in ("Горизонт", "Примечание", "ГСП"):
        out[col] = out[col].where(~_blank(out[col]), None)
    layer_attrs: Dict[str, int] = {}
    if fill:
        out = fill_layers(out)
        layer_attrs = {k: v for k, v in out.attrs.items() if k.startswith("layer_")}
    key = out["Дата"].dt.strftime("%Y-%m-%d").fillna("без даты:" + out["Источник"].astype(str))
    out["_k"] = out["Скважина"].astype(str) + "|" + key + "|" + out["Горизонт"].fillna("").astype(str).str.strip()
    before = len(out)
    out = out.sort_values("_rank", kind="stable")
    if whole_rows:      # прежнее поведение: побеждает вся строка приоритетного источника
        out = out.drop_duplicates("_k", keep="first")
    else:               # пустые поля дополняются из следующих источников
        out = out.groupby("_k", sort=False).first().reset_index()
    out = out[COLUMNS]
    out = out.sort_values(["Скважина", "Дата"], na_position="last").reset_index(drop=True)
    out.attrs["replaced"] = before - len(out)
    out.attrs.update(layer_attrs)
    return out


def merge(old: Optional[pd.DataFrame], new: pd.DataFrame) -> pd.DataFrame:
    """Новые строки целиком заменяют старые с тем же ключом (скважина + дата + горизонт), как и раньше."""
    return combine([new, old], fill=False, whole_rows=True)


def _blank(s: pd.Series) -> pd.Series:
    return s.isna() | s.astype(str).str.strip().eq("")


def fill_layers(data: pd.DataFrame) -> pd.DataFrame:
    """Горизонт в строках, где он не проставлен, — по скважине из самых поздних замеров (шаблон последнего года).

    Горизонт — свойство скважины, поэтому соответствие «скважина → горизонт» из файла последнего года распространяется
    на пустые строки остальных лет. Уже проставленный горизонт не переписывается: расхождения считаются в attrs.
    """
    out = data.copy()
    blank = _blank(out["Горизонт"])
    known = out[~blank].assign(_d=pd.to_datetime(out.loc[~blank, "Дата"], errors="coerce"))
    known = known.sort_values("_d", ascending=False, na_position="last", kind="stable")
    ref = known.drop_duplicates("Скважина").set_index("Скважина")["Горизонт"]
    mapped = out["Скважина"].map(ref)
    if blank.any():
        out.loc[blank, "Горизонт"] = mapped[blank].fillna("")
    still = _blank(out["Горизонт"])
    conflict = ~blank & mapped.notna() & (out["Горизонт"].astype(str).str.strip() != mapped.astype(str).str.strip())
    out.attrs["layer_filled"] = int(blank.sum() - still.sum())
    out.attrs["layer_unresolved"] = int(still.sum())
    out.attrs["layer_conflicts"] = int(conflict.sum())
    return out


def by_month(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Скважины по строкам, месяцы по столбцам (последний замер месяца)."""
    d = df.dropna(subset=["Дата", column]).copy()
    if d.empty:
        return pd.DataFrame()
    d["Месяц"] = d["Дата"].dt.strftime("%Y-%m")
    d = d.sort_values("Дата").drop_duplicates(["Скважина", "Месяц"], keep="last")
    return d.pivot(index="Скважина", columns="Месяц", values=column).sort_index(axis=1)
