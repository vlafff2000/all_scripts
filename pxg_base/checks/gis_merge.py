"""Проверка исходников «Объединение БД ГИС»: обе папки и файлы читаются теми же загрузчиками."""
from __future__ import annotations

from typing import Dict

from pxg_core import gis_compare, gis_merge, qc
from pxg_core.qc import Report


def check_gis_merge(values: Dict[str, str]) -> Report:
    rep = Report(title="Объединение БД ГИС")
    for key, label in (("a", "Первая БД ГИС (Excel)"), ("b", "Вторая БД ГИС (отчёты)")):
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
    alt = (values.get("altitudes") or "").strip()
    if alt:
        qc.check_path(rep, alt, "Файл альтитуд", "file")
        try:
            rep.saw("Файл альтитуд: скважин %d" % len(gis_merge.load_altitudes(alt)[0]))
        except Exception as e:
            rep.error("FILE", str(e), file=alt)
    else:
        rep.warn("FILE", "Файл альтитуд не указан: а.о. останутся такими, как в БД (в одной из БД альтитуда может быть неверной)")
    keep = (values.get("keep_first") or "").strip()
    if keep:
        qc.check_path(rep, keep, "Файл решений «взять из первой»", "file")
        try:
            rep.saw("Решений «взять из первой»: %d" % len(gis_merge.load_keep_first(keep)))
        except Exception as e:
            rep.error("FILE", str(e), file=keep)
    return rep
