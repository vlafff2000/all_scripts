"""БД ГИС из отчётов: Word-отчёты по ГИС-контролю (.doc/.docx, в том числе внутри архивов ZIP/TAR/RAR) → «БД_ГИС_из_отчётов.xlsx» и таблицы.

Из каждого отчёта берутся: выполненный комплекс ГИС, доход шаблона / остановка прибора (отдельная БД шаблонировок), термобарические
условия (давление и температура по глубинам, в таблице или в тексте), заполнение ствола, таблицы результатов интерпретации по пачкам
(в том числе покрышка, перемычка, «поиск вторичных скоплений газа») с ГВК в MD и а.о., таблица ГВК по датам. Разбор — `pxg_core.gis_report`:
по структуре таблиц Word, без Word и LibreOffice. У каждого значения — источник (таблица, строка), уверенность и основание решения;
решения программы (пачка по заголовку, среднее по диапазону Кг, ГВК по границе газ/вода) — подсказки, правятся листом «Заголовки пачек».
Параметры: --files (файлы, папки, архивы, по одному в строке), --mapping (сопоставление заголовков пачек), --kg-min (порог Кг для hэф, доля).
Результаты — в текущую папку. Для RAR нужен пакет rarfile и программа unrar/unar/7z; если её нет, об этом сказано в выводе.
"""
from __future__ import annotations

import os
import sys

from pxg_core import archives, gis_report, параметры
from pxg_core.parallel import map_jobs

_ = sys


def _paths(value: str) -> list:
    return [x.strip().strip('"') for x in (value or "").splitlines() if x.strip()]


def _read_job(job):
    return gis_report.parse_file(job[0], job[1])


def read_all(files, mapping):
    jobs = [(f, mapping) for f in files]
    if len(jobs) > 8:
        return list(map_jobs(_read_job, jobs, 120.0))
    return [_read_job(j) for j in jobs]


def main(argv=None):
    args = параметры.parse(
        "БД ГИС из отчётов", argv,
        files="отчёты ГИС (.doc/.docx), папки и архивы (ZIP, TAR, RAR), по одному пути в строке",
        mapping="файл сопоставления заголовков пачек (Excel/CSV, лист «Заголовки пачек» прежней выгрузки), необязательно",
        kg_min="порог Кг для hэф, доля единицы (0 — порог 25 %)")
    paths = _paths(args.files)
    if not paths:
        one = параметры.ask_path("Отчёты ГИС: файл, папка или архив", args.files if args.files is not None else None, "folder")
        paths = [one] if one else []
    files, notes, tmp = archives.expand(paths)
    try:
        for n in notes:
            print("⚠️ %s" % n)
        if any(p.lower().endswith(".rar") for p in paths) or any(".rar" in n for n in notes):
            ok_rar, why = archives.rar_support()
            print(("ℹ️ RAR: " if ok_rar else "⚠️ RAR: ") + why)
        if not files:
            print("⚠️ Файлов .doc/.docx не найдено.")
            return 0
        mapping = gis_report.load_mapping(параметры.clean_path(args.mapping or ""))
        kg_min = float((args.kg_min or "0").replace(",", ".") or 0)
        print("📚 Отчётов: %d" % len(files))
        reports = read_all(files, mapping)
        for r in reports:
            if r.error:
                print("❌ %s: %s" % (r.file, r.error))
        good = [r for r in reports if not r.error]
        print("📊 Прочитано: %d, скважин: %d, строк интервалов: %d, точек давления/температуры: %d, строк комплекса ГИС: %d" % (
            len(good), len({r.well for r in good}), sum(len(r.intervals) for r in good), sum(len(r.thermo) for r in good), sum(len(r.complex) for r in good)))
        for code, label in (("no_intervals", "без таблицы интервалов"), ("no_thermo", "без температуры и давления"), ("no_template", "без дохода шаблона/прибора"),
                            ("pack_unknown", "с пачкой, не определённой по заголовку")):
            n = sum(1 for r in reports for i in r.issues if i["Код"] == code)
            if n:
                print("⚠️ Отчётов %s: %d — лист «Проверка»" % (label, n))
        # дубли замеров из разных отчётов
        out, _frames = gis_report.export(good, os.getcwd(), mapping, kg_min, source="; ".join(paths))
        for f in out:
            print("✅ %s" % os.path.basename(f))
        return 0 if good else 1
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
