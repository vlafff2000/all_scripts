"""Проверка исходников «Сбора БД замеров воды»: месячные файлы выноса воды, разбор как в «Картах ГСП»."""
from __future__ import annotations

import os
from typing import Dict

from gsp_maps.inputs import load_water
from pxg_core import qc
from pxg_core.qc import Report


def check_water(values: Dict[str, str]) -> Report:
    rep = Report(title="Сбор БД замеров воды")
    folder = (values.get("folder") or "").strip()
    if not qc.check_path(rep, folder, "Папка с файлами замеров воды", "folder"):
        if not folder:
            rep.error("FILE", "Не указана папка с файлами замеров воды")
        return rep
    db = (values.get("db") or "").strip()
    if db:
        qc.check_path(rep, db, "Прежняя база")
    files = [f for f in qc.list_excel(folder) if not os.path.basename(f).startswith("~$")]
    if not files:
        rep.note("FILE", "В папке нет файлов Excel", file=folder)
        return rep
    raw, warn = load_water(files)
    for text in warn:
        rep.warn("WATER", text)
    if raw.empty:
        rep.error("WATER", "Замеры воды не найдены ни в одном файле")
        return rep
    rep.saw("%d файл(ов), %d записей (скважина × месяц), %d скважин" % (len(files), len(raw), raw["Скважина"].nunique()))
    unknown = int(raw["Расход_воды_лч"].isna().sum())
    if unknown:
        rep.note("WATER", "Записей без данных (песок, ремонт): %d — объём за месяц не считается" % unknown)
    return rep
