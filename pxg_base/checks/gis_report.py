"""Проверка исходников «БД ГИС из отчётов»: отчёты читаются тем же разбором, что и запуск."""
from __future__ import annotations

from typing import Dict

from pxg_core import archives, gis_report, qc
from pxg_core.qc import Report

LEVEL = {"error": qc.ERROR, "warn": qc.WARN, "note": qc.NOTE}
LABELS = {"no_well": "Нет номера скважины", "no_date": "Нет даты исследования", "date_from_name": "Дата из имени файла", "no_alt": "Нет альтитуды",
          "no_complex": "Нет таблицы комплекса ГИС", "no_thermo": "Нет температуры и давления", "no_filling": "Нет заполнения ствола",
          "no_intervals": "Нет таблицы интервалов", "no_template": "Нет дохода шаблона/прибора", "pack_unknown": "Пачка не определена",
          "gvk_abs": "ГВК: а.о. не сходится с альтитудой", "gvk_boundary": "ГВК не на границе газового интервала", "hg_mismatch": "Нг не сходится с таблицей",
          "kg_range": "Кг вне 0–100 %", "interval_order": "Подошва выше кровли", "intervals_empty": "Таблица интервалов без строк",
          "thermo_empty": "Таблица термобарики без значений", "unreadable": "Файл не прочитан", "archive": "Архив не открыт"}


def check_gis_report(values: Dict[str, str]) -> Report:
    rep = Report(title="БД ГИС из отчётов")
    paths = [x.strip().strip('"') for x in (values.get("files") or "").splitlines() if x.strip()]
    if not paths:
        rep.error("FILE", "Не указаны отчёты ГИС")
        return rep
    files, notes, tmp = archives.expand(paths)
    try:
        for n in notes:
            rep.warn("archive", n)
        if not files:
            rep.note("FILE", "Файлов .doc/.docx не найдено")
            return rep
        mapping = gis_report.load_mapping((values.get("mapping") or "").strip())
        reports = [gis_report.parse_file(f, mapping) for f in files]
        for r in reports:
            for i in r.issues:
                rep.add(LEVEL[i["Уровень"]], i["Код"], i["Сообщение"], file=r.file, well=r.well, row=i["Где"])
        rep.saw("%d отчётов, %d скважин, %d строк интервалов" % (len(reports), len({r.well for r in reports if r.well}), sum(len(r.intervals) for r in reports)))
    finally:
        tmp.cleanup()
    return rep


def check_gis_construction(values: Dict[str, str]) -> Report:
    """Проверка исходников «БД конструкций из отчётов ГИС»: сколько отчётов и в скольких есть таблица конструкции."""
    from pxg_core import gis_construction
    rep = Report(title="БД конструкций из отчётов ГИС")
    paths = [x.strip().strip('"') for x in (values.get("files") or "").splitlines() if x.strip()]
    if not paths:
        rep.error("FILE", "Не указаны отчёты ГИС")
        return rep
    files, notes, tmp = archives.expand(paths, (".doc", ".docx", ".md"))
    try:
        for n in notes:
            rep.warn("archive", n)
        files = [f for f in files if not f.lower().endswith(".md") or f.lower().endswith(".ocr.md")]
        if not files:
            rep.note("FILE", "Файлов .doc/.docx и вывода OCR (*.ocr.md) не найдено")
            return rep
        reports, bad = gis_construction.read_files(files)
        for b in bad:
            rep.warn("FILE", b)
        with_table = sum(1 for _r, t, _p in reports if t is not None)
        rep.saw("%d отчётов, с таблицей конструкции %d" % (len(reports), with_table))
    finally:
        tmp.cleanup()
    return rep


qc.CODES.update(LABELS)
