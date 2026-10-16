"""Отбор ГДИ для адаптации: чтение БД ГДИ («База ПХГ»), коэффициенты a и b считаются заново по режимам,
контроль качества каждого исследования, выбор самого свежего прошедшего контроль, сопоставление скважин с моделью.

Результат отбора превращается в комплект для тНавигатора (`kit.write_kit`): по одной строке-исследованию на скважину.
Python 3.8+.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import quality
from .gdi import GDI, fit_ab, to_base_units

# слова в названии столбца БД ГДИ -> роль; первое подходящее по порядку, столбцы с лишними словами пропускаются
_ROLES = {
    "well": (("№скв", "скважин", "well"), ()),
    "date": (("дата", "date"), ()),
    "wbp": (("рпл", "pпл", "wbp"), ("рпл2", "рз2", "²", "^2", "max")),
    "bhp": (("рзаб", "pзаб", "bhp"), ("рпл2", "рз2", "²", "^2", "max")),
    "q": (("qгаза", "q газа", "дебит", "q,", "q ", "q"), ("max", "час", "св", "кру", "а.св")),
}
P_UNITS = ("kgf/cm2", "bar", "MPa")
Q_UNITS = ("10^3 m3/day", "m3/day")


def _norm_col(c) -> str:
    return re.sub(r"\s+", " ", str(c).strip().lower().replace("р ", "р"))


def detect_columns(columns: Sequence) -> Dict[str, str]:
    """Роли столбцов БД ГДИ по названиям: well, date, wbp, bhp, q. Чего не нашли, того нет в словаре."""
    out: Dict[str, str] = {}
    for role, (keys, stop) in _ROLES.items():
        for key in keys:
            hit = None
            for c in columns:
                n = _norm_col(c)
                if role == "q" and key == "q" and n != "q":
                    continue
                if key in n and not any(s in n for s in stop) and c not in out.values():
                    hit = c
                    break
            if hit is not None:
                out[role] = hit
                break
    return out


def clean_name(x) -> str:
    """33, 33.0, '33', ' 33 ' -> '33'."""
    if isinstance(x, (float, np.floating)) and float(x).is_integer():
        return str(int(x))
    return str(x).strip()


@dataclass
class Settings:
    p_units: str = "kgf/cm2"               # единицы давлений в БД ГДИ (давления абсолютные)
    q_units: str = "10^3 m3/day"           # единицы дебита в БД ГДИ
    min_status: str = "fair"               # 'good' - только хорошие; 'fair' - хорошие и удовлетворительные
    max_age_years: Optional[float] = None  # ГДИ старше исключаются; None - не ограничивать
    from_date: Optional[str] = None        # ГДИ раньше даты (ГГГГ-ММ-ДД) игнорируются
    ab_q_units: str = "10^3 m3/day"

    def validate(self) -> None:
        if self.p_units not in P_UNITS:
            raise ValueError("Единицы давления: %s" % ", ".join(P_UNITS))
        if self.q_units not in Q_UNITS:
            raise ValueError("Единицы дебита: %s" % ", ".join(Q_UNITS))
        if self.min_status not in ("good", "fair"):
            raise ValueError("Минимальный статус: good или fair")


def read_db(path: str, sheet=None) -> pd.DataFrame:
    from pxg_core.расходы_файлы import read_excel_safe
    kw = {"sheet_name": sheet} if sheet not in (None, "") else {}
    df = read_excel_safe(path, **kw)
    if df is None or len(df) == 0:
        raise ValueError("Не удалось прочитать БД ГДИ «%s». Проверьте путь и что файл не открыт в другой программе." % path)
    return df


def build_studies(df: pd.DataFrame, cols: Dict[str, str], st: Settings) -> Tuple[List[GDI], List[str]]:
    """Исследования = группа (скважина, дата). a и b считаются МНК по режимам (Pпл²−Pз² = A·Q + B·Q²), а не берутся из файла."""
    st.validate()
    need = [cols.get(k) for k in ("well", "date", "wbp", "bhp", "q")]
    miss = [k for k, c in zip(("скважина", "дата", "Pпл", "Pзаб", "Q"), need) if not c or c not in df.columns]
    if miss:
        raise ValueError("В БД ГДИ не указаны столбцы: %s. Есть: %s" % (", ".join(miss), ", ".join(str(c) for c in df.columns if not str(c).startswith("Unnamed"))))
    d = df[need].copy()
    d.columns = ["w", "d", "wbp", "bhp", "q"]
    n0 = len(d)
    d["wbp"], d["bhp"], d["q"] = (pd.to_numeric(d[c], errors="coerce") for c in ("wbp", "bhp", "q"))
    d["d"] = pd.to_datetime(d["d"], errors="coerce", dayfirst=True)
    d = d.dropna()
    notes: List[str] = []
    if len(d) < n0:
        notes.append("Пропущено строк без скважины, даты или значений: %d из %d" % (n0 - len(d), n0))
    d["w"] = d["w"].map(clean_name)
    d["d"] = d["d"].dt.normalize()
    if st.from_date:
        d = d[d["d"] >= pd.Timestamp(st.from_date)]
    out: List[GDI] = []
    for (w, day), g in d.groupby(["w", "d"], sort=False):
        wbp = to_base_units(g["wbp"].values, st.p_units, "pressure")
        bhp = to_base_units(g["bhp"].values, st.p_units, "pressure")
        q = to_base_units(g["q"].values, st.q_units, "flow_rate")
        ok = np.isfinite(wbp) & np.isfinite(bhp) & np.isfinite(q) & (wbp > bhp) & (q > 0)
        if not ok.any():
            continue
        wbp, bhp, q = wbp[ok], bhp[ok], q[ok]
        a, b = fit_ab(q, wbp, bhp, st.ab_q_units)
        notes_g = [] if ok.all() else ["отброшено режимов (Pзаб >= Pпл или Q <= 0): %d" % int((~ok).sum())]
        out.append(GDI(wname=w, date=day.to_pydatetime(), wbp=wbp, bhp=bhp, q=q, a=a, b=b, notes=notes_g, n_dropped=int((~ok).sum())))
    return out, notes


def model_wells(path: str) -> List[str]:
    """Скважины модели (по SMSPEC результатов расчёта: те, у которых есть WBHP). Файл UNSMRY не читается."""
    from schedule_pxg import results
    from tnav_results.ecl import read_all
    f = results.find_files(path)
    if "SMSPEC" not in f:
        raise ValueError("В «%s» нет файла SMSPEC" % path)
    s = {b.keyword: v for b, v in read_all(f["SMSPEC"], ["KEYWORDS", "WGNAMES", "NAMES"])}
    names = s.get("WGNAMES") or s.get("NAMES") or []
    kws = s.get("KEYWORDS") or []
    seen, out = set(), []
    for k, n in zip(kws, names):
        n = str(n).strip()
        if k == "WBHP" and n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


@dataclass
class Row:
    well: str                     # имя в БД ГДИ
    model: str = ""               # имя в модели ("" - в модели нет)
    n_studies: int = 0
    n_usable: int = 0             # исследований, прошедших контроль качества
    date: Optional[dt.datetime] = None      # выбранное ГДИ
    status: str = ""              # статус выбранного (good / fair)
    age_years: float = float("nan")
    a: float = float("nan")
    b: float = float("nan")
    n_regimes: int = 0
    note: str = ""                # почему не выбрано / предупреждения
    include: bool = False         # итог (с учётом ручных переключателей)
    auto: bool = False            # что решил отбор до ручных переключателей

    def to_dict(self) -> dict:
        d = dict(well=self.well, model=self.model, n_studies=self.n_studies, n_usable=self.n_usable,
                 date=self.date.strftime("%Y-%m-%d") if self.date else "", status=self.status,
                 age_years=None if not np.isfinite(self.age_years) else round(self.age_years, 1),
                 a=None if not np.isfinite(self.a) else self.a, b=None if not np.isfinite(self.b) else self.b,
                 n_regimes=self.n_regimes, note=self.note, include=self.include, auto=self.auto)
        return d


@dataclass
class Selection:
    rows: List[Row] = field(default_factory=list)
    chosen: Dict[str, GDI] = field(default_factory=dict)     # имя в модели -> выбранное исследование
    qcs: Dict[str, quality.QC] = field(default_factory=dict)  # те же ключи
    notes: List[str] = field(default_factory=list)
    model_only: List[str] = field(default_factory=list)       # скважины модели без ГДИ


def select(studies: Sequence[GDI], cfg, st: Settings, model: Optional[Sequence[str]] = None,
           resolve=None, overrides: Optional[Dict[str, bool]] = None, today: Optional[dt.datetime] = None) -> Selection:
    """Для каждой скважины БД ГДИ: контроль качества всех исследований и выбор самого свежего из прошедших.

    model - скважины модели (None: сопоставление не делается); resolve(имя) -> имя в модели или None (синонимы проекта);
    overrides - ручные включения/выключения {имя в БД: bool}; today - точка отсчёта возраста (по умолчанию дата последнего ГДИ в БД).
    """
    st.validate()
    overrides = overrides or {}
    by_well: Dict[str, List[GDI]] = {}
    for g in studies:
        by_well.setdefault(g.wname, []).append(g)
    ref = today or (max((g.date for g in studies), default=dt.datetime.now()))
    mset = {m.strip().lower(): m for m in (model or [])}
    allowed = ("good",) if st.min_status == "good" else ("good", "fair")
    sel = Selection()
    for w in sorted(by_well, key=lambda s: (not s.isdigit(), int(s) if s.isdigit() else 0, s)):
        lst = sorted(by_well[w], key=lambda g: g.date, reverse=True)
        row = Row(well=w, n_studies=len(lst))
        if model is not None:
            m = (resolve(w) if resolve else None) or mset.get(w.strip().lower())
            row.model = m or ""
        else:
            row.model = w
        qcs = [(g, quality.assess(g, cfg)) for g in lst]
        usable = [(g, q) for g, q in qcs if q.status in allowed]
        row.n_usable = len(usable)
        if model is not None and not row.model:
            row.note = "нет в модели"
        elif not usable:
            last_g, last_q = qcs[0]
            row.note = "все ГДИ забракованы; последнее от %s: %s" % (last_g.date.strftime("%d.%m.%Y"), last_q.reasons or "—")
        else:
            g, q = usable[0]
            row.date, row.status = g.date, q.status
            row.age_years = (ref - g.date).days / 365.25
            row.a, row.b, row.n_regimes = g.a, g.b, len(g.q)
            warn = [q.warnings] if q.warn else []
            if st.max_age_years is not None and row.age_years > st.max_age_years:
                row.note = "ГДИ старше %g лет (%.1f)" % (st.max_age_years, row.age_years)
            else:
                row.auto = True
            if row.auto and qcs[0][0] is not g:
                warn.append("свежее ГДИ от %s забраковано: %s" % (qcs[0][0].date.strftime("%d.%m.%Y"), qcs[0][1].reasons or "—"))
            if warn:
                row.note = "; ".join(x for x in [row.note] + warn if x)
            sel.qcs[row.model or w] = q
            sel.chosen[row.model or w] = g
        row.include = bool(overrides.get(w, row.auto)) and row.date is not None and bool(row.model)
        sel.rows.append(row)
    if model is not None:
        have = {r.model for r in sel.rows if r.model}
        sel.model_only = [m for m in model if m not in have]
    return sel


def chosen_for_kit(sel: Selection) -> List[Tuple[str, GDI]]:
    """Выбранные исследования для комплекта: (имя в модели, GDI), только включённые."""
    return [(r.model, sel.chosen[r.model]) for r in sel.rows if r.include and r.model in sel.chosen]
