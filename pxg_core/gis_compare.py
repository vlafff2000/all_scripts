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
NO_DATE = "без даты"
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
            df["month"] = df["date"].dt.strftime("%Y-%m").fillna(NO_DATE)     # без даты — своя группа (иначе пропуск float ломает сортировку)
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


def compare_packs(a: pd.DataFrame, b: pd.DataFrame, tol_depth: float = TOL_DEPTH, tol_kg: float = TOL_KG) -> pd.DataFrame:
    fields = (("top_m", "Кровля, м", tol_depth), ("bottom_m", "Подошва, м", tol_depth), ("h_eff_m", "hг эф, м", tol_depth), ("kg_avg", "Кг ср.взв", tol_kg),
              ("gvk_depth_m", "ГВК MD, м", tol_depth), ("gvk_abs_m", "ГВК а.о., м", tol_depth))
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


def compare_intervals(a: pd.DataFrame, b: pd.DataFrame, tol_depth: float = TOL_DEPTH, tol_kg: float = TOL_KG) -> pd.DataFrame:
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
            dk = _diff(ra.get("kg"), rb.get("kg"), tol_kg)
            if dk is not None:
                rows.append({**base, "Вид": "разный Кг", "Кг А": _num(ra.get("kg")), "Кг Б": _num(rb.get("kg")),
                             "Подсказка": "Кг в отчёте мог быть диапазоном: в новой базе взято среднее" if rb.get("kg_text") or ra.get("kg_text") else "проверьте Кг по отчёту"})
        for j, rb in enumerate(ib):
            if j not in used:
                rows.append({"Скважина": key[0], "Месяц": key[1], "Пачка": rb["pack"], "От, м": rb["from_m"], "До, м": rb["to_m"], "Вид": "только в Б",
                             "Кг А": None, "Кг Б": _num(rb.get("kg")), "Подсказка": "в прежней базе нет интервала с такими границами"})
    return pd.DataFrame(rows, columns=cols)


DIFF_SHEETS = ("Замеры", "Пачки", "Интервалы")
MARK_KEYS = ("Скважина", "Месяц", "Год", "Пачка", "От, м", "До, м", "Вид", "Показатель")
EXTRA_TABLES = ("gis_templating", "gis_complex")


def load_extra(folder: str) -> Dict[str, pd.DataFrame]:
    """Необязательные таблицы новой БД из отчётов: gis_templating (доход шаблона) и gis_complex (комплекс ГИС)."""
    out: Dict[str, pd.DataFrame] = {}
    for name in EXTRA_TABLES:
        pq, csv = os.path.join(folder, name + ".parquet"), os.path.join(folder, name + ".csv")
        df = pd.read_parquet(pq) if os.path.exists(pq) else pd.read_csv(csv, sep=";", decimal=",", encoding="utf-8-sig", dtype={"well": str}) if os.path.exists(csv) else pd.DataFrame()
        if len(df):
            df["well"] = df["well"].map(qc.well_key)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        out[name] = df
    return out


def _templating_sheet(a: Dict[str, pd.DataFrame], b: Dict[str, pd.DataFrame], tol: float) -> Optional[pd.DataFrame]:
    """«Доход шаблона»: скважина + год, допуск в метрах (общий код с «Сравнением БД шаблонирования»). Нет таблицы в одной из БД — листа нет."""
    from . import templating_db as td
    ta, tb = a.get("gis_templating"), b.get("gis_templating")
    if ta is None or tb is None or not len(ta) or not len(tb):
        return None
    ru = {"well": "Скважина", "date": "Дата", "kind": "Вид", "depth_m": "Глубина, м", "origin": "Источник данных", "file": "Файл"}

    def prep(df):
        d = df.rename(columns=ru)
        d["Год"] = d["Дата"].dt.year
        return d.dropna(subset=["Год", "Глубина, м"])
    r = td.compare_frames(prep(ta), prep(tb), tol)
    kinds = {"Расхождения": "расхождение", "Только в старой": "только в А", "Только в новой": "только в Б"}
    out = pd.concat([r[k].assign(Вид=v) for k, v in kinds.items()], ignore_index=True)
    out.insert(2, "Вид", out.pop("Вид"))
    return out.rename(columns={"Глубина старая, м": "А, м", "Глубина новая, м": "Б, м"}).drop(columns=["Решение инженера", "Комментарий"])


