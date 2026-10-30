"""Проверка исходников «Состояния скважин и приоритета КР»: таблица «Анализ ревизии КРУ», вскрытия КРУ, сезон."""
from __future__ import annotations

import re
from typing import Dict

from pxg_core import krs, qc
from pxg_core.qc import Report


def check_krs(values: Dict[str, str]) -> Report:
    rep = Report(title="Состояние скважин и приоритет КР")
    table = (values.get("table") or "").strip()
    if not qc.check_path(rep, table, "Таблица «Анализ ревизии КРУ»"):
        if not table:
            rep.error("FILE", "Не указана таблица «Анализ ревизии КРУ»")
        return rep
    for key, label in (("kru", "Вскрытия КРУ нового сезона"), ("prev", "Прежний результат")):
        if (values.get(key) or "").strip():
            qc.check_path(rep, values[key].strip(), label)
    season = (values.get("season") or "").strip()
    if season and not re.fullmatch(r"20\d\d-20\d\d", season):
        rep.error("SEASON", "Сезон надо писать так: 2025-2026", file=season)
    try:
        data, _ = krs.parse(table)
    except Exception as exc:       # шапка не найдена, файл не читается
        rep.error("HEADER", str(exc), file=table)
        return rep
    rep.saw("%d скважин, %d ремонтов, %d записей по песку" % (len(data.wells), len(data.works), len(data.revisions)))
    for level, text in data.notes:
        (rep.warn if level == "предупреждение" else rep.note)("KRS", text)
    kru = (values.get("kru") or "").strip()
    if kru and not season and not data.columns.rev:
        rep.error("SEASON", "Укажите сезон вскрытий КРУ")
    elif kru:
        try:
            new = krs.read_new_revisions(kru)
            rep.saw("вскрытия КРУ: %d скважин, песок у %d" % (len(new), int(new["Песок"].eq("Да").sum())))
            known = set(data.wells["Скважина"])
            for w in new["Скважина"]:
                if w not in known:
                    rep.warn("WELL", "Скважины %d из вскрытий КРУ нет в таблице анализа" % w)
        except ValueError as exc:
            rep.error("HEADER", str(exc), file=kru)
    return rep
