"""Шаблон конструкции из свода скважин: «Данные по скважинам» (форма ПХГ-01) → таблица конструкции для загрузки в Газовый атлас.

Разбор и правила — `pxg_core.well_construction`. Параметры: --file (свод скважин, Excel), --date (дата конструкции ДД.ММ.ГГГГ;
без неё берётся «По состоянию на» из шапки). Результаты пишутся в текущую папку: `Конструкция_для_Атласа.xlsx` (загружается в Атлас
как «Шаблон конструкции») и `Свод_скважин_разбор.xlsx` (паспорт, проведённые работы, соответствие столбцов, проверка).
"""
from __future__ import annotations

import os
import sys

from pxg_core import well_construction as wc, параметры

# Запуск из подпроцесса: репозиторий в sys.path уже есть (корень задаёт runner)
_ = sys


def main(argv=None):
    args = параметры.parse(
        "Шаблон конструкции из свода скважин", argv,
        file="свод скважин (Excel, форма ПХГ-01)",
        date="дата конструкции ДД.ММ.ГГГГ (по умолчанию «По состоянию на» из шапки свода)")
    path = параметры.ask_path("Свод скважин (Excel)", args.file)
    if not path:
        print("❌ Свод скважин не выбран.")
        return 1
    try:
        book = wc.read(path, date=args.date or "")
    except ValueError as err:
        print("❌ %s" % err)
        return 1
    if book.snapshot is None:
        print("❌ Дата конструкции не определена: укажите её в форме.")
        return 1
    table = wc.atlas_table(book)
    print("📚 Скважин: %d, строк конструкции: %d, дата конструкции: %s%s" % (
        len(book.wells), len(table), book.snapshot.strftime("%d.%m.%Y"), " (из шапки свода)" if book.snapshot_from_header else ""))
    for name, n in table["Элемент"].value_counts().items():
        print("   %s: %d" % (name, n))
    kinds = {}
    for i in book.issues:
        kinds[i.level] = kinds.get(i.level, 0) + 1
    print("🔎 Проверка свода: %s" % (", ".join("%s: %d" % kv for kv in sorted(kinds.items())) or "замечаний нет"))
    for f in wc.export(book, os.getcwd()):
        print("✅ %s" % os.path.basename(f))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
