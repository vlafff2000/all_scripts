"""Сравнение двух БД ГИС (папок с `gis_observations/packs/intervals`): прежней («База ГИС», из Excel) и новой (из отчётов).

Программа ничего не исправляет и не выбирает «правильную» базу: она показывает расхождения и откуда они, решает инженер.
Замеры сопоставляются по скважине и месяцу (в прежней базе дата бывает «первое число сезона», в отчётах — точная), пачки — по
названию, интервалы — по границам с допуском. Расхождения помечены видом («только в А», «только в Б», «разные значения») и
подсказкой, где искать (например, «ГВК отличается на 0,8 м: проверьте, какой замер в отчёте»).
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import qc

TOL_DEPTH = 0.15      # м: границы интервалов и ГВК считаются совпавшими
TOL_KG = 0.03         # доля единицы
TABLES = ("gis_observations", "gis_packs", "gis_intervals")


def load_db(folder: str) -> Dict[str, pd.DataFrame]:
    """Три таблицы из папки: parquet, иначе CSV («;», десятичная запятая). Нет таблицы — пустая."""
    out: Dict[str, pd.DataFrame] = {}
    for name in TABLES:
        pq, csv = os.path.join(folder, name + ".parquet"), os.path.join(folder, name + ".csv")
        if os.path.exists(pq):
            df = pd.read_parquet(pq)
        elif os.path.exists(csv):
            df = pd.read_csv(csv, sep=";", decimal=",", encoding="utf-8-sig", dtype={"well": str})
        else:
            df = pd.DataFrame()
        if len(df):
            df["well"] = df["well"].map(qc.well_key)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["month"] = df["date"].dt.strftime("%Y-%m")
        out[name] = df
    if not any(len(v) for v in out.values()):
        raise ValueError("В папке «%s» нет таблиц gis_observations / gis_packs / gis_intervals" % folder)
    return out


def _num(x) -> Optional[float]:
    return None if x is None or pd.isna(x) else float(x)


def _diff(a, b, tol: float) -> Optional[float]:
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return None if a is None and b is None else float("inf")
    return round(b - a, 3) if abs(b - a) > tol else None


def compare_observations(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ka = {(r.well, r.month): r for r in a.itertuples()} if len(a) else {}
    kb = {(r.well, r.month): r for r in b.itertuples()} if len(b) else {}
    for key in sorted(set(ka) | set(kb)):
        ra, rb = ka.get(key), kb.get(key)
        if ra is not None and rb is not None:
            if str(ra.date)[:10] != str(rb.date)[:10]:
                rows.append({"Скважина": key[0], "Месяц": key[1], "Вид": "дата различается", "Дата А": ra.date, "Дата Б": rb.date,
                             "Подсказка": "тот же месяц, разные числа: в прежней базе дата может быть первым числом сезона"})
            continue
        rows.append({"Скважина": key[0], "Месяц": key[1], "Вид": "только в А" if rb is None else "только в Б", "Дата А": getattr(ra, "date", None),
                     "Дата Б": getattr(rb, "date", None),
                     "Подсказка": "замера нет в новой базе: проверьте, есть ли отчёт за эту дату" if rb is None else "замера нет в прежней базе: новый отчёт или пропуск в Excel"})
    return pd.DataFrame(rows, columns=["Скважина", "Месяц", "Вид", "Дата А", "Дата Б", "Подсказка"])


def compare_packs(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    fields = (("top_m", "Кровля, м", TOL_DEPTH), ("bottom_m", "Подошва, м", TOL_DEPTH), ("h_eff_m", "hг эф, м", TOL_DEPTH), ("kg_avg", "Кг ср.взв", TOL_KG),
              ("gvk_depth_m", "ГВК MD, м", TOL_DEPTH), ("gvk_abs_m", "ГВК а.о., м", TOL_DEPTH))
    key = ["well", "month", "pack"]
    rows = []
    if not len(a) or not len(b):
        return pd.DataFrame(columns=["Скважина", "Месяц", "Пачка", "Вид", "Показатель", "А", "Б", "Разница (Б−А)", "Подсказка"])
    m = a.merge(b, on=key, how="outer", suffixes=("_a", "_b"), indicator=True)
    for d in m.to_dict("records"):
        base = {"Скважина": d["well"], "Месяц": d["month"], "Пачка": d["pack"]}
        if d["_merge"] != "both":
            rows.append({**base, "Вид": "только в А" if d["_merge"] == "left_only" else "только в Б", "Показатель": "", "А": None, "Б": None, "Разница (Б−А)": None,
                         "Подсказка": "пачки нет в новой базе" if d["_merge"] == "left_only" else "пачки нет в прежней базе"})
            continue
        for col, name, tol in fields:
            va, vb = d.get(col + "_a"), d.get(col + "_b")
            df = _diff(va, vb, tol)
            if df is None:
                continue
            hint = "значение есть только в одной базе" if df == float("inf") else (
                "ГВК: проверьте замер и абсолютную отметку (альтитуда, MD)" if col.startswith("gvk") else
                "hэф зависит от порога Кг и от того, считается ли интервал ниже ГВК" if col == "h_eff_m" else "")
            rows.append({**base, "Вид": "разные значения", "Показатель": name, "А": _num(va), "Б": _num(vb), "Разница (Б−А)": None if df == float("inf") else df, "Подсказка": hint})
    return pd.DataFrame(rows)


def compare_intervals(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    cols = ["Скважина", "Месяц", "Пачка", "От, м", "До, м", "Вид", "Кг А", "Кг Б", "Подсказка"]
    if not len(a) or not len(b):
        return pd.DataFrame(columns=cols)
    rows = []
    months = sorted(set(zip(a["well"], a["month"])) | set(zip(b["well"], b["month"])))
    ga, gb = dict(list(a.groupby(["well", "month"]))), dict(list(b.groupby(["well", "month"])))
    for key in months:
        if key not in ga or key not in gb:
            continue            # замер целиком в одной базе — это уже в листе «Замеры»
        ia, ib = ga[key].sort_values("from_m").to_dict("records"), gb[key].sort_values("from_m").to_dict("records")
        used = set()
        for ra in ia:
            hit = None
            for j, rb in enumerate(ib):
                if j in used or rb["pack"] != ra["pack"]:
                    continue
                if abs(rb["from_m"] - ra["from_m"]) <= TOL_DEPTH and abs(rb["to_m"] - ra["to_m"]) <= TOL_DEPTH:
                    hit = j
                    break
            base = {"Скважина": key[0], "Месяц": key[1], "Пачка": ra["pack"], "От, м": ra["from_m"], "До, м": ra["to_m"]}
            if hit is None:
                rows.append({**base, "Вид": "только в А", "Кг А": _num(ra.get("kg")), "Кг Б": None,
                             "Подсказка": "в новой базе нет интервала с такими границами (другая разбивка или пропуск)"})
                continue
            used.add(hit)
            rb = ib[hit]
            dk = _diff(ra.get("kg"), rb.get("kg"), TOL_KG)
            if dk is not None:
                rows.append({**base, "Вид": "разный Кг", "Кг А": _num(ra.get("kg")), "Кг Б": _num(rb.get("kg")),
                             "Подсказка": "Кг в отчёте мог быть диапазоном: в новой базе взято среднее" if rb.get("kg_text") or ra.get("kg_text") else "проверьте Кг по отчёту"})
        for j, rb in enumerate(ib):
            if j not in used:
                rows.append({"Скважина": key[0], "Месяц": key[1], "Пачка": rb["pack"], "От, м": rb["from_m"], "До, м": rb["to_m"], "Вид": "только в Б",
                             "Кг А": None, "Кг Б": _num(rb.get("kg")), "Подсказка": "в прежней базе нет интервала с такими границами"})
    return pd.DataFrame(rows, columns=cols)


def compare(a: Dict[str, pd.DataFrame], b: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    obs = compare_observations(a["gis_observations"], b["gis_observations"])
    packs = compare_packs(a["gis_packs"], b["gis_packs"])
    ints = compare_intervals(a["gis_intervals"], b["gis_intervals"])
    summary = pd.DataFrame([
        {"Показатель": "Замеров в А / в Б", "Значение": "%d / %d" % (len(a["gis_observations"]), len(b["gis_observations"]))},
        {"Показатель": "Замеры только в А", "Значение": int((obs["Вид"] == "только в А").sum())},
        {"Показатель": "Замеры только в Б", "Значение": int((obs["Вид"] == "только в Б").sum())},
        {"Показатель": "Пачки: расхождений", "Значение": len(packs)},
        {"Показатель": "Интервалы: расхождений", "Значение": len(ints)},
        {"Показатель": "Допуск по глубине, м / по Кг", "Значение": "%g / %g" % (TOL_DEPTH, TOL_KG)},
        {"Показатель": "Как читать", "Значение": "А — прежняя база, Б — новая. Программа ничего не исправляет: расхождение — повод открыть источник и решить."}])
    return {"Сводка": summary, "Замеры": obs, "Пачки": packs, "Интервалы": ints}


def export(a_dir: str, b_dir: str, out_dir: str) -> Tuple[str, Dict[str, pd.DataFrame]]:
    os.makedirs(out_dir, exist_ok=True)
    frames = compare(load_db(a_dir), load_db(b_dir))
    path = os.path.join(out_dir, "Сравнение_БД_ГИС.xlsx")
    with pd.ExcelWriter(path, engine="xlsxwriter", datetime_format="dd.mm.yyyy", date_format="dd.mm.yyyy") as xw:
        for name, fr in frames.items():
            fr.to_excel(xw, sheet_name=name, index=False)
            sh = xw.sheets[name]
            sh.freeze_panes(1, 0)
            for i, c in enumerate(fr.columns):
                sh.set_column(i, i, 60 if c in ("Подсказка", "Значение") else 14)
    return path, frames
