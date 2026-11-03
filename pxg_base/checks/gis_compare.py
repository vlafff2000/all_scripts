"""Проверка исходников «Сравнение БД ГИС»: обе папки читаются тем же загрузчиком."""
from __future__ import annotations

from typing import Dict

from pxg_core import gis_compare, qc
from pxg_core.qc import Report


def check_gis_compare(values: Dict[str, str]) -> Report:
    rep = Report(title="Сравнение БД ГИС")
    for key, label in (("a", "Прежняя БД ГИС (А)"), ("b", "Новая БД ГИС (Б)")):
        p = (values.get(key) or "").strip()
        if not p:
            rep.error("FILE", "Не указана папка: " + label)
            continue
        qc.check_path(rep, p, label, "folder")
        try:
            db = gis_compare.load_db(p)
            rep.saw("%s: замеров %d, пачек %d, интервалов %d" % (label, len(db["gis_observations"]), len(db["gis_packs"]), len(db["gis_intervals"])))
        except Exception as e:
            rep.error("FILE", str(e), file=p)
    return rep
