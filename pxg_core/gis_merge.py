"""Объединение двух БД ГИС: первая — «База ГИС» из Excel, вторая — «БД ГИС из отчётов» (Word). Вторая главнее.

Из первой берутся замеры, которых нет во второй (замер = скважина + месяц, как в ``gis_compare``); если замер есть в обеих, берётся целиком
из второй: замеры, пачки и интервалы не смешиваются. Исключение — список «взять из первой» (скважина + месяц): решение инженера главнее правила.
У каждой строки есть столбец ``db_source``.

Абсолютные отметки: если дан файл альтитуд (тот же «Глубины_перфораций.xlsx», что читают Газовый Атлас и Карты), альтитуда скважины берётся из него,
а ГВК а.о. пересчитывается из MD: а.о. = альтитуда − MD. Прежние значения остаются в ``altitude_prev_m`` и ``gvk_abs_prev_m``. Нет скважины в файле —
значения БД не трогаются. Расхождения альтитуд и неверные а.о. выводятся таблицей; автоматика только подсказывает, решает инженер.
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

from . import gis_compare, gis_export, qc

FIRST, SECOND = "БД 1 (Excel)", "БД 2 (отчёты)"
ALT_TOL = 0.05          # м: альтитуды и а.о. считаются совпавшими
NEAR_DAYS = 45          # замеры первой и второй БД ближе этого — возможный дубль с другой датой


def load_altitudes(path: str) -> Tuple[Dict[str, float], str]:
    """Альтитуды из файла Атласа/Карт: тот же разбор, что у ``well_construction`` и Газового Атласа (лист «альтитуды»)."""
    from .well_construction import file_altitudes
    alts, label = file_altitudes(path)
    return {qc.well_key(w): float(a) for w, a in alts.items()}, label


def load_keep_first(path: str) -> Set[Tuple[str, str]]:
    """Список «взять из первой БД»: столбцы «Скважина» и «Месяц» (ГГГГ-ММ или дата). Excel или CSV."""
    if not path:
        return set()
    df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig", dtype=str) if path.lower().endswith((".csv", ".txt")) else pd.read_excel(path, dtype=str)
    cols = {str(c).strip().lower(): c for c in df.columns}
    w, m = cols.get("скважина") or cols.get("well"), cols.get("месяц") or cols.get("month") or cols.get("дата")
    if w is None or m is None:
        raise ValueError("В файле решений нужны столбцы «Скважина» и «Месяц»")
    out = set()
    for _i, r in df.iterrows():
        month = pd.to_datetime(r[m], errors="coerce", dayfirst=True)
        if pd.notna(month):
            out.add((qc.well_key(r[w]), month.strftime("%Y-%m")))
    return out


def _prep(db: Dict[str, pd.DataFrame], label: str) -> Dict[str, pd.DataFrame]:
    out = {}
    for name in gis_compare.TABLES:
        df = db[name].copy() if len(db[name]) else pd.DataFrame(columns=["well", "date"])
        if "month" not in df.columns:
            df["month"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m")
        df["db_source"] = label
        out[name] = df
    return out


def _keys(frame: pd.DataFrame) -> Set[Tuple[str, str]]:
    return set(zip(frame["well"], frame["month"])) if len(frame) else set()


def _shift(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) - 1 + delta
    return "%04d-%02d" % (y + m // 12, m % 12 + 1)


def neighbour_pairs(ka: Set[Tuple[str, str]], kb: Set[Tuple[str, str]]) -> Dict[Tuple[str, str], Tuple[str, str]]:
    """Замеры первой БД, совпавшие с замером второй при сдвиге месяца на ±1 (в Excel дата только месяц-год, в отчётах — день).
    Соответствие один к одному: сначала точные совпадения, затем ближайший свободный сосед. Результат: ключ первой БД → ключ второй."""
    free_a = {k for k in ka if k not in kb}
    pairs: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for w, m in sorted(k for k in kb if k not in ka):
        for d in (-1, 1):
            cand = (w, _shift(m, d))
            if cand in free_a:
                pairs[cand] = (w, m)
                free_a.discard(cand)
                break
    return pairs


def choose(first: Dict[str, pd.DataFrame], second: Dict[str, pd.DataFrame], keep_first: Set[Tuple[str, str]] = frozenset()) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    """(объединённые таблицы, решения по каждому замеру). Решение: откуда взят замер и почему."""
    a, b = _prep(first, FIRST), _prep(second, SECOND)
    ka, kb = _keys(a["gis_observations"]) | _keys(a["gis_packs"]), _keys(b["gis_observations"]) | _keys(b["gis_packs"])
    near_pairs = neighbour_pairs(ka, kb)
    take_first = {k for k in ka if (k not in kb and k not in near_pairs) or k in keep_first}
    take_second = {k for k in kb if k not in take_first}
    rows: List[dict] = []
    second_dates = {k: pd.to_datetime(d["date"]).min() for k, d in b["gis_observations"].groupby(["well", "month"])} if len(b["gis_observations"]) else {}
    matched_second = {v: k for k, v in near_pairs.items()}
    for key in sorted(ka | kb):
        well, month = key
        note = ""
        if key in take_first:
            src, why = FIRST, ("только в первой БД" if key not in kb else "по решению инженера (список «взять из первой»)")
            if key in near_pairs:
                why = "по решению инженера (список «взять из первой»)"
        else:
            src, why = SECOND, ("только во второй БД" if key not in ka else "есть в обеих БД: вторая главнее")
            if key in near_pairs and key not in kb:
                continue                          # замер первой БД заменён замером второй (месяц ±1): отдельной строки нет
            if key in matched_second and key not in ka:
                why = "есть в обеих БД со сдвигом месяца на ±1 (в Excel %s): вторая главнее" % matched_second[key][1]
        if src == FIRST:                              # возможный дубль со сдвинутой датой
            d1 = pd.to_datetime(a["gis_observations"].loc[(a["gis_observations"]["well"] == well) & (a["gis_observations"]["month"] == month), "date"]).min()
            near = [(m, d) for (w, m), d in second_dates.items() if w == well and m != month and pd.notna(d1) and abs((d - d1).days) <= NEAR_DAYS]
            if near:
                note = "во второй БД у этой скважины замер рядом (%s): возможно, это один замер с другой датой; проверьте" % near[0][0]
        rows.append({"Скважина": well, "Месяц": month, "Источник": src, "Почему": why, "Подсказка": note})
    out = {}
    for name in gis_compare.TABLES:
        parts = []
        for df, take in ((a[name], take_first), (b[name], take_second)):
            if len(df):
                keep = df[[(w, m) in take for w, m in zip(df["well"], df["month"])]]
                parts.append(keep)
        out[name] = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return out, pd.DataFrame(rows, columns=["Скважина", "Месяц", "Источник", "Почему", "Подсказка"])


def _first_num(s: pd.Series) -> Optional[float]:
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.iloc[0]) if len(s) else None


def altitude_table(first: Dict[str, pd.DataFrame], second: Dict[str, pd.DataFrame], file_alt: Dict[str, float]) -> pd.DataFrame:
    """По скважине: альтитуда в первой БД, во второй, в файле; сколько ГВК а.о. не сходятся с «альтитуда − MD» в каждой БД."""
    def per(db):
        p = db["gis_packs"]
        if not len(p) or "altitude_m" not in p.columns:
            return {}, {}
        alts = {w: _first_num(g["altitude_m"]) for w, g in p.groupby("well")}
        bad = {}
        for w, g in p.groupby("well"):
            alt = file_alt.get(w, alts.get(w))
            md, ab = pd.to_numeric(g["gvk_depth_m"], errors="coerce"), pd.to_numeric(g["gvk_abs_m"], errors="coerce")
            bad[w] = 0 if alt is None else int((md.notna() & ab.notna() & ((alt - md - ab).abs() > ALT_TOL)).sum())
        return alts, bad
    a_alt, a_bad = per(first)
    b_alt, b_bad = per(second)
    rows = []
    for w in sorted(set(a_alt) | set(b_alt) | set(file_alt), key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x)):
        va, vb, vf = a_alt.get(w), b_alt.get(w), file_alt.get(w)
        hints = []
        if vf is None:
            hints.append("скважины нет в файле альтитуд: взято из БД")
        for label, v in (("первой БД", va), ("второй БД", vb)):
            if v is not None and vf is not None and abs(v - vf) > ALT_TOL:
                hints.append("альтитуда %s %g, в файле %g: ГВК а.о. пересчитан по файлу" % (label, v, vf))
        if va is not None and vb is not None and abs(va - vb) > ALT_TOL:
            hints.append("альтитуды БД различаются на %.2f м" % (vb - va))
        if a_bad.get(w):
            hints.append("в первой БД а.о. не равна «альтитуда − MD» у %d строк" % a_bad[w])
        if b_bad.get(w):
            hints.append("во второй БД а.о. не равна «альтитуда − MD» у %d строк" % b_bad[w])
        rows.append({"Скважина": w, "Альтитуда БД 1, м": va, "Альтитуда БД 2, м": vb, "Альтитуда файла, м": vf,
                     "Расхождение БД 1 − файл, м": None if va is None or vf is None else round(va - vf, 3),
                     "Расхождение БД 2 − файл, м": None if vb is None or vf is None else round(vb - vf, 3),
                     "Подсказка": "; ".join(hints)})
    return pd.DataFrame(rows)


def apply_altitudes(tables: Dict[str, pd.DataFrame], file_alt: Dict[str, float]) -> pd.DataFrame:
    """Альтитуда из файла и ГВК а.о. = альтитуда − MD в пачках и интервалах (на месте). Возвращает таблицу изменений."""
    p, iv = tables["gis_packs"], tables["gis_intervals"]
    changes: List[dict] = []
    if not len(p) or not file_alt:
        return pd.DataFrame(columns=["Скважина", "Дата", "Пачка", "ГВК MD, м", "ГВК а.о. было, м", "ГВК а.о. стало, м", "Альтитуда была, м", "Альтитуда стала, м", "Источник"])
    p["altitude_prev_m"] = p.get("altitude_m")
    p["gvk_abs_prev_m"] = p.get("gvk_abs_m")
    p["alt_source"] = "БД"
    for idx, r in p.iterrows():
        alt = file_alt.get(r["well"])
        if alt is None:
            continue
        p.at[idx, "altitude_m"], p.at[idx, "alt_source"] = alt, "файл альтитуд"
        md = pd.to_numeric(pd.Series([r.get("gvk_depth_m")]), errors="coerce").iloc[0]
        if pd.notna(md):
            new = round(alt - md, 2)
            p.at[idx, "gvk_abs_m"] = new
            old = r.get("gvk_abs_m")
            if pd.isna(old) or abs(old - new) > ALT_TOL:
                changes.append({"Скважина": r["well"], "Дата": r["date"], "Пачка": r.get("pack"), "ГВК MD, м": md, "ГВК а.о. было, м": old, "ГВК а.о. стало, м": new,
                                "Альтитуда была, м": r.get("altitude_prev_m"), "Альтитуда стала, м": alt, "Источник": r["db_source"]})
    if len(iv) and "gvk_abs_m" in iv.columns:
        md = {(r["well"], r["month"], r.get("pack")): r["gvk_depth_m"] for _i, r in p.iterrows() if pd.notna(r.get("gvk_depth_m"))}
        iv["gvk_abs_prev_m"] = iv["gvk_abs_m"]
        for idx, r in iv.iterrows():
            alt, m = file_alt.get(r["well"]), md.get((r["well"], r["month"], r.get("pack")))
            if alt is not None and m is not None and pd.notna(r["gvk_abs_m"]):
                iv.at[idx, "gvk_abs_m"] = round(alt - m, 2)
    return pd.DataFrame(changes)


def merge(first: Dict[str, pd.DataFrame], second: Dict[str, pd.DataFrame], file_alt: Optional[Dict[str, float]] = None,
          keep_first: Set[Tuple[str, str]] = frozenset()) -> Dict[str, pd.DataFrame]:
    """Все листы отчёта + таблицы для Атласа под ключами ``gis_*``."""
    file_alt = file_alt or {}
    tables, decisions = choose(first, second, keep_first)
    alts = altitude_table(first, second, file_alt)
    changes = apply_altitudes(tables, file_alt)
    disputed = gis_compare.compare(first, second)
    both = set(zip(decisions.loc[decisions["Почему"].str.startswith("есть в обеих") | decisions["Почему"].str.startswith("по решению"), "Скважина"],
                   decisions.loc[decisions["Почему"].str.startswith("есть в обеих") | decisions["Почему"].str.startswith("по решению"), "Месяц"]))
    pk = disputed["Пачки"]
    pk = pk[[(w, m) in both for w, m in zip(pk["Скважина"], pk["Месяц"])]] if len(pk) else pk
    n = decisions["Источник"].value_counts()
    summary = pd.DataFrame([
        {"Показатель": "Замеров взято из первой БД (Excel)", "Значение": int(n.get(FIRST, 0))},
        {"Показатель": "Замеров взято из второй БД (отчёты)", "Значение": int(n.get(SECOND, 0))},
        {"Показатель": "из них есть в обеих: вторая перекрыла первую", "Значение": int(decisions["Почему"].str.startswith("есть в обеих").sum())},
        {"Показатель": "Спорных значений (пачки, обе БД)", "Значение": len(pk)},
        {"Показатель": "Возможных дублей с другой датой", "Значение": int((decisions["Подсказка"] != "").sum())},
        {"Показатель": "Скважин с альтитудой из файла", "Значение": int(alts["Альтитуда файла, м"].notna().sum()) if len(alts) else 0},
        {"Показатель": "ГВК а.о. изменено пересчётом", "Значение": len(changes)},
        {"Показатель": "Как читать", "Значение": "Вторая БД главнее, но это правило-подсказка: «Решения» показывают причину по каждому замеру, список «взять из первой» меняет решение. Альтитуды — из файла Атласа."}])
    return {**tables, "Сводка": summary, "Решения": decisions, "Альтитуды": alts, "Пересчёт а.о.": changes, "Спорные": pk}


REPORT = ("Сводка", "Решения", "Альтитуды", "Пересчёт а.о.", "Спорные")


def export(first_dir: str, second_dir: str, out_dir: str, altitudes: str = "", keep_first: str = "") -> Tuple[str, Dict[str, pd.DataFrame]]:
    os.makedirs(out_dir, exist_ok=True)
    file_alt, label = load_altitudes(altitudes) if altitudes else ({}, "")
    res = merge(gis_compare.load_db(first_dir), gis_compare.load_db(second_dir), file_alt, load_keep_first(keep_first))
    tables = {n: res[n].drop(columns=["month"], errors="ignore") for n in gis_compare.TABLES}
    gis_export.write_tables(tables, out_dir, "объединение: %s + %s%s" % (os.path.basename(first_dir), os.path.basename(second_dir), "; альтитуды: " + label if label else ""))
    path = os.path.join(out_dir, "Объединённая_БД_ГИС.xlsx")
    with pd.ExcelWriter(path, engine="xlsxwriter", datetime_format="dd.mm.yyyy", date_format="dd.mm.yyyy") as xw:
        for name in REPORT:
            res[name].to_excel(xw, sheet_name=name, index=False)
            xw.sheets[name].freeze_panes(1, 0)
            xw.sheets[name].set_column(0, 12, 16)
            xw.sheets[name].set_column(3, 3, 40 if name != "Решения" else 16)
        for name, df in tables.items():
            df.to_excel(xw, sheet_name=name[4:].replace("observations", "замеры").replace("packs", "пачки").replace("intervals", "интервалы"), index=False)
    return path, res
