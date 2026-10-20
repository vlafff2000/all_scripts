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


def _dates(col: pd.Series) -> pd.Series:
    """Даты Excel как есть; строки: ГГГГ-ММ-ДД разбираются по ISO, остальные (дд.мм.гггг) день-вперёд."""
    if pd.api.types.is_datetime64_any_dtype(col):
        return col
    def one(v):
        if isinstance(v, str) and re.match(r"^\s*\d{4}-\d{2}-\d{2}", v):
            return pd.to_datetime(v, errors="coerce")
        return pd.to_datetime(v, errors="coerce", dayfirst=True)
    return col.map(one)


def _numbers(col: pd.Series) -> pd.Series:
    """Числа Excel как есть; текст с запятой и пробелами («1 234,5») тоже разбирается."""
    if pd.api.types.is_numeric_dtype(col):
        return pd.to_numeric(col, errors="coerce")
    txt = col.astype(str).str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(txt, errors="coerce").where(col.notna())


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
    d["wbp"], d["bhp"], d["q"] = (_numbers(d[c]) for c in ("wbp", "bhp", "q"))
    d["d"] = _dates(d["d"])
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
    manual: int = 0              # сколько исследований скважины решено вручную

    def to_dict(self) -> dict:
        d = dict(well=self.well, model=self.model, n_studies=self.n_studies, n_usable=self.n_usable,
                 date=self.date.strftime("%Y-%m-%d") if self.date else "", status=self.status,
                 age_years=None if not np.isfinite(self.age_years) else round(self.age_years, 1),
                 a=None if not np.isfinite(self.a) else self.a, b=None if not np.isfinite(self.b) else self.b,
                 n_regimes=self.n_regimes, note=self.note, include=self.include, auto=self.auto, manual=self.manual)
        return d


@dataclass
class StudyRow:
    """Одно исследование ГДИ: что показал контроль качества и что решил инженер."""
    well: str                     # имя в БД ГДИ
    model: str                    # имя в модели ("" - в модели нет)
    date: dt.datetime
    key: str                      # ключ ручного решения: study_key
    status: str                   # good / fair / bad - заключение программы
    reasons: str                  # почему брак (подсказка для инженера)
    warnings: str
    n_regimes: int
    a: float
    b: float
    auto: bool                    # решение программы: брать (прошло контроль) или нет
    manual: Optional[bool]        # решение инженера; None - не трогали
    use: bool                     # итог: берётся в расчёт

    def to_dict(self) -> dict:
        return dict(well=self.well, model=self.model, date=self.date.strftime("%Y-%m-%d"), key=self.key, status=self.status,
                    reasons=self.reasons, warnings=self.warnings, n_regimes=self.n_regimes,
                    a=None if not np.isfinite(self.a) else self.a, b=None if not np.isfinite(self.b) else self.b,
                    auto=self.auto, manual=self.manual, use=self.use)


@dataclass
class Selection:
    rows: List[Row] = field(default_factory=list)
    chosen: Dict[str, GDI] = field(default_factory=dict)     # имя в модели -> выбранное исследование
    qcs: Dict[str, quality.QC] = field(default_factory=dict)  # те же ключи
    history: Dict[str, List[GDI]] = field(default_factory=dict)  # все взятые в расчёт исследования (по возрастанию даты)
    notes: List[str] = field(default_factory=list)
    model_only: List[str] = field(default_factory=list)       # скважины модели без ГДИ
    studies: List[StudyRow] = field(default_factory=list)     # все исследования БД с решениями
    manual: int = 0                                           # ручных решений всего: по исследованиям и по скважинам


def study_key(well: str, date: dt.datetime) -> str:
    """Ключ исследования для ручных решений: «скважина|ГГГГ-ММ-ДД»."""
    return "%s|%s" % (well, date.strftime("%Y-%m-%d"))


