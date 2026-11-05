"""Сведение двух баз конструкций скважин (таблицы в формате шаблона конструкции Атласа) в одну проверенную.

База A — из «Шаблона конструкции из свода»: дата в ней ничего не значит, конструкция одна на скважину. База B — из Word: у скважины может быть
несколько дат; для сравнения берётся САМАЯ СВЕЖАЯ конструкция B (её дата показана в таблице), более ранние даты не проверяются и при сведении остаются как есть.
Ключ сравнения: скважина + элемент (+ порядковый номер однотипных элементов) в паре «A против самой свежей конструкции B». Расхождения — «только в A», «только в B», «глубины
различаются» (допуск настраивается), «диаметр различается». Автоматика — подсказка: на каждое расхождение предлагается решение с видимой причиной,
но последнее слово за инженером: он правит столбец «Решение» (A / B / вручную / исключить) и вносит свои глубины, затем свод собирается заново
с этим файлом, и ручное решение всегда главнее подсказки.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

TEMPLATE = ["Скважина", "Дата конструкции", "Элемент", "Верх интервала, м", "Низ интервала, м", "Наружный диаметр, мм",
            "Внутренний диаметр, мм", "Комментарий", "Комплект", "Ресурс"]
DIFF_COLUMNS = ["Скважина", "Дата конструкции", "Элемент", "Дата B (самая свежая)", "Расхождение", "A: верх", "A: низ", "A: диаметр", "B: верх", "B: низ", "B: диаметр",
                "Подсказка", "Причина подсказки", "Решение", "Вручную: верх", "Вручную: низ", "Вручную: диаметр", "Комментарий инженера"]
DECISIONS = ("A", "B", "вручную", "исключить")
TOLERANCE = 0.5          # м: глубины ближе допуска считаются совпадающими


def well_key(v) -> str:
    return re.sub(r"\s+", "", str(v)).replace(".0", "") if str(v).endswith(".0") else re.sub(r"\s+", "", str(v))


def read_base(path: str) -> pd.DataFrame:
    """Лист с таблицей конструкции (столбцы «Скважина», «Дата конструкции», «Элемент», «Верх», «Низ»): первый подходящий."""
    sheets = pd.read_excel(path, sheet_name=None)
    for name, df in sheets.items():
        cols = {str(c).strip(): c for c in df.columns}
        need = ["Скважина", "Дата конструкции", "Элемент", "Верх интервала, м", "Низ интервала, м"]
        if all(n in cols for n in need):
            out = pd.DataFrame({n: df[cols[n]] for n in TEMPLATE if n in cols})
            for n in TEMPLATE:
                if n not in out:
                    out[n] = None
            out = out[TEMPLATE].copy()
            out["Скважина"] = out["Скважина"].map(well_key)
            out["Дата конструкции"] = pd.to_datetime(out["Дата конструкции"], errors="coerce", dayfirst=True).dt.normalize()
            out["Элемент"] = out["Элемент"].astype(str).str.strip()
            for n in ("Верх интервала, м", "Низ интервала, м", "Наружный диаметр, мм", "Внутренний диаметр, мм"):
                out[n] = pd.to_numeric(out[n], errors="coerce")
            return out.dropna(subset=["Скважина", "Дата конструкции"]).reset_index(drop=True)
    raise ValueError("В файле %s нет листа конструкции со столбцами шаблона (Скважина, Дата конструкции, Элемент, Верх/Низ интервала)" % path)


def _close(a, b, tol) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    return not pd.isna(a) and not pd.isna(b) and abs(a - b) <= tol


def prepare(a: pd.DataFrame, b: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, List[str]]:
    """(A с датой самой свежей конструкции B, самая свежая конструкция B, более ранние конструкции B, заметки).
    Дата A не используется: у скважин, общих с B, она заменяется датой свежей конструкции B. Если в A у скважины несколько дат — берётся последняя."""
    notes: List[str] = []
    a = a.copy()
    multi = a.groupby("Скважина")["Дата конструкции"].nunique()
    if (multi > 1).any():
        notes.append("В базе A у %d скважин несколько дат: взята последняя (A должна быть из свода, одна конструкция на скважину)" % int((multi > 1).sum()))
        a = a[a["Дата конструкции"] == a.groupby("Скважина")["Дата конструкции"].transform("max")]
    latest = b.groupby("Скважина")["Дата конструкции"].transform("max")
    b_latest, b_older = b[b["Дата конструкции"] == latest].copy(), b[b["Дата конструкции"] != latest].copy()
    newest = b.groupby("Скважина")["Дата конструкции"].max()
    a["Дата конструкции"] = a["Скважина"].map(newest).fillna(a["Дата конструкции"])
    return a, b_latest, b_older, notes


def compare(a: pd.DataFrame, b: pd.DataFrame, tol: float = TOLERANCE, prefer: str = "B") -> pd.DataFrame:
    """Таблица расхождений с подсказкой. Пустая — базы совпадают. Элементы одного вида в снимке (несколько фильтров) сопоставляются по порядку."""
    rows = []
    a, b, _older, _notes = prepare(a, b)
    for df in (a, b):
        df["_n"] = df.sort_values(["Верх интервала, м", "Низ интервала, м"]).groupby(["Скважина", "Дата конструкции", "Элемент"]).cumcount().reindex(df.index)
    key = ["Скважина", "Дата конструкции", "Элемент", "_n"]
    m = a.merge(b, on=key, how="outer", suffixes=("_a", "_b"), indicator=True)
    prefer = "B" if str(prefer).upper() == "B" else "A"
    for _, r in m.sort_values(key[:3] + ["_n"], key=lambda s: s.map(lambda v: (0, int(v)) if str(v).isdigit() else (1, str(v)))).iterrows():
        kind = hint = reason = None
        if r["_merge"] == "left_only":
            kind, hint, reason = "только в A", "A", "элемент есть только в базе A: другой базе нечего противопоставить, берём найденное"
        elif r["_merge"] == "right_only":
            kind, hint, reason = "только в B", "B", "элемент есть только в базе B: другой базе нечего противопоставить, берём найденное"
        else:
            deep = not (_close(r["Верх интервала, м_a"], r["Верх интервала, м_b"], tol) and _close(r["Низ интервала, м_a"], r["Низ интервала, м_b"], tol))
            diam = not _close(r["Наружный диаметр, мм_a"], r["Наружный диаметр, мм_b"], 0.0) and not (pd.isna(r["Наружный диаметр, мм_a"]) or pd.isna(r["Наружный диаметр, мм_b"]))
            if deep or diam:
                kind = "глубины различаются" if deep else "диаметр различается"
                hint = prefer
                reason = "базы не сходятся (допуск %g м): автоматически выбрать нельзя, по умолчанию приоритет базы %s — проверьте по документам" % (tol, prefer)
        if kind:
            rows.append([r["Скважина"], r["Дата конструкции"], r["Элемент"], r["Дата конструкции"], kind,
                         r["Верх интервала, м_a"], r["Низ интервала, м_a"], r["Наружный диаметр, мм_a"],
                         r["Верх интервала, м_b"], r["Низ интервала, м_b"], r["Наружный диаметр, мм_b"], hint, reason, "", None, None, None, ""])
    return pd.DataFrame(rows, columns=DIFF_COLUMNS)


def read_decisions(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Расхождения")
    missing = [c for c in DIFF_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError("В файле решений нет столбцов: %s" % ", ".join(missing))
    df["Скважина"] = df["Скважина"].map(well_key)
    df["Дата конструкции"] = pd.to_datetime(df["Дата конструкции"], errors="coerce").dt.normalize()
    return df


def merge(a: pd.DataFrame, b: pd.DataFrame, diffs: pd.DataFrame, tol: float = TOLERANCE) -> Tuple[pd.DataFrame, List[str]]:
    """Сведённая база: совпавшее берётся как есть, расхождения — по столбцу «Решение» (если пусто — по подсказке, это отмечено в notes).
    Ручные значения главнее: «вручную» берёт «Вручную: …», пустые поля — из подсказанной базы."""
    a, b, older, notes = prepare(a, b)
    for df in (a, b):
        df["_n"] = df.sort_values(["Верх интервала, м", "Низ интервала, м"]).groupby(["Скважина", "Дата конструкции", "Элемент"]).cumcount().reindex(df.index)
    key = ["Скважина", "Дата конструкции", "Элемент", "_n"]
    out_rows = []
    m = a.merge(b, on=key, how="outer", suffixes=("_a", "_b"), indicator=True)
    dec = {}
    if diffs is not None and len(diffs):
        d = diffs.copy()
        d["_n"] = d.groupby(["Скважина", "Дата конструкции", "Элемент"]).cumcount()
        for _, r in d.iterrows():
            dec[(r["Скважина"], r["Дата конструкции"], r["Элемент"], r["_n"])] = r
    used_hint = 0
    for _, r in m.iterrows():
        k = (r["Скважина"], r["Дата конструкции"], r["Элемент"], r["_n"])
        pick = None
        if k in dec:
            x = dec[k]
            choice = str(x["Решение"]).strip()
            low = choice.lower()
            if low in ("", "nan"):
                pick, used_hint = str(x["Подсказка"]), used_hint + 1
            elif low in ("a", "а"):          # латинская и русская «А»
                pick = "A"
            elif low in ("b", "в"):
                pick = "B"
            elif low == "исключить":
                continue
            elif low == "вручную":
                pick = "manual"
            else:
                notes.append("Скважина %s %s: неизвестное решение «%s», взята подсказка" % (k[0], k[2], choice))
                pick, used_hint = str(x["Подсказка"]), used_hint + 1
        else:
            pick = "A" if r["_merge"] != "right_only" else "B"
        sfx = {"A": "_a", "B": "_b"}.get(pick)
        if pick == "manual":
            x = dec[k]
            base = "_a" if r["_merge"] != "right_only" else "_b"
            vals = {"Верх интервала, м": x["Вручную: верх"], "Низ интервала, м": x["Вручную: низ"], "Наружный диаметр, мм": x["Вручную: диаметр"]}
            row = {c: r.get(c + base) for c in TEMPLATE if c not in key}
            for c, v in vals.items():
                if not pd.isna(v):
                    row[c] = v
            row["Комментарий"] = ("Вручную; " + str(x["Комментарий инженера"])).strip("; ") if str(x["Комментарий инженера"]) != "nan" else "Вручную"
        else:
            sfx = sfx if r["_merge"] == "both" else ("_a" if r["_merge"] == "left_only" else "_b")
            if (pick == "A" and r["_merge"] == "right_only") or (pick == "B" and r["_merge"] == "left_only"):
                continue            # выбрана база, где элемента нет: значит элемент не берётся
            row = {c: r.get(c + sfx) for c in TEMPLATE if c not in key}
        out_rows.append({"Скважина": r["Скважина"], "Дата конструкции": r["Дата конструкции"], "Элемент": r["Элемент"], **row})
    if used_hint:
        notes.append("Для %d расхождений решение не указано: взята подсказка (причина — в файле расхождений)" % used_hint)
    out = pd.DataFrame(out_rows, columns=["Скважина", "Дата конструкции", "Элемент"] + [c for c in TEMPLATE if c not in key])[TEMPLATE]
    if len(older):
        out = pd.concat([out, older[TEMPLATE]], ignore_index=True)          # более ранние конструкции B не проверяются и не меняются
        notes.append("Более ранние конструкции B (%d строк) оставлены как есть" % len(older))
    return out.sort_values(["Скважина", "Дата конструкции"], kind="stable").reset_index(drop=True), notes
