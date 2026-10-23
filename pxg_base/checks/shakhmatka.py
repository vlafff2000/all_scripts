"""Проверка исходников модуля «База_шахматка_Лена»: шахматки отбора/закачки и книги воды."""
from __future__ import annotations

import os
import tempfile
from typing import Dict

from pxg_core import qc, шахматка
from pxg_core.parallel import map_jobs
from pxg_core.qc import Report


def _check_file(job):
    """Проверка одного файла: (отчёт по файлу, вид файла или "")."""
    n, path, tmp = job
    rep = Report()
    if not qc.check_path(rep, path, "Файл"):
        return rep, ""
    kind = шахматка.classify(path)
    if not kind:
        rep.warn("FORMAT", "Вид файла не опознан (ни шахматка, ни книга воды): файл будет пропущен", file=path)
        return rep, ""
    if kind == "вода":
        try:
            season, _daily = шахматка.read_water(path)
            if season.empty:
                rep.note("EMPTY", "В листе «Данные» нет строк с датами", file=path)
        except KeyError:
            rep.error("HEADER", "Нет листов «Данные» и «Water per day»", file=path)
        return rep, kind
    wd = os.path.join(tmp, str(n))
    os.makedirs(wd)
    try:
        sh = шахматка.Shakh(path, kind, шахматка._infer_year(path, 2000), wd)
    except (StopIteration, IndexError, KeyError, ValueError):
        rep.error("HEADER", "Не найдена шапка шахматки (строка «№№», блоки «Состояние»)", file=path)
        return rep, kind
    if not sh.blocks or not sh.day_cols:
        rep.error("HEADER", "В файле нет блоков скважин или суточных столбцов", file=path)
        return rep, kind
    for i in sh.issues:
        (rep.error if i["Уровень"] == "ошибка" else rep.warn)("FORMAT", "%s: %s" % (i["Вид"], i["Описание"]), file=path, hint=str(i["Где"]))
    rep.saw("%s (%s): %d скважин, %d суток" % (os.path.basename(path), kind, len(sh.blocks), len(sh.day_cols)))
    return rep, kind


def check_shakhmatka(values: Dict[str, str]) -> Report:
    rep = Report(title="База шахматка (Лена)")
    items = [x for x in (values.get("files") or "").splitlines() if x.strip()]
    for it in items:
        if not os.path.exists(it.strip().strip('"')) and not any(ch in it for ch in "*?["):
            rep.error("FILE", "Путь не найден", file=it)
    files = шахматка.expand_paths(items)
    if not files:
        rep.error("FILE", "Не выбрано ни одного файла Excel")
        return rep
    tmp = tempfile.mkdtemp()
    kinds = {"отбор": 0, "закачка": 0, "вода": 0}
    for sub, kind in map_jobs(_check_file, [(n, p, tmp) for n, p in enumerate(files)], 400):       # файлы независимы: по ядрам
        for i in sub.issues:
            rep.add(i.level, i.code, i.message, file=i.file, sheet=i.sheet, row=i.row, well=i.well, when=i.date, value=i.value, hint=i.hint)
        rep.checked.extend(sub.checked)
        if kind:
            kinds[kind] += 1
    rep.saw("Отбор: %d, закачка: %d, вода: %d файл(ов)" % (kinds["отбор"], kinds["закачка"], kinds["вода"]))
    return rep
