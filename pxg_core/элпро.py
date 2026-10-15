"""Разбор файлов ЭЛПРО «Параметры работы ГСП (за месяц)» в одну длинную таблицу.

Три вида файлов, все с расширением .xlsx:
- SpreadsheetML 2003 (XML, открывается не openpyxl): ГСП-1,2,3 и ГСП-8 в одном файле, блоки «Скважина» по группам;
- настоящий xlsx «Month_ГГГГММДД_GSPn_Lift|Pump»: одна группа, давления в кПа, Q подписан м3/ч;
- те же xlsx для закачки (Pump).

Каждый день — блок из пяти столбцов: P газа, T газа, Y кру, Q газа, «В работе». Режим (отбор/закачка) берётся из
шапки блока. Прочерк «-» — нет данных (пропуск), ноль — простой. Единицы приводятся к кгс/см² и тыс. м³/сут.
"""
from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

KPA_PER_KGF = 98.0665          # 1 кгс/см² в кПа
SS = "{urn:schemas-microsoft-com:office:spreadsheet}"
BLOCK = 5                      # P, T, Y, Q, В работе
COLUMNS = ["Дата", "Режим", "ГСП", "Скважина", "№ п/п", "Начало сезона", "P газа, кгс/см²", "T газа, °C",
           "Y кру, %", "Q газа, тыс. м³/сут", "В работе, ч", "Файл"]
# «№ п/п» входит в ключ: в файлах ЭЛПРО один номер скважины может стоять в двух строках (разные значения)
KEY = ["Дата", "ГСП", "Скважина", "Режим", "№ п/п"]

_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_MONTH_RE = re.compile(r"(20\d{2})_?(\d{2})")
_GSP_FILE_RE = re.compile(r"GSP\s*(\d+)", re.I)
_GSP_LABEL_RE = re.compile(r"^ГСП\s*-?\s*(\d+)$")
_GSP_TITLE_RE = re.compile(r"ГСП\s*-\s*(\d+)")
_MODE_RE = re.compile(r"(отбор|закачк)", re.I)


@dataclass
class FileInfo:
    """Сведения о разобранном файле: для статистики и сверки покрытия."""
    name: str
    fmt: str                                   # «XML» (SpreadsheetML) или «xlsx»
    month: Optional[date] = None               # месяц отчёта по имени файла
    groups: List[str] = field(default_factory=list)
    rows: int = 0
    wells: int = 0
    empty: int = 0                             # строки «скважина × день» без единого значения (прочерки)
    blocks: int = 0                            # дни в шапках (0 — файл не ЭЛПРО)
    outside: int = 0                           # строки за дни следующего месяца (блок 31-го дня и т. п.), не загружены
    range_bad: int = 0                         # значения вне допустимого диапазона, заменены пропуском
    q_unit: str = ""                           # «m3» — Q подписан м3/ч (принято как м³ за сутки)
    warnings: List[str] = field(default_factory=list)


# ---------- чтение сетки ячеек ----------

def _grids_xml(path: str) -> List[Tuple[str, List[list]]]:
    root = ET.parse(path).getroot()
    out = []
    for ws in root.iter(SS + "Worksheet"):
        grid: List[list] = []
        table = ws.find(SS + "Table")
        if table is None:
            continue
        for r in table.findall(SS + "Row"):
            ri = r.get(SS + "Index")
            if ri:
                while len(grid) < int(ri) - 1:
                    grid.append([])
            cells: list = []
            for c in r.findall(SS + "Cell"):
                ci = c.get(SS + "Index")
                if ci:
                    while len(cells) < int(ci) - 1:
                        cells.append(None)
                d = c.find(SS + "Data")
                cells.append(None if d is None else (d.text or "").strip())
                for _ in range(int(c.get(SS + "MergeAcross") or 0)):
                    cells.append("")
            grid.append(cells)
        out.append((ws.get(SS + "Name") or "", grid))
    return out


def _grids_xlsx(path: str) -> List[Tuple[str, List[list]]]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    finally:
        wb.close()


def read_grids(path: str) -> Tuple[str, List[Tuple[str, List[list]]]]:
    """Возвращает (формат, [(лист, сетка)]). Формат узнаётся по содержимому, не по расширению."""
    with open(path, "rb") as f:
        head = f.read(64)
    if head[:2] == b"PK":
        return "xlsx", _grids_xlsx(path)
    if b"<" in head:
        return "XML", _grids_xml(path)
    raise ValueError("неизвестный формат файла")


# ---------- разбор ----------

def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _num(v) -> float:
    """Число или NaN. «-», пусто и текст ошибок («#DIV/0!») — пропуск."""
    if isinstance(v, bool):
        return np.nan
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().replace(",", "."))
        except ValueError:
            return np.nan
    return np.nan


