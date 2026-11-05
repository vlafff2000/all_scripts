"""БД конструкций скважин из отчётов ГИС: таблица «Конструкция скважины и подземного оборудования» (графы «по промысловым данным» и «по данным ГИС»).

По каждой скважине берётся самый свежий отчёт, в котором такая таблица есть. Две книги в формате шаблона конструкции Атласа (лист «Конструкция»):
  «Конструкции_из_ГИС_исходные_данные.xlsx» — глубины из графы «по промысловым данным»;
  «Конструкции_из_ГИС_по_данным_ГИС.xlsx» — глубины из графы «по данным ГИС» (положение НКТ, фильтра, расширки и т. п.); где ГИС элемент не определил, берётся
  исходное значение, это видно в столбце «Источник глубины».
Листы: «Скважины», «Замеры забоя», «Условия», «Отчёты с конструкцией», «Проверка». Разбор — `pxg_core.gis_construction`; последнее слово за инженером.
Параметры: --files (файлы .doc/.docx, вывод OCR *.ocr.md, папки, архивы; по одному в строке). Результаты — в текущую папку.
"""
from __future__ import annotations

import os

from pxg_core import archives, gis_construction as gc, параметры


def _paths(value: str) -> list:
    return [x.strip().strip('"') for x in (value or "").splitlines() if x.strip()]


def main(argv=None):
    args = параметры.parse(
        "БД конструкций из отчётов ГИС", argv,
        files="отчёты ГИС (.doc/.docx, вывод OCR *.ocr.md), папки и архивы (ZIP, TAR, RAR), по одному пути в строке")
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
        reports, bad = gc.read_files(files)
        for b in bad:
            print("❌ %s" % b)
        frames = gc.build(reports)
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