def _complex_sheet(a: Dict[str, pd.DataFrame], b: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    """«Комплекс ГИС»: замеры (скважина + месяц), где методы различаются или комплекс есть только в одной БД."""
    ca, cb = a.get("gis_complex"), b.get("gis_complex")
    if ca is None or cb is None or not len(ca) or not len(cb):
        return None
    col = next((c for c in ("methods_short", "methods", "method") if c in ca.columns and c in cb.columns), None)
    if col is None:
        return None

    def sets(df):
        df = df.dropna(subset=["date"])
        return {k: {x.strip() for v in g[col].dropna() for x in str(v).split(";") if x.strip()} for k, g in df.groupby(["well", df["date"].dt.strftime("%Y-%m")])}
    sa, sb = sets(ca), sets(cb)
    rows = []
    for k in sorted(set(sa) | set(sb)):
        x, y = sa.get(k), sb.get(k)
        if x == y:
            continue
        rows.append({"Скважина": k[0], "Месяц": k[1], "Вид": "только в А" if y is None else "только в Б" if x is None else "разные методы",
                     "Методы А": "; ".join(sorted(x or [])), "Методы Б": "; ".join(sorted(y or [])),
                     "Подсказка": "комплекс ГИС есть не в обеих БД" if x is None or y is None else "в А нет: %s; в Б нет: %s" % (", ".join(sorted(y - x)) or "—", ", ".join(sorted(x - y)) or "—")})
    return pd.DataFrame(rows, columns=["Скважина", "Месяц", "Вид", "Методы А", "Методы Б", "Подсказка"])


def _carry_marks(frames: Dict[str, pd.DataFrame], marks: str) -> None:
    """Решения инженера из прежней выгрузки сравнения переносятся по ключу строки (скважина, месяц/год, пачка, границы, вид, показатель)."""
    prev = pd.read_excel(marks, sheet_name=None, dtype=object)
    for name, df in frames.items():
        old = prev.get(name)
        if old is None or "Решение инженера" not in old.columns or "Решение инженера" not in df.columns:
            continue
        keys = [k for k in MARK_KEYS if k in df.columns and k in old.columns]

        def key(r):
            return tuple("" if pd.isna(r[k]) else str(r[k]) for k in keys)
        found = {key(r): r for _i, r in old.dropna(subset=["Решение инженера"]).iterrows()}
        for i, r in df.iterrows():
            hit = found.get(key(r))
            if hit is not None:
                df.at[i, "Решение инженера"] = hit["Решение инженера"]
                if "Комментарий" in old.columns and pd.notna(hit.get("Комментарий")):
                    df.at[i, "Комментарий"] = hit["Комментарий"]


def compare(a: Dict[str, pd.DataFrame], b: Dict[str, pd.DataFrame], tol_depth: float = TOL_DEPTH, tol_kg: float = TOL_KG, marks: str = "",
            extra_a: Optional[Dict[str, pd.DataFrame]] = None, extra_b: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, pd.DataFrame]:
    obs = compare_observations(a["gis_observations"], b["gis_observations"])
    packs = compare_packs(a["gis_packs"], b["gis_packs"], tol_depth, tol_kg)
    ints = compare_intervals(a["gis_intervals"], b["gis_intervals"], tol_depth, tol_kg)
    frames = {"Замеры": obs, "Пачки": packs, "Интервалы": ints}
    tpl = _templating_sheet(extra_a or {}, extra_b or {}, tol_depth)
    if tpl is not None:
        frames["Доход шаблона"] = tpl
    cx = _complex_sheet(extra_a or {}, extra_b or {})
    if cx is not None:
        frames["Комплекс ГИС"] = cx
    for df in frames.values():
        df["Решение инженера"], df["Комментарий"] = "", ""
    n_obs = len(set(zip(a["gis_observations"].get("well", []), a["gis_observations"].get("month", []))) | set(zip(b["gis_observations"].get("well", []), b["gis_observations"].get("month", []))))
    pct = lambda k, n: "%d (%.1f %%)" % (k, 100.0 * k / n) if n else str(k)        # noqa: E731
    rows = [("Замеров в А / в Б", "%d / %d" % (len(a["gis_observations"]), len(b["gis_observations"]))),
            ("Замеры только в А", pct(int((obs["Вид"] == "только в А").sum()), n_obs)), ("Замеры только в Б", pct(int((obs["Вид"] == "только в Б").sum()), n_obs)),
            ("Замеры с разной датой", pct(int((obs["Вид"] == "дата различается").sum()), n_obs)),
            ("Пачки: расхождений", len(packs)), ("Интервалы: расхождений", len(ints))]
    for name in ("Доход шаблона", "Комплекс ГИС"):
        rows.append((name + ": расхождений", len(frames[name]) if name in frames else "нет таблицы в одной из БД"))
    rows += [("Допуск по глубине, м / по Кг", "%g / %g" % (tol_depth, tol_kg)),
             ("Решений инженера отмечено", 0),
             ("Как читать", "А — прежняя база, Б — новая. Программа ничего не исправляет: расхождение — повод открыть источник; решение отмечается в столбце «Решение инженера».")]
    summary = pd.DataFrame(rows, columns=["Показатель", "Значение"])
    if marks:
        _carry_marks(frames, marks)
        summary.loc[summary["Показатель"] == "Решений инженера отмечено", "Значение"] = int(sum((f["Решение инженера"] != "").sum() for f in frames.values()))
    return {"Сводка": summary, **frames}


def export(a_dir: str, b_dir: str, out_dir: str, tol_depth: float = TOL_DEPTH, tol_kg: float = TOL_KG, marks: str = "") -> Tuple[str, Dict[str, pd.DataFrame]]:
    os.makedirs(out_dir, exist_ok=True)
    frames = compare(load_db(a_dir), load_db(b_dir), tol_depth, tol_kg, marks, load_extra(a_dir), load_extra(b_dir))
    path = os.path.join(out_dir, "Сравнение_БД_ГИС.xlsx")
    with pd.ExcelWriter(path, engine="xlsxwriter", datetime_format="dd.mm.yyyy", date_format="dd.mm.yyyy") as xw:
        for name, fr in frames.items():
            fr.to_excel(xw, sheet_name=name, index=False)
            sh = xw.sheets[name]
            sh.freeze_panes(1, 0)
            for i, c in enumerate(fr.columns):
                sh.set_column(i, i, 60 if c in ("Подсказка", "Значение") else 18 if c in ("Решение инженера", "Комментарий") else 14)
    return path, frames