def _as_date(v) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        m = _DATE_RE.search(v)
        if m:
            try:
                return date(int(m[3]), int(m[2]), int(m[1]))
            except ValueError:
                return None
    return None


def _well(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and float(v).is_integer():
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\d+(\.0+)?", v.strip()):
        return int(float(v))
    return None


def _name_month(name: str) -> Optional[date]:
    m = _MONTH_RE.search(name)
    return date(int(m[1]), int(m[2]), 1) if m else None


def _blocks(header: list) -> List[Tuple[int, date, Optional[str]]]:
    """Дни шапки: (столбец начала блока, дата, режим). Блоки идут подряд через BLOCK столбцов."""
    out = []
    for j in range(2, len(header)):
        d = _as_date(header[j])
        if d is None:
            continue
        cells = " ".join(_text(x) for x in header[j:j + BLOCK])
        m = _MODE_RE.search(cells)
        mode = None
        if m:
            mode = "Отбор" if m[1].lower().startswith("отбор") else "Закачка"
        out.append((j, d, mode))
    return out


def _parse_grid(sheet: str, grid: List[list], info: FileInfo, default_group: Optional[str],
                unit_p: str, unit_q: str) -> List[dict]:
    recs: List[dict] = []
    group = default_group
    blocks: List[Tuple[int, date, Optional[str]]] = []
    active = False
    seen_blocks = 0
    season: Optional[date] = None
    season_mode: Optional[str] = None
    for row in grid:
        c0 = _text(row[0]) if row else ""
        if not row:
            continue
        if c0 in ("Скважина", "Время"):
            blocks = _blocks(row)
            active = bool(blocks)
            seen_blocks += len(blocks)
            if not blocks:
                info.warnings.append("%s: шапка без дат, блок пропущен" % sheet)
            continue
        if re.search(r"(Сезон работы|Начало сезона)", " ".join(_text(x) for x in row[:7])):
            for x in row[:8]:
                d = _as_date(x)
                if d and season is None:
                    season = d
                if isinstance(x, str) and _MODE_RE.search(x) and season_mode is None:
                    season_mode = "Отбор" if x.lower().find("отбор") >= 0 else "Закачка"
            continue
        if re.search(r"Режим работы", " ".join(_text(x) for x in row[:7])):
            for x in row[:8]:
                if isinstance(x, str) and _MODE_RE.search(x):
                    season_mode = "Отбор" if x.lower().find("отбор") >= 0 else "Закачка"
            continue
        m = _GSP_LABEL_RE.match(c0)
        if m:
            group = "ГСП-%d" % int(m[1])
            if group not in info.groups:
                info.groups.append(group)
            continue
        if c0.startswith("для скважин") or c0.startswith("По "):
            active = False
            continue
        if not active or len(row) < 2:
            continue
        well = _well(row[1])
        if well is None:
            continue
        for j, d, bmode in blocks:
            mode = bmode or season_mode
            if mode is None:
                info.warnings.append("%s: скв. %d, %s — режим не указан, день пропущен" % (sheet, well, d))
                continue
            vals = [_num(row[k]) if k < len(row) else np.nan for k in range(j, j + BLOCK)]
            if np.isnan(vals).all():
                info.empty += 1
                continue
            if unit_p == "kpa":
                vals[0] = vals[0] / KPA_PER_KGF
            if unit_q == "m3":
                vals[3] = vals[3] / 1000
            recs.append({
                "Дата": pd.Timestamp(d), "Режим": mode, "ГСП": group, "Скважина": well, "№ п/п": c0,
                "Начало сезона": pd.Timestamp(season) if season else pd.NaT,
                "P газа, кгс/см²": vals[0], "T газа, °C": vals[1], "Y кру, %": vals[2],
                "Q газа, тыс. м³/сут": vals[3], "В работе, ч": vals[4],
                "Файл": info.name,
            })
    info.blocks = seen_blocks
    return recs


def _units(grid_rows: List[list]) -> Tuple[str, str]:
    """Единицы давления и расхода: кПа (xlsx ЭЛПРО) или кгс/см² (XML); Q «м3/ч» или «т. м³»."""
    head = [_text(x) for r in grid_rows[:15] for x in r[:8]]
    unit_p = "kpa" if "кПа" in head else "kgf"
    unit_q = "m3" if any(h.replace("³", "3") == "м3/ч" for h in head) else "tm3"
    return unit_p, unit_q


def read_file(path: str) -> Tuple[pd.DataFrame, FileInfo]:
    """Разбор одного файла. Пустой результат — не ошибка: файл попадёт в статистику с нулём записей."""
    name = os.path.basename(path)
    info = FileInfo(name=name, fmt="", month=_name_month(name))
    fmt, grids = read_grids(path)
    info.fmt = fmt
    recs: List[dict] = []
    for sheet, grid in grids:
        if not grid:
            continue
        # номер ГСП из заголовка «Параметры работы ГСП - 4»; в XML заголовок общий («ГСП-1,2,3»), там берутся подписи секций
        titles = {int(m[1]) for r in grid[:3] for x in r[:4] for m in [_GSP_TITLE_RE.search(_text(x))] if m}
        title = titles.pop() if len(titles) == 1 and not any("," in _text(x) for r in grid[:3] for x in r[:4]) else None
        fname_gsp = _GSP_FILE_RE.search(name)
        if fname_gsp and title and int(fname_gsp[1]) != title:
            info.warnings.append("%s: номер ГСП в имени (%s) и в заголовке (%d) не совпадают" % (name, fname_gsp[1], title))
        default = "ГСП-%d" % title if title else ("ГСП-%d" % int(fname_gsp[1]) if fname_gsp else None)
        unit_p, unit_q = _units(grid)
        info.q_unit = unit_q if unit_q == "m3" else info.q_unit
        if default and default not in info.groups:
            info.groups.append(default)
        recs += _parse_grid(sheet, grid, info, default, unit_p, unit_q)
    if not info.blocks:
        info.warnings.append("%s: шапка с датами не найдена — файл не похож на ЭЛПРО, пропущен" % name)
        return pd.DataFrame(columns=COLUMNS), info
    df = pd.DataFrame(recs, columns=COLUMNS)
    if info.month is not None and not df.empty:
        # в файле за месяц может стоять блок дня следующего месяца (например 01.12 в файле за ноябрь):
        # такой день берётся из файла своего месяца, здесь он не нужен и может быть неполным
        own = (df["Дата"].dt.year == info.month.year) & (df["Дата"].dt.month == info.month.month)
        info.outside = int((~own).sum())
        if info.outside:
            info.warnings.append("%s: строки за дни вне месяца отчёта не загружены: %d (даты %s)" % (
                name, info.outside, ", ".join(sorted(df.loc[~own, "Дата"].dt.strftime("%d.%m.%Y").unique())[:3])))
        df = df[own].reset_index(drop=True)
    if not df.empty:
        # физически невозможные значения (давление < 0 или > 400 кгс/см², расход < 0 или > 5000 тыс. м³/сут)
        # — ошибки в исходнике (например, 1e+24 в ячейке); они становятся пропуском и считаются
        bad_p = ((df["P газа, кгс/см²"] < 0) | (df["P газа, кгс/см²"] > 400)).fillna(False)
        bad_q = ((df["Q газа, тыс. м³/сут"] < 0) | (df["Q газа, тыс. м³/сут"] > 5000)).fillna(False)
        info.range_bad = int(bad_p.sum() + bad_q.sum())
        if info.range_bad:
            df.loc[bad_p, "P газа, кгс/см²"] = np.nan
            df.loc[bad_q, "Q газа, тыс. м³/сут"] = np.nan
            info.warnings.append("%s: значения вне диапазона заменены пропуском: давление %d, расход %d"
                                 % (name, int(bad_p.sum()), int(bad_q.sum())))
        # номер скважины в двух строках с разными значениями — не дубль, сохраняем обе, но сообщаем
        multi = df.groupby(["Дата", "ГСП", "Режим", "Скважина"])["№ п/п"].nunique()
        twice = sorted({int(w) for (_, _, _, w), n in multi.items() if n > 1})
        if twice:
            info.warnings.append("%s: номера скважин стоят в двух строках с разными «№ п/п»: %s — проверить в ЭЛПРО"
                                 % (name, ", ".join(map(str, twice[:20]))))
        dup = df.duplicated(KEY, keep="first")
        if dup.any():
            info.warnings.append("%s: одинаковые строки «день × ГСП × скважина × режим × № п/п»: %d (оставлена первая)"
                                 % (name, int(dup.sum())))
            df = df[~dup].reset_index(drop=True)
    info.wells = int(df["Скважина"].nunique()) if not df.empty else 0
    info.rows = len(df)
    return df, info


# ---------- сборка по папке ----------

def build(paths: Sequence[str], db: Optional[pd.DataFrame] = None) -> Tuple[pd.DataFrame, List[FileInfo], pd.DataFrame, List[str]]:
    """Все файлы → одна таблица, файлы, покрытие (ГСП × месяц) и предупреждения.

    Дозапись: строки прежней базы с тем же ключом (день, ГСП, скважина, режим, № п/п) заменяются новыми.
    """
    frames, infos, warn = [], [], []
    for p in paths:
        try:
            df, info = read_file(p)
        except Exception as exc:  # битый файл не останавливает пакет
            info = FileInfo(name=os.path.basename(p), fmt="", month=_name_month(os.path.basename(p)))
            info.warnings.append("%s: не прочитан (%s)" % (info.name, exc))
            df = pd.DataFrame(columns=COLUMNS)
        frames.append(df)
        infos.append(info)
        warn += info.warnings
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    data["Дата"] = pd.to_datetime(data["Дата"])
    m3 = [i.name for i in infos if i.q_unit == "m3"]
    if m3:
        warn.insert(0, "Q подписан «м3/ч» в %d файлах: принято как м³ за сутки (значения сопоставимы с «т. м³» в XML). "
                       "Подтвердить по БД расходов" % len(m3))
    # ГСП-8 в XML: давления 4–8 при 50–80 у остальных групп — похоже на МПа; не пересчитываем, подтвердить
    p8 = data[(data["ГСП"] == "ГСП-8") & data["P газа, кгс/см²"].notna()]["P газа, кгс/см²"]
    if len(p8) and p8.median() < 15:
        warn.insert(0, "ГСП-8: медиана давления %.1f кгс/см² (у ГСП-1…3 около 50–80). Похоже на МПа — пересчёт не делался, "
                       "подтвердить единицы в ЭЛПРО" % p8.median())
    if db is not None and not db.empty:
        old = db.reindex(columns=COLUMNS).copy()
        old["Дата"] = pd.to_datetime(old["Дата"])
        replaced = int(old.merge(data[KEY], on=KEY).shape[0]) if not data.empty else 0
        if replaced:
            warn.append("Строк с тем же ключом заменено новыми: %d" % replaced)
        data = pd.concat([old[~old.set_index(KEY).index.isin(data.set_index(KEY).index)], data], ignore_index=True)
    data = data.sort_values(["Дата", "ГСП", "Режим", "Скважина"]).reset_index(drop=True)
    return data, infos, coverage(data, infos), warn


def coverage(data: pd.DataFrame, infos: List[FileInfo]) -> pd.DataFrame:
    """Покрытие (ГСП × месяц отчёта). Ожидаемый месяц — тот, за который есть файл формата этой группы.

    Статус: «есть» — в файле месяца группа с данными; «ПРОПУСК: файла нет» — файла за месяц нет;
    «ПРОПУСК: в файле нет данных» — файл есть, а по группе все значения прочерки.
    """
    fmt_months: Dict[str, set] = {}
    group_fmt: Dict[str, set] = {}
    file_group: set = set()
    for info in infos:
        if info.month is None:
            continue
        fmt_months.setdefault(info.fmt, set()).add(info.month)
        for g in info.groups:
            group_fmt.setdefault(g, set()).add(info.fmt)
            file_group.add((g, info.month))
    counts: Dict[Tuple[str, date], Tuple[int, str, int]] = {}
    if not data.empty:
        month_of = {i.name: i.month for i in infos}
        for (g, name), grp in data.groupby(["ГСП", "Файл"]):
            mo = month_of.get(name)
            if mo is not None:
                counts[(g, mo)] = (int(grp["Скважина"].nunique()), ", ".join(sorted(grp["Режим"].unique())),
                                   int(grp["Дата"].nunique()))
    rows = []
    for g in sorted(group_fmt, key=lambda s: int(re.search(r"\d+", s)[0])):
        months = set()
        for f in group_fmt[g]:
            months |= fmt_months.get(f, set())
        for mo in sorted(months):
            if (g, mo) not in file_group:
                status, wells, modes, days = "ПРОПУСК: файла нет", 0, "", 0
            else:
                wells, modes, days = counts.get((g, mo), (0, "", 0))
                status = "есть" if wells else "ПРОПУСК: в файле нет данных"
            rows.append({"ГСП": g, "Месяц": mo.strftime("%m.%Y"), "Скважин": wells, "Дней с данными": days,
                         "Режим": modes, "Статус": status})
    return pd.DataFrame(rows, columns=["ГСП", "Месяц", "Скважин", "Дней с данными", "Режим", "Статус"])


def file_stats(infos: List[FileInfo]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Файл": i.name, "Формат": i.fmt or "—", "Месяц": i.month.strftime("%m.%Y") if i.month else "",
        "Группы": ", ".join(i.groups), "Записей": i.rows, "Скважин": i.wells,
        "Прочерков (нет данных)": i.empty, "Вне месяца (не загружено)": i.outside,
        "Вне диапазона (пропуск)": i.range_bad, "Предупреждений": len(i.warnings),
    } for i in infos], columns=["Файл", "Формат", "Месяц", "Группы", "Записей", "Скважин",
                               "Прочерков (нет данных)", "Вне месяца (не загружено)", "Вне диапазона (пропуск)",
                               "Предупреждений"])
