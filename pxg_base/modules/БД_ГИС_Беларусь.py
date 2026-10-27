"""БД ГИС Беларусь: заключения ГИС в Word (.doc/.docx) → «БД_ГИС_Беларусь.xlsx» и таблицы gis_*.csv для Газового Атласа.

Шапка таблицы в заключении — настоящая таблица Word, строки данных — обычный текст с пробелами и табуляциями: строки ищутся
по содержимому (`pxg_core.gis_word`), Word и LibreOffice не нужны. В книге: «Свод» (по пачкам), «Интервалы» (от-до по стволу и
а.о., мощность, Кг, ГВК; горизонт и пачка отдельными столбцами), «Замеры», «Скважины» (шапка заключения: перфорация, альтитуда,
забой, НКТ), «Горизонты» (как разобраны метки; правится и подаётся обратно), «Не распознано», «Проверка».
Параметры: --files (файлы и папки, по одному в строке), --mapping (сопоставление меток), --depth (auto — с учётом отклонения, если оно есть в заключении; md — по стволу; incl), --kg-min (порог Кг для hэф, доля; по умолчанию 0 — все перечисленные интервалы). Результаты — в текущую папку.
"""
from __future__ import annotations

import os
import sys

from pxg_core import gis_word, параметры
from pxg_core.parallel import map_jobs

_ = sys


def _paths(value: str) -> list:
    return [x.strip().strip('"') for x in (value or "").splitlines() if x.strip()]


def read_all(files, mapping):
    """Разбор заключений: по ядрам, если файлов много."""
    jobs = [(f, mapping) for f in files]
    if len(jobs) > 8:
        return list(map_jobs(_read_job, jobs, 120.0))
    return [_read_job(j) for j in jobs]


def _read_job(job):
    return gis_word.read_conclusion(job[0], job[1])


def main(argv=None):
    args = параметры.parse(
        "БД ГИС Беларусь", argv,
        files="заключения ГИС (.doc/.docx), файлы или папки, по одному пути в строке",
        mapping="файл сопоставления меток горизонтов (Excel/CSV, лист «Горизонты» прежней выгрузки), необязательно",
        depth="auto — с учётом отклонения, если заключение его даёт (по умолчанию), md — по стволу, incl — всегда с отклонением",
        kg_min="порог Кг для hэф, доля единицы (0 — все интервалы)")
    paths = _paths(args.files)
    if not paths:
        one = параметры.ask_path("Заключения ГИС: файл или папка", args.files if args.files is not None else None, "folder")
        paths = [one] if one else []
    files = gis_word.find_files(paths)
    if not files:
        print("⚠️ Файлов .doc/.docx не найдено.")
        return 0
    mapping = gis_word.load_mapping(параметры.clean_path(args.mapping or ""))
    depth = (args.depth or "auto").strip().lower()
    depth = depth if depth in ("md", "incl") else "auto"
    kg_min = float((args.kg_min or "0").replace(",", ".") or 0)
    print("📚 Заключений: %d" % len(files))
    conclusions = read_all(files, mapping)
    for c in conclusions:
        if c.error:
            print("❌ %s: %s" % (c.file, c.error))
    ok = [c for c in conclusions if not c.error]
    print("📊 Прочитано: %d, строк интервалов: %d, скважин: %d" % (
        len(ok), sum(len(c.rows) for c in ok), len({c.sheet for c in ok})))
    lost = sum(len(c.unresolved) for c in ok)
    if lost:
        print("⚠️ Не распознано строк: %d — лист «Не распознано»" % lost)
    noh = sum(1 for c in ok for r in c.rows if not r.horizon)
    if noh:
        print("⚠️ Строк без горизонта: %d — в таблицы для Атласа не попадут" % noh)
    out, frames = gis_word.export(ok, os.getcwd(), depth, kg_min, mapping, source="; ".join(paths))
    for f in out:
        print("✅ %s" % os.path.basename(f))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
