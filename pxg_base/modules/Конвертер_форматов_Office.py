"""Конвертер форматов Office: Excel, Word, презентации (пачкой, с подпапками).

Движок: LibreOffice, если найден; для .xls → .xlsx без него — запасной путь на Python (формулы заменяются значениями).
Исходные файлы не меняются. Результат кладётся рядом с исходным или в выбранную папку (с теми же подпапками).
Уже сконвертированные файлы пропускаются.
"""
import os
import sys

from pxg_core import параметры
from pxg_core import office_convert as oc


def read_paths():
    out = []
    while True:
        try:
            line = input().strip().strip('"')
        except EOFError:
            break
        if not line:
            break
        out.append(line)
    return out


def main():
    print("Конвертер форматов Office")
    print("Пути к файлам и папкам (по одному в строке, пустая строка — конец):")
    paths = read_paths()
    target = параметры.ask("Целевой формат (xlsx, xls, ods, csv, docx, doc, odt, rtf, pptx, ppt, odp, pdf)", "xlsx").lower().lstrip(".")
    dest = параметры.clean_path(параметры.ask("Папка для результатов (пусто — рядом с исходными)", ""))
    if target not in oc.TARGETS:
        print("Неизвестный целевой формат: .%s" % target)
        return 1
    files = oc.collect(paths)
    if not files:
        print("Подходящих файлов не найдено (нужны Excel, Word, презентации или PDF).")
        return 0
    soffice = oc.find_soffice()
    print("Движок: %s" % (soffice or "LibreOffice не найден; работает только .xls → .xlsx на Python"))
    counts = {"ok": 0, "skip": 0, "error": 0}
    for i, (f, base) in enumerate(files, 1):
        res = oc.convert_file(f, target, oc.dest_path(f, base, target, dest or None), soffice)
        counts[res["status"]] += 1
        label = {"ok": "готово", "skip": "пропущен", "error": "ОШИБКА"}[res["status"]]
        eng = " [%s]" % res["engine"] if res["engine"] else ""
        print("%d/%d %s: %s%s. %s" % (i, len(files), os.path.basename(f), label, eng, res["note"]))
    print("Итого: сконвертировано %d, пропущено %d, ошибок %d" % (counts["ok"], counts["skip"], counts["error"]))
    if counts["error"] and not soffice:
        print("Чтобы поддержать остальные форматы, установите LibreOffice (libreoffice.org) и запустите снова.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
