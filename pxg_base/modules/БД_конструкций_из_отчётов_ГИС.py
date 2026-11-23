"""БД конструкций скважин из отчётов ГИС: таблица «Конструкция скважины и подземного оборудования» (графы «по промысловым данным» и «по данным ГИС»).

По каждой скважине берётся самый свежий отчёт, в котором такая таблица есть. Две книги в формате шаблона конструкции Атласа (лист «Конструкция»):
  «Конструкции_из_ГИС_исходные_данные.xlsx» — глубины из графы «по промысловым данным»;
  «Конструкции_из_ГИС_по_данным_ГИС.xlsx» — глубины из графы «по данным ГИС» (положение НКТ, фильтра, расширки и т. п.); где ГИС элемент не определил, берётся
  исходное значение, это видно в столбце «Источник глубины».
Листы: «Скважины», «Замеры забоя», «Условия», «Отчёты с конструкцией», «Проверка». Разбор — `pxg_core.gis_construction`; последнее слово за инженером.
Параметры: --files (файлы .doc/.docx, вывод OCR *.ocr.md, папки, архивы; по одному в строке), --shift (1/0: сдвигать меры элементов, которые ГИС не охватил,
по привязке к соседнему элементу; по умолчанию 1, это подсказка с причиной). Результаты — в текущую папку.
"""
from __future__ import annotations

import os
import re

from pxg_core import append_mode, archives, gis_construction as gc, параметры


# версия правил разбора отчётов: увеличивать при любой правке gis_construction.read_one / gis_report.parse_*
PARSE_VERSION = 1
SCHEMA_VERSION = "gis_construction-1"


def _paths(value: str) -> list:
    return [x.strip().strip('"') for x in (value or "").splitlines() if x.strip()]


def main(argv=None):
    args = параметры.parse(
        "БД конструкций из отчётов ГИС", argv,
        files="отчёты ГИС (.doc/.docx, вывод OCR *.ocr.md), папки и архивы (ZIP, TAR, RAR), по одному пути в строке",
        short_reach="недоход прибора, м: если ИЗ глубже остановки прибора ГИС больше чем на столько, элементы ниже остановки берутся по промысловым данным (по умолчанию 0,5; 0 — выключить)",
        keep_gis="скважины, где оставить глубины ГИС несмотря на недоход (через запятую)",
        cache="папка кэша разбора отчётов (по умолчанию ~/.pxg/append_cache по набору входных путей)",
        **append_mode.FLAGS,
        shift="1/0: элементы, которые ГИС не охватил, — по мерам со сдвигом по привязке к соседнему элементу (по умолчанию 1)")
    paths = _paths(args.files)
    if not paths:
        one = параметры.ask_path("Отчёты ГИС: файл, папка или архив", args.files if args.files is not None else None, "folder")
        paths = [one] if one else []
    files, notes, tmp = archives.expand(paths, (".doc", ".docx", ".md"))
    try:
        for n in notes:
            print("⚠️ %s" % n)
        files = [f for f in files if not f.lower().endswith(".md") or f.lower().endswith(".ocr.md")]
        if not files:
            print("⚠️ Файлов .doc/.docx и вывода OCR (*.ocr.md) не найдено.")
            return 0
        print("📚 Файлов: %d" % len(files))
        cache = append_mode.ParseCache(
            append_mode.cache_dir("gis_construction", paths, параметры.clean_path(args.cache or "")), SCHEMA_VERSION, PARSE_VERSION)
        root = os.path.dirname(files[0]) if len(files) == 1 else os.path.commonpath(files)
        try:
            items, plan = append_mode.run_cached(
                cache, files, root, lambda paths: [gc.read_one(p) for p in paths],
                rebuild=параметры.yes(args.rebuild), drop_missing=параметры.yes(args.drop_missing),
                plan_only=параметры.yes(args.plan_only), rows_of=lambda it: 0 if it[1] is None else 1, cacheable=lambda it: not it[3])
        except append_mode.AppendError as e:
            print("❌ Дополнение невозможно: %s (параметр --rebuild=да)" % e)
            return 1
        print("🧩 %s" % append_mode.summary(plan))
        for _, row in plan[plan["Статус"] != append_mode.SAME].iterrows():
            print("   • %s: %s → %s (%s)" % (row["Файл"], row["Статус"], row["Действие"], row["Причина"]))
        if параметры.yes(args.plan_only):
            return 0
        append_mode.write_registry_xlsx(cache)
        reports, bad = gc.finish_reading(items)
        for b in bad:
            print("❌ %s" % b)
        thr = float((args.short_reach or "").replace(",", ".") or gc.SHORT_REACH_M)
        keep = [x.strip() for x in re.split(r"[,;\s]+", args.keep_gis or "") if x.strip()]
        frames = gc.build(reports, shift=параметры.yes(args.shift) if args.shift is not None else True, short_thr=thr, keep_gis=keep)
        wells = len(frames["Скважины"])
        with_table = sum(1 for _r, t, _p in reports if t is not None)
        print("📊 Отчётов %d, с таблицей конструкции %d, скважин %d; строк конструкции: %d (исходные) и %d (ГИС)" % (
            len(reports), with_table, wells, len(frames["initial"]), len(frames["gis"])))
        for p in gc.write(frames, os.getcwd()):
            print("✅ %s" % os.path.basename(p))
        return 0 if wells else 1
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
