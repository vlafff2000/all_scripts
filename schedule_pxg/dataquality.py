"""Проверка данных (Скедул): «ненормальные» строки в базе расходов и в эталонном суточном объёме.

Правила взяты из «Проверки данных» Газового Атласа (`atlas/quality.py`) и приведены к таблице истории
(`history.COLUMNS`: скважина, дата, расход, часы, вид). Только поиск: само ничего не исключается. Строку можно
исключить из расчётов — отметка хранится в проекте (`sources.excluded_rows`), исходные файлы не меняются.
Идентификатор строки: «набор|скважина|дата|вид», набор — `flows` (база расходов) или `daily` (эталон). Python 3.8+.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

import pandas as pd

LIMIT = 2000                 # находок одной проверки; дальше только счётчик
GAP_DAYS = (3, 45)           # пропуск суточных записей: от и до дней (длиннее — перерыв между сезонами)
FLOWS, DAILY = "flows", "daily"
LABELS = {FLOWS: "База расходов", DAILY: "Эталонный суточный объём"}
COLUMNS = ["dataset", "id", "well", "date", "kind", "check", "level", "value", "details"]
ERR, WARN = "ошибка", "внимание"


@dataclass(frozen=True)
class Limits:
    jump: float = 3.0        # скачок расхода: во сколько раз отличается от соседних суток


def row_ids(df: pd.DataFrame, dataset: str) -> pd.Series:
    d = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    return dataset + "|" + df["well"].astype(str) + "|" + d + "|" + df["kind"].astype(str)


def drop_excluded(df: pd.DataFrame, dataset: str, ids: Set[str]) -> pd.DataFrame:
    if not ids or df.empty:
        return df
    return df[~row_ids(df, dataset).isin(ids)].reset_index(drop=True)


def _fmt(v, digits: int = 1) -> str:
    return "" if pd.isna(v) else ("{:,.%df}" % digits).format(v).replace(",", " ").replace(".", ",")


def _find(d: pd.DataFrame, mask, check: str, level: str, value, details: str, dataset: str) -> pd.DataFrame:
    rows = d[mask]
    if rows.empty:
        return pd.DataFrame(columns=COLUMNS)
    vals = value(rows) if callable(value) else value
    out = pd.DataFrame({"dataset": dataset, "id": row_ids(rows, dataset).to_numpy(), "well": rows["well"].astype(str).to_numpy(),
                        "date": pd.to_datetime(rows["date"], errors="coerce").to_numpy(), "kind": rows["kind"].astype(str).to_numpy(),
                        "check": check, "level": level, "value": vals.to_numpy() if isinstance(vals, pd.Series) else vals,
                        "details": details})
    return out.head(LIMIT)


def scan_frame(df: pd.DataFrame, dataset: str, limits: Optional[Limits] = None) -> pd.DataFrame:
    """Находки по таблице истории (`well`, `date`, `rate`, `hours`, `kind`)."""
    limits = limits or Limits()
    if df is None or df.empty or not {"well", "date", "rate"} <= set(df.columns):
        return pd.DataFrame(columns=COLUMNS)
    d = df.copy()
    for c, default in (("hours", float("nan")), ("kind", "")):
        if c not in d:
            d[c] = default
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.sort_values(["well", "kind", "date"], kind="stable").reset_index(drop=True)
    keys = ["well", "kind"]
    q, hrs = d["rate"], d["hours"]
    out = [
        _find(d, q.lt(0), "Отрицательный расход", ERR, lambda r: r["rate"].map(_fmt), "Расход не может быть меньше нуля.", dataset),
        _find(d, hrs.notna() & (hrs.lt(0) | hrs.gt(24)), "Часы работы вне 0–24", ERR, lambda r: r["hours"].map(_fmt),
              "В сутках от 0 до 24 часов работы.", dataset),
        _find(d, d.duplicated(keys + ["date"], keep=False) & d["date"].notna(), "Повтор даты", ERR, lambda r: r["rate"].map(_fmt),
              "На одну дату несколько строк: при исключении уходят все строки этой даты, оставьте верную в исходнике.", dataset),
    ]
    g = d.groupby(keys, sort=False)["rate"]
    prev, nxt = g.shift(1), g.shift(-1)
    around = pd.concat([g.shift(i) for i in (1, 2, 3, -1, -2, -3)], axis=1).where(lambda x: x.gt(0)).median(axis=1)
    ratio = q / around
    jump = q.gt(0) & around.gt(0) & ((ratio >= limits.jump) | (ratio <= 1 / limits.jump))
    show = lambda r: ratio[r.index].map(lambda x: "" if pd.isna(x) else (("в %.1f раза выше" % x) if x >= 1 else ("в %.1f раза ниже" % (1 / x))).replace(".", ","))
    out.append(_find(d, jump, "Скачок расхода", WARN, show, "Расход отличается от соседних суток не менее чем в %g раза: возможна опечатка, "
                     "ошибка единиц или остановка." % limits.jump, dataset))
    out.append(_find(d, q.eq(0) & prev.gt(0) & nxt.gt(0), "Ноль посреди работы", WARN, "0",
                     "Нулевой расход между двумя сутками с расходом: остановка на сутки или пропуск записи.", dataset))
    out.append(_find(d, q.gt(0) & hrs.eq(0), "Расход при нуле часов", WARN, lambda r: r["rate"].map(_fmt),
                     "Скважина «не работала», а расход есть: проверьте часы или расход.", dataset))
    step = d.groupby(keys, sort=False)["date"].diff().dt.days
    out.append(_find(d, step.gt(GAP_DAYS[0]) & step.le(GAP_DAYS[1]), "Пропуск записей", WARN,
                     lambda r: step[r.index].map(lambda n: "" if pd.isna(n) else "%d сут." % (n - 1)),
                     "Между соседними записями нет суточных данных: график проведёт линию через пропуск.", dataset))
    found = [f for f in out if not f.empty]
    return pd.concat(found, ignore_index=True)[COLUMNS] if found else pd.DataFrame(columns=COLUMNS)


def daily_frame(total: pd.DataFrame) -> pd.DataFrame:
    """Эталон («Дата», «Объем») в виде таблицы истории для тех же проверок."""
    if total is None or total.empty:
        return pd.DataFrame(columns=["well", "date", "rate", "hours", "kind"])
    return pd.DataFrame({"well": "", "date": total["Дата"], "rate": total["Объем"], "hours": float("nan"), "kind": ""})


def scan(flows: Optional[pd.DataFrame], daily: Optional[pd.DataFrame], limits: Optional[Limits] = None) -> pd.DataFrame:
    parts = [scan_frame(flows, FLOWS, limits) if flows is not None else None,
             scan_frame(daily_frame(daily), DAILY, limits) if daily is not None else None]
    parts = [p for p in parts if p is not None and not p.empty]
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    out = pd.concat(parts, ignore_index=True)
    out["_o"] = out["level"].map({ERR: 0, WARN: 1})
    out = out.sort_values(["_o", "dataset", "check", "well", "date"], kind="stable").drop(columns="_o")
    return out.reset_index(drop=True)[COLUMNS]


def summary(found: pd.DataFrame) -> pd.DataFrame:
    if found.empty:
        return pd.DataFrame(columns=["dataset", "check", "level", "count"])
    out = found.groupby(["dataset", "check", "level"], sort=False).size().reset_index(name="count")
    out["_o"] = out["level"].map({ERR: 0, WARN: 1})
    return out.sort_values(["_o", "count"], ascending=[True, False], kind="stable").drop(columns="_o").reset_index(drop=True)
