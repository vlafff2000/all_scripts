"""Проверка исходников «БД ГИС Беларусь»: заключения Word читаются тем же разбором, что и запуск."""
from __future__ import annotations

from typing import Dict

from pxg_core import gis_word, qc
from pxg_core.qc import Report

LEVEL = {"error": qc.ERROR, "warn": qc.WARN, "note": qc.NOTE}
LABELS = {"no_horizon": "Горизонт не определён", "date_from_name": "Дата из имени файла", "no_date": "Нет даты исследований",
          "well_from_name": "Скважина из имени файла", "span_order": "Подошва не ниже кровли", "thickness": "Мощность не сходится",
          "abs_mismatch": "Абс. отметка не сходится с альтитудой", "total_mismatch": "Итог заключения не сходится",
          "no_rows": "Нет строк интервалов", "unresolved": "Строка не разобрана"}


def check_gis_word(values: Dict[str, str]) -> Report:
    rep = Report(title="БД ГИС Беларусь")
    paths = [x.strip().strip('"') for x in (values.get("files") or "").splitlines() if x.strip()]
    if not paths:
        rep.error("FILE", "Не указаны заключения ГИС")
        return rep
    for p in paths:
        qc.check_path(rep, p, "Заключения ГИС", "folder" if "." not in p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] else "file")
    files = gis_word.find_files(paths)
    if not files:
        rep.note("FILE", "Файлов .doc/.docx не найдено")
        return rep
    mapping = gis_word.load_mapping((values.get("mapping") or "").strip())
    cs = [gis_word.read_conclusion(f, mapping) for f in files]
    wells = set()
    for c in cs:
        if c.error:
            rep.error("FILE", "Файл не прочитан: " + c.error, file=c.file)
            continue
        wells.add(c.sheet)
        for i in c.issues:
            rep.add(LEVEL[i.level], i.code, i.message, file=c.file, well=c.sheet, row=i.row or "", value=i.value)
        for no, text, why in c.unresolved:
            rep.warn("unresolved", why, file=c.file, well=c.sheet, row=no, value=text)
    rep.saw("%d заключений, %d скважин, %d строк интервалов" % (len(cs), len(wells), sum(len(c.rows) for c in cs)))
    return rep


qc.CODES.update(LABELS)