def select(studies: Sequence[GDI], cfg, st: Settings, model: Optional[Sequence[str]] = None,
           resolve=None, overrides: Optional[Dict[str, bool]] = None, today: Optional[dt.datetime] = None,
           study_overrides: Optional[Dict[str, bool]] = None) -> Selection:
    """Для каждой скважины БД ГДИ: контроль качества всех исследований и выбор самого свежего из взятых в расчёт.

    model - скважины модели (None: сопоставление не делается); resolve(имя) -> имя в модели или None (синонимы проекта);
    overrides - ручное включение скважины {имя в БД: bool};
    study_overrides - ручное решение по исследованию {study_key: True (взять, даже если программа забраковала) /
    False (не брать)}. Ручное решение приоритетнее контроля качества; без него исследование берётся, если прошло контроль.
    today - точка отсчёта возраста (по умолчанию дата последнего ГДИ в БД).
    """
    st.validate()
    overrides = overrides or {}
    so = study_overrides or {}
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
        manual = [so.get(study_key(w, g.date)) for g, _ in qcs]
        use = [q.status in allowed if m is None else m for (_, q), m in zip(qcs, manual)]
        row.n_usable = sum(1 for _, q in qcs if q.status in allowed)
        row.manual = sum(1 for m in manual if m is not None)
        sel.manual += row.manual + (1 if w in overrides else 0)
        for (g, q), m, u in zip(qcs, manual, use):
            sel.studies.append(StudyRow(well=w, model=row.model, date=g.date, key=study_key(w, g.date), status=q.status,
                                        reasons=q.reasons, warnings=q.warnings, n_regimes=len(g.q), a=g.a, b=g.b,
                                        auto=q.status in allowed, manual=m, use=u))
        chosen = [(g, q, m) for (g, q), m, u in zip(qcs, manual, use) if u]
        if model is not None and not row.model:
            row.note = "нет в модели"
        elif not chosen and any(m is False for m in manual):
            row.note = "все взятые ГДИ исключены вручную"
        elif not chosen:
            last_g, last_q = qcs[0]
            row.note = "все ГДИ забракованы; последнее от %s: %s" % (last_g.date.strftime("%d.%m.%Y"), last_q.reasons or "—")
        else:
            g, q, m = chosen[0]
            row.date, row.status = g.date, q.status
            row.age_years = (ref - g.date).days / 365.25
            row.a, row.b, row.n_regimes = g.a, g.b, len(g.q)
            warn = [q.warnings] if q.warn else []
            if m is None and st.max_age_years is not None and row.age_years > st.max_age_years:
                row.note = "ГДИ старше %g лет (%.1f)" % (st.max_age_years, row.age_years)
            else:
                row.auto = True
            if m:
                warn.append("взято вручную, программа забраковала: %s" % (q.reasons or "—"))
            newest_g, newest_q = qcs[0]
            if row.auto and newest_g is not g:
                if manual[0] is False:
                    warn.append("свежее ГДИ от %s исключено вручную" % newest_g.date.strftime("%d.%m.%Y"))
                elif manual[0] is None:
                    warn.append("свежее ГДИ от %s забраковано: %s" % (newest_g.date.strftime("%d.%m.%Y"), newest_q.reasons or "—"))
            if warn:
                row.note = "; ".join(x for x in [row.note] + warn if x)
            sel.qcs[row.model or w] = q
            sel.chosen[row.model or w] = g
            sel.history[row.model or w] = sorted((c[0] for c in chosen), key=lambda u: u.date)
        row.include = bool(overrides.get(w, row.auto)) and row.date is not None and bool(row.model)
        sel.rows.append(row)
    if model is not None:
        have = {r.model for r in sel.rows if r.model}
        sel.model_only = [m for m in model if m not in have]
    return sel


def chosen_for_kit(sel: Selection, all_dates: bool = False) -> List[Tuple[str, GDI]]:
    """Исследования для комплекта: (имя в модели, GDI), только включённые скважины.
    all_dates - все прошедшие контроль исследования скважины (по возрастанию даты), а не только последнее."""
    out: List[Tuple[str, GDI]] = []
    for r in sel.rows:
        if r.include and r.model in sel.chosen:
            for g in (sel.history.get(r.model) or [sel.chosen[r.model]]) if all_dates else [sel.chosen[r.model]]:
                out.append((r.model, g))
    return out
