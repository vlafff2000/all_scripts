"""Проверка исходников модуля «Сравнение БД шаблонирования»."""
from __future__ import annotations

from typing import Dict

from pxg_core import qc, templating_db
from pxg_core.qc import Report


def check_templating_compare(values: Dict[str, str]) -> Report:
    rep = Report(title="Сравнение БД шаблонирования")
    for key, label in (("old", "Прежняя БД"), ("new", "Новая БД")):
        p = (values.get(key) or "").strip()
        if not p:
            rep.error("FILE", "Не указана " + label)
            continue
        qc.check_path(rep, p, label, "file")
        try:
            df, _n = templating_db.load_for_compare(p)
            rep.saw("%s: отбивок %d, скважин %d" % (label, len(df), df["Скважина"].nunique()))
        except Exception as e:
            rep.error("FILE", str(e), file=p)
    tol = (values.get("tol") or "").strip()
    if tol:
        try:
            float(tol.replace(",", "."))
        except ValueError:
            rep.error("DATA", "Допуск должен быть числом (метры): " + tol)
    return rep
