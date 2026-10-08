"""Пересчёт пластовых давлений на верх перфораций (логика Excel-файла «ФАЙЛ_СО_ВСЕМИ_ДАВЛЕНИЯМИ»).

Вход: строки замеров (скважина, дата, Рпл приведённое, Руст, избыточное давление, уровень жидкости), справочники
«Альтитуды» (Z, м) и «Перфорации» (абсолютная отметка верха перфораций). Глубина приведения 670 м одна для всех скважин.

Плотность воды ρ (г/см³), как в столбце I Excel:
  есть уровень E:               ρ = 10·D / (E + 670 + Z)
  нет уровня, есть избыточное G: ρ = 10·(D − G) / (670 + Z)
  есть Руст (газовая скважина):  ρ не считается
Давление на верх перфораций J (столбец J Excel):
  скважина из списка исключений или есть Руст:  J = D (без пересчёта)
  есть уровень и ρ:                             J = (E + Z + отметка)·ρ/10
  есть избыточное давление и ρ:                 J = (Z + отметка)·ρ/10 + G
K = J·0,980665 (кгс/см² в бар), плюс 1,01325 по флажку «+1 атм».
Excel при отсутствии отметки перфорации молча считал отметку нулём; здесь такая строка остаётся без J и помечается.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

DEFAULT_EXCLUDED = (8, 11, 110, 122, 447)
DEPTH = 670.0
KGF_TO_BAR = 0.980665
ATM = 1.01325

# Способ расчёта (столбец «Способ расчёта»)
M_EXCLUDED = "исключённая скважина, без пересчёта"
M_GAS = "есть Руст (газовая), без пересчёта"
M_LEVEL = "по уровню жидкости"
M_EXCESS = "по избыточному давлению"
M_NO_ALT = "нет альтитуды"
M_NO_PERF = "нет отметки перфорации"
M_NO_DATA = "нет данных"
M_ZERO = "расчёт невозможен (деление на ноль)"


def _num(x) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


@dataclass
class Refs:
    altitude: Dict[int, float] = field(default_factory=dict)
    perf_mark: Dict[int, float] = field(default_factory=dict)


def read_refs(path: str) -> Refs:
    """Альтитуды и абсолютные отметки верха перфораций из книги со справочниками (листы по названию «Альтитуд…», «Перфорац…»)."""
    import openpyxl
    refs = Refs()
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            low = ws.title.lower()
            if "альтитуд" in low:
                for row in ws.iter_rows(min_row=2, values_only=True):
                    w, z = _num(row[0]), _num(row[1]) if len(row) > 1 else None
                    if w is not None and z is not None:
                        refs.altitude[int(w)] = z
            elif "перфорац" in low:
                rows = list(ws.iter_rows(values_only=True))
                head = [str(c or "").lower() for c in (rows[0] if rows else ())]
                mark_col = next((i for i, h in enumerate(head) if "абсолютн" in h), None)
                pair: Dict[int, float] = {}
                for row in rows[1:]:
                    w = _num(row[0]) if row else None
                    if w is None:
                        continue
                    if mark_col is not None and mark_col < len(row) and _num(row[mark_col]) is not None:
                        refs.perf_mark[int(w)] = _num(row[mark_col])
                    elif len(row) > 1 and _num(row[1]) is not None and all(c in (None, "") for c in row[2:]):
                        pair[int(w)] = _num(row[1])   # нижняя таблица «скважина — отметка»
                for w, m in pair.items():
                    refs.perf_mark.setdefault(w, m)
    finally:
        wb.close()
    return refs


def level_value(raw, sign: str) -> Optional[float]:
    """Уровень жидкости E, м: «auto» — всегда ниже устья (−|Нст|), «as_is» — как в отчёте."""
    v = _num(raw)
    if v is None:
        return None
    return -abs(v) if sign == "auto" else v


def recalc_row(well: int, d, f, g, e, refs: Refs, excluded: Iterable[int] = DEFAULT_EXCLUDED, depth: float = DEPTH):
    """Одна строка: (ρ, J, способ). d — Рпл приведённое, f — Руст, g — избыточное, e — уровень (м, обычно отрицательный)."""
    d, f, g, e = _num(d), _num(f), _num(g), _num(e)
    if well in set(excluded):
        return None, d, M_EXCLUDED if d is not None else M_NO_DATA
    if d is None or (e is None and f is None and g is None):
        return None, None, M_NO_DATA
    if f is not None and f != 0 and d != 0:
        return None, d, M_GAS
    z, mark = refs.altitude.get(well), refs.perf_mark.get(well)
    if z is None:
        return None, None, M_NO_ALT
    if e is not None:
        den = e + depth + z
        rho = 10 * d / den if den else None
    elif g is not None:
        rho = 10 * (d - g) / (depth + z)
    else:
        return None, None, M_NO_DATA
    if rho is None:
        return None, None, M_ZERO
    if mark is None:
        return rho, None, M_NO_PERF
    if e is not None:
        return rho, (e + z + mark) * rho / 10, M_LEVEL
    return rho, (z + mark) * rho / 10 + g, M_EXCESS


def recalc(db: pd.DataFrame, refs: Refs, excluded: Iterable[int] = DEFAULT_EXCLUDED, level_sign: str = "auto",
           add_atm: bool = False, depth: float = DEPTH) -> pd.DataFrame:
    """Таблица замеров (столбцы «База давлений по замерам») -> таблица пересчёта."""
    excluded = tuple(excluded)
    out: List[list] = []
    for r in db.itertuples(index=False):
        row = r._asdict() if hasattr(r, "_asdict") else {}
        well = int(row["Скважина"])
        level = level_value(row.get("Уровень_жидкости"), level_sign)
        rho, j, how = recalc_row(well, row.get("Рпл"), row.get("Руст"), row.get("Избыточное_давление"), level, refs, excluded, depth)
        k = None if j is None else j * KGF_TO_BAR + (ATM if add_atm else 0.0)
        out.append([well, row.get("Дата"), row.get("Горизонт"), row.get("Категория"), _num(row.get("Руст")),
                    _num(row.get("Избыточное_давление")), level, _num(row.get("Рпл")), rho, j, k, how, row.get("Источник")])
    cols = ["Скважина", "Дата", "Горизонт", "Категория", "Руст, кгс/см2", "Избыточное давление, кгс/см2",
            "Уровень жидкости, м", "Рпл приведённое (на 670 м), кгс/см2", "Плотность воды, г/см3",
            "Рпл на верх перфораций, кгс/см2", "Рпл на верх перфораций, бар", "Способ расчёта", "Источник"]
    return pd.DataFrame(out, columns=cols)


def read_measurements(path: str) -> pd.DataFrame:
    """Лист «Данные» базы «База давлений по замерам» с именами столбцов без пробелов."""
    df = pd.read_excel(path, sheet_name="Данные")
    df = df.rename(columns={"Избыточное давление": "Избыточное_давление", "Уровень жидкости": "Уровень_жидкости"})
    for col in ("Руст", "Избыточное_давление", "Рпл", "Уровень_жидкости"):
        if col not in df.columns:
            df[col] = None
    for col in ("Горизонт", "Категория", "Источник"):
        if col not in df.columns:
            df[col] = None
    df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce")
    return df.dropna(subset=["Скважина"])


def include_frames(res: pd.DataFrame, add_atm: bool = False) -> Dict[str, pd.DataFrame]:
    """Include-таблицы «скважина, дата, давление (бар)» как в Excel-файле."""
    bar = "Рпл на верх перфораций, бар"

    def triple(df, col):
        t = df.dropna(subset=["Дата", col])[["Скважина", "Дата", col]].sort_values(["Дата", "Скважина"])
        t.columns = ["Скважина", "Дата", "Давление, бар"]
        return t

    raw_bar = (res["Рпл приведённое (на 670 м), кгс/см2"] * KGF_TO_BAR + (ATM if add_atm else 0.0))
    res = res.assign(_raw=raw_bar)
    exploit = res[res["Категория"] == "Эксплуатационные"]
    obs = res[res["Категория"] != "Эксплуатационные"]
    mean = (exploit.dropna(subset=["Дата", "_raw"]).groupby("Дата")["_raw"].mean().reset_index())
    mean.columns = ["Дата", "Среднее пластовое, бар"]
    return {
        "include_среднее_пластовое": mean,
        "include_эксплуатационные": triple(exploit, "_raw"),
        "include_набл_с_пересчётом": triple(obs, bar),
        "include_набл_без_пересчёта": triple(obs, "_raw"),
    }
