"""Проверка исходников ГИС (этап А9): правила поверх разбора `pxg_core.gis`.

Правила только сообщают: у каждой находки есть причина и место (лист, строка), исключить её можно вручную
(`excluded` — набор пар «лист, строка»; исключённое не попадает в замечания и считается в «исключено вручную»).
Разбор уже сообщает о нераспознанной дате, листе без альтитуды, неизвестной заливке и втором ГВК в пачке; здесь — проверки
содержания: дыры и наложения интервалов, Кг и Кп вне диапазона, ГВК выше кровли, «прыжки» ГВК против сезона,
интервал глубже забоя прибора, пустой лист.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

from . import gis
from .gis import Issue

SETTINGS = {
    "gap_tol_m": 0.05,       # допуск на стыке интервалов (округление глубин)
    "gap_big_m": 10.0,       # дыра больше этого — предупреждение, меньше — заметка (на листах часто перечислены только коллекторы)
    "kg_max": 1.0,
    "kp_max": 0.5,
    "gvk_jump_m": 5.0,       # скачок ГВК между соседними замерами одной пачки, м
    "gvk_season_tol_m": 0.5, # допуск «против сезона»: осенью ГВК не выше весеннего, весной не ниже осеннего
}

# Подпись правила для таблицы замечаний
CODES = {
    "gap": "Дыра между интервалами", "overlap": "Наложение интервалов", "kg_range": "Кг вне 0–1", "kp_range": "Кп вне 0–0,5",
    "gvk_above_top": "ГВК выше кровли", "gvk_jump": "Скачок ГВК", "gvk_season": "ГВК против сезона",
    "below_bottom": "Интервал глубже забоя прибора", "empty_sheet": "Пустой лист",
}


def _fmt(x) -> str:
    return f"{x:g}"


def check_results(results: Dict[str, gis.SheetResult], bottom: Optional[pd.DataFrame] = None,
                  excluded: Iterable[Tuple[str, int]] = (), settings: Optional[dict] = None
                  ) -> Tuple[List[Issue], int]:
    """(находки, сколько исключено вручную). Находки разбора (`result.issues`) сюда не копируются."""
    cfg = {**SETTINGS, **(settings or {})}
    skip: Set[Tuple[str, int]] = set(excluded)
    out: List[Issue] = []
    dropped = 0

    def add(level, code, res, row, message, value=""):
        nonlocal dropped
        if (res.sheet, row) in skip:
            dropped += 1
        else:
            out.append(Issue(level, code, res.sheet, row, message, value))

    depth_by = {}
    if bottom is not None and len(bottom):
        for _, r in bottom.iterrows():
            if pd.notna(r["Дата"]):
                d = pd.Timestamp(r["Дата"])
                depth_by[(str(r["Скважина"]), d.year, d.month)] = float(r["Глубина, м"])

    for res in results.values():
        if not res.data_rows:
            add("warn", "empty_sheet", res, 0, "На листе нет ни одного интервала ГИС")
            continue
        for b in res.blocks:
            per_pack: Dict[str, List[gis.Row]] = defaultdict(list)
            for r in b.rows:
                if r.hi is None:
                    continue
                per_pack[r.pack or f"цвет {r.color}"].append(r)
                if r.kg is not None and (r.kg < 0 or r.kg > cfg["kg_max"]):
                    add("error", "kg_range", res, r.xl_row, f"Кг = {_fmt(r.kg)}: допустимо 0–{_fmt(cfg['kg_max'])}", _fmt(r.kg))
                if r.kp is not None and (r.kp < 0 or r.kp > cfg["kp_max"]):
                    add("warn", "kp_range", res, r.xl_row, f"Кп = {_fmt(r.kp)}: ждём 0–{_fmt(cfg['kp_max'])}", _fmt(r.kp))
                if b.date is not None and r.to is not None:
                    deep = depth_by.get((res.well, b.date.year, b.date.month))
                    if deep is not None and r.to > deep + cfg["gap_tol_m"]:
                        add("warn", "below_bottom", res, r.xl_row,
                            f"Интервал до {_fmt(r.to)} м, а прибор в этом месяце прошёл до {_fmt(deep)} м", _fmt(r.to))
            # соседи по глубине: дыра — между интервалами одной пачки, если между ними нет интервала другой пачки
            allrows = sorted((x for rows in per_pack.values() for x in rows if x.frm is not None and x.to is not None),
                             key=lambda x: (x.frm, x.to))
            for prev, nxt in zip(allrows, allrows[1:]):
                delta = nxt.frm - prev.to
                if delta > cfg["gap_tol_m"] and (prev.pack or prev.color) == (nxt.pack or nxt.color):
                    pack = prev.pack or f"цвет {prev.color}"
                    add("warn" if delta > cfg["gap_big_m"] else "note", "gap", res, nxt.xl_row,
                        f"Между интервалами «{pack}» дыра {_fmt(round(delta, 2))} м ({_fmt(prev.to)}–{_fmt(nxt.frm)}): "
                        "непроницаемый прослой или пропущенный интервал?",
                        _fmt(round(delta, 2)))
                elif delta < -cfg["gap_tol_m"]:
                    add("warn", "overlap", res, nxt.xl_row,
                        f"Интервалы накладываются на {_fmt(round(-delta, 2))} м: {_fmt(nxt.frm)} и {_fmt(prev.to)} "
                        f"(«{prev.pack or prev.color}», «{nxt.pack or nxt.color}»)", _fmt(round(-delta, 2)))
            for pack, rows in per_pack.items():
                top = rows[0].frm    # первая строка пачки в листе — кровля (метка «кровля N»)
                for x in rows:
                    if x.gvk_label and not x.gvk_extra and x.to is not None and top is not None and x.to < top - cfg["gap_tol_m"]:
                        add("error", "gvk_above_top", res, x.xl_row,
                            f"ГВК на {_fmt(x.to)} м выше кровли пачки «{pack}» ({_fmt(top)} м)", _fmt(x.to))

        # ГВК по замерам одной пачки: скачки и ход против сезона
        series: Dict[str, List[Tuple[gis.Block, gis.Row]]] = defaultdict(list)
        for b in res.blocks:
            if b.date is None:
                continue
            for r in b.rows:
                if r.gvk_label and not r.gvk_extra and r.gvk_abs is not None:
                    series[r.pack or f"цвет {r.color}"].append((b, r))
        for pack, items in series.items():
            items.sort(key=lambda t: (t[0].date, t[0].block))
            for (b0, r0), (b1, r1) in zip(items, items[1:]):
                diff = r1.gvk_abs - r0.gvk_abs      # минус = ГВК опустился (глубже)
                if abs(diff) > cfg["gvk_jump_m"]:
                    add("warn", "gvk_jump", res, r1.xl_row,
                        f"ГВК «{pack}» изменился на {_fmt(round(diff, 2))} м между {b0.date:%m.%Y} и {b1.date:%m.%Y}", _fmt(round(diff, 2)))
                tol = cfg["gvk_season_tol_m"]
                if b0.season == gis.SEASON_SPRING and b1.season == gis.SEASON_AUTUMN and diff > tol:
                    add("note", "gvk_season", res, r1.xl_row,
                        f"ГВК «{pack}» после закачки (осень {b1.date:%Y}) выше, чем после отбора (весна {b0.date:%Y}) на {_fmt(round(diff, 2))} м",
                        _fmt(round(diff, 2)))
                if b0.season == gis.SEASON_AUTUMN and b1.season == gis.SEASON_SPRING and diff < -tol:
                    add("note", "gvk_season", res, r1.xl_row,
                        f"ГВК «{pack}» после отбора (весна {b1.date:%Y}) ниже, чем после закачки (осень {b0.date:%Y}) на {_fmt(round(-diff, 2))} м",
                        _fmt(round(-diff, 2)))
    return out, dropped
