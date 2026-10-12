"""Проверка исходников модуля «База_шахматка_Лена»: шахматки отбора/закачки и книга воды."""
from __future__ import annotations

import os
import tempfile
from typing import Dict

from pxg_core import qc, шахматка
from pxg_core.qc import Report


def check_shakhmatka(values: Dict[str, str]) -> Report:
    rep = Report(title="База шахматка (Лена)")
    paths = {k: (values.get(k) or "").strip() for k in ("otbor", "zakachka", "voda")}
    if not any(paths.values()):
        rep.error("FILE", "Не выбран ни один файл")
        return rep
    tmp = tempfile.mkdtemp()
    for key, kind, label in (("otbor", "отбор", "Шахматка отбора"), ("zakachka", "закачка", "Шахматка закачки")):
        path = paths[key]
        if not path or not qc.check_path(rep, path, label):
            continue
        try:
            wd = os.path.join(tmp, kind)
            os.makedirs(wd)
            sh = шахматка.Shakh(path, kind, шахматка._infer_year(path, 2000), wd)
        except (StopIteration, IndexError, KeyError, ValueError):
            rep.error("HEADER", "Не найдена шапка шахматки (строка «№№», блоки «Состояние»)", file=path)
            continue
        if not sh.blocks or not sh.day_cols:
            rep.error("HEADER", "В файле нет блоков скважин или суточных столбцов", file=path)
            continue
        for i in sh.issues:
            (rep.error if i["Уровень"] == "ошибка" else rep.warn)("FORMAT", "%s: %s" % (i["Вид"], i["Описание"]), file=path, hint=str(i["Где"]))
        rep.saw("%s: %d скважин, %d суток" % (label, len(sh.blocks), len(sh.day_cols)))
    if paths["voda"] and qc.check_path(rep, paths["voda"], "Книга воды"):
        try:
            season, daily = шахматка.read_water(paths["voda"])
            if season.empty:
                rep.note("EMPTY", "В листе «Данные» нет строк с датами", file=paths["voda"])
            else:
                rep.saw("Вода: %d сезонов, %d строк" % (season["Сезон"].nunique(), len(season)))
        except KeyError:
            rep.error("HEADER", "Нет листов «Данные» и «Water per day»", file=paths["voda"])
    return rep
