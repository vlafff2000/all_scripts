"""Вспомогательные входные файлы: периоды работы, глубины и альтитуды, замеры воды, давление.

Разбор повторяет старый скрипт (apps/map_dashboards), форматы файлов те же; добавлены разбор формата замеров
«литров за час / ВФ» и терпимость к опечаткам дат. Всё, что пропущено, попадает в список предупреждений.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

EPOCH = np.datetime64("1970-01-01", "D")
MONTHS = {"января": 1, "январь": 1, "февраля": 2, "февраль": 2, "марта": 3, "март": 3, "апреля": 4, "апрель": 4,
          "мая": 5, "май": 5, "июня": 6, "июнь": 6, "июля": 7, "июль": 7, "августа": 8, "август": 8,
          "сентября": 9, "сентябрь": 9, "октября": 10, "октябрь": 10, "ноября": 11, "ноябрь": 11,
          "декабря": 12, "декабрь": 12}
_MONTH_RE = re.compile(r"(январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|август[а]?|сентябр[ья]|"
                       r"октябр[ья]|ноябр[ья]|декабр[ья])", re.I)


def day_of(dt: datetime) -> int:
    return int((np.datetime64(dt.date(), "D") - EPOCH).astype("int64"))


def iso(day: int) -> str:
    return str(EPOCH + np.timedelta64(int(day), "D"))


def _read_text(path: str) -> List[str]:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read().splitlines()
        except UnicodeDecodeError:
            continue
    return []


def parse_date(text: str) -> Optional[datetime]:
    t = text.strip().rstrip(".")
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            pass
    return None


# ---------------- периоды работы ----------------
def load_periods(path: str) -> Tuple[List[Tuple[int, str]], List[str]]:
    """Строки «08.04.2012 inj» (inj — закачка, prod — отбор, none — нейтральный период)."""
    out: List[Tuple[int, str]] = []
    warn: List[str] = []
    if not path or not os.path.isfile(path):
        return out, warn
    for line in _read_text(path):
        parts = line.split()
        if len(parts) < 2:
            continue
        dt = parse_date(parts[0])
        if dt is None:
            warn.append("Периоды: не разобрана дата «%s»" % parts[0])
            continue
        out.append((day_of(dt), parts[1].lower()))
    out.sort()
    return out, warn


# ---------------- глубины и альтитуды ----------------
def load_perforations(path: str) -> Tuple[Dict[int, Tuple[float, float]], Dict[int, float]]:
    """Абсолютные глубины верха/низа перфорации (как в старом скрипте, столбцы 5 и 6) и альтитуды устья."""
    depths: Dict[int, Tuple[float, float]] = {}
    alt: Dict[int, float] = {}
    if not path or not os.path.isfile(path):
        return depths, alt
    try:
        xl = pd.ExcelFile(path, engine="calamine")
    except Exception:
        xl = pd.ExcelFile(path)
    names = xl.sheet_names
    sheet = next((n for n in names if "перфор" in n.lower()), None)
    if sheet:
        df = xl.parse(sheet)
        for r in df.itertuples(index=False):
            try:
                well = int(float(str(r[0]).strip()))
                top, bottom = float(r[4]), float(r[5])
            except (ValueError, TypeError, IndexError):
                continue
            if well and top == top and bottom == bottom and top and bottom:
                depths[well] = (top, bottom)
    sheet = next((n for n in names if "альтитуд" in n.lower()), None)
    if sheet:
        df = xl.parse(sheet)
        for r in df.itertuples(index=False):
            try:
                well, z = int(float(str(r[0]).strip())), float(r[1])
            except (ValueError, TypeError, IndexError):
                continue
            if z == z:
                alt[well] = z
    return depths, alt


# ---------------- вода ----------------
def _num(text) -> Optional[float]:
    try:
        return float(str(text).strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _leading_number(text) -> Optional[float]:
    m = re.match(r"\s*(-?\d+(?:[.,]\d+)?)", str(text))
    return float(m.group(1).replace(",", ".")) if m else None


def parse_water_row(vals: List[object], has_flow_col: bool) -> Tuple[Optional[float], Optional[float], str]:
    """Строка старого формата: (водный фактор, расход воды л/ч, примечание); None — нет данных (песок, ремонт)."""
    def present(i: int) -> bool:
        return len(vals) > i and vals[i] is not None and not (isinstance(vals[i], float) and np.isnan(vals[i]))

    water_factor: Optional[float] = 0.0
    flow_lh: Optional[float] = 0.0
    gas_flow = 0.0
    note = ""
    if present(1):
        val = str(vals[1]).strip().lower()
        if "нет воды" in val or val == "" or val == "nan":
            water_factor, flow_lh = 0.0, 0.0
        elif "песок" in val or "ремонт" in val or "не идет" in val:
            note = str(vals[1]).strip()
            water_factor, flow_lh = None, None
        elif "1000м³/" in val or "1000м3/" in val:
            m = re.search(r"/(\d+[.,]?\d*)\s*л", val)
            if m:
                water_factor = _num(m.group(1)) or 0.0
        elif "/" in val:
            water_factor = _num(val.split("/")[0]) or 0.0
        else:
            water_factor = _num(val) or 0.0
    if present(2):
        gas_flow = _num(vals[2]) or 0.0
    if has_flow_col and present(3):
        s = str(vals[3]).strip()
        if s and s.lower() not in ("nan", "", "песок в ремонт", "не идет"):
            flow_lh = _num(s) or 0.0
    elif not has_flow_col:
        if water_factor and water_factor > 0 and gas_flow > 0:
            flow_lh = round(gas_flow * water_factor / 1000, 1)
    return water_factor, flow_lh, note


def _month_year(fname: str, head: List[str]) -> Optional[Tuple[int, int]]:
    for text in [fname] + head:
        m, y = _MONTH_RE.search(text), re.search(r"(20\d{2})", text)
        if m and y:
            return MONTHS[m.group(1).lower()], int(y.group(1))
    return None


def load_water(paths: List[str]) -> Tuple[pd.DataFrame, List[str]]:
    """Замеры выноса пластовой жидкости по файлам «… <месяц> <год>»: одна запись на скважину и месяц."""
    cols = ["Скважина", "Месяц", "Год", "Дата_замера", "Метка_замера", "Водный_фактор", "Расход_воды_лч", "Примечание"]
    records: List[dict] = []
    warn: List[str] = []
    for fp in paths:
        fname = os.path.basename(fp)
        try:
            xl = pd.ExcelFile(fp, engine="calamine")
        except Exception:
            try:
                xl = pd.ExcelFile(fp)
            except Exception as e:
                warn.append("Вода: %s не открыт (%s)" % (fname, e))
                continue
        df = None
        for sheet in xl.sheet_names:
            try:
                tmp = xl.parse(sheet, header=None)
            except Exception:
                continue
            if len(tmp) > 0 and tmp.shape[1] >= 2:
                first = tmp.iloc[:, 0]
                if sum(1 for v in first if str(v).strip().replace("-", "").replace(".", "").isdigit()) >= 1:
                    df = tmp
                    break
        if df is None:
            warn.append("Вода: в %s не найдена таблица со скважинами" % fname)
            continue
        head = [" ".join(str(v) for v in df.iloc[i].tolist() if isinstance(v, str)) for i in range(min(3, len(df)))]
        my = _month_year(fname, head)
        if my is None:
            warn.append("Вода: в %s и в заголовке листа не найдены месяц и год" % fname)
            continue
        month, year = my
        headers = " ".join(head).lower() + " " + " ".join(str(v) for v in df.iloc[:4].values.ravel().tolist()).lower()
        litres = "литров" in headers or "вф" in headers.split()
        has_flow_col = df.shape[1] >= 4
        for row in df.itertuples(index=False):
            try:
                well = int(float(str(row[0]).strip()))
            except ValueError:
                continue
            vals = list(row)
            if litres:  # «№скв | литров за час | литров за сутки | расход газа | … | ВФ (л/м³)»
                lh = _leading_number(vals[1]) if len(vals) > 1 else None
                gas = _num(vals[3]) if len(vals) > 3 else None
                vf = _num(vals[-1]) if len(vals) > 5 else None
                if vf is None and lh is not None and gas:
                    vf = lh / gas
                wf, flow, note = (vf * 1000 if vf is not None else 0.0), (lh or 0.0), ""
            else:
                wf, flow, note = parse_water_row(vals, has_flow_col)
            records.append({"Скважина": well, "Месяц": month, "Год": year,
                            "Дата_замера": "%d-%02d-01" % (year, month), "Метка_замера": "%02d.%d" % (month, year),
                            "Водный_фактор": wf if wf is not None else (0.0 if not note else None),
                            "Расход_воды_лч": flow if flow is not None else (0.0 if not note else None),
                            "Примечание": note or "Ок"})
    return pd.DataFrame(records, columns=cols), warn


# ---------------- давление ----------------
def load_pressure(path: str, is_gsp: bool) -> Tuple[pd.DataFrame, List[str]]:
    """Файл ГСП: «520<TAB>22.11.2024<TAB>95,42», файл объекта: «02.08.2006<TAB>94,7»."""
    cols = ["Дата", "Давление_бар", "Скважина"]
    if not path or not os.path.isfile(path):
        return pd.DataFrame(columns=cols), []
    rows, bad = [], 0
    for line in _read_text(path):
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        need = 3 if is_gsp else 2
        if len(parts) < need:
            continue
        date_s, press_s = (parts[1], parts[2]) if is_gsp else (parts[0], parts[1])
        dt = parse_date(date_s)
        p = _num(press_s)
        if dt is None or p is None:
            if press_s.strip():  # пустое давление — нормально для файла, где замеров ещё нет
                bad += 1
            continue
        well = int(float(parts[0])) if is_gsp and _num(parts[0]) is not None else 0
        rows.append((dt, round(p, 2), well))
    df = pd.DataFrame(rows, columns=cols)
    if len(df):
        df = df.sort_values("Дата", kind="stable").reset_index(drop=True)
    warn = ["пропущено строк с неразобранной датой или значением — %d" % bad] if bad else []
    return df, warn
