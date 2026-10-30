"""Шаблон конструкции из свода скважин: «Данные по скважинам» (форма ПХГ-01) → таблица конструкции для загрузки в Газовый атлас.

Разбор и правила — `pxg_core.well_construction`. Параметры: --file (свод скважин, Excel), --date (дата конструкции ДД.ММ.ГГГГ;
без неё берётся «По состоянию на» из шапки). Альтитуды Атласа для а.о. и сверки: --atlas-storage / --atlas-project (проект Атласа) или --alt-file («Глубины_перфораций.xlsx»).
Результаты пишутся в текущую папку: `Конструкция_для_Атласа.xlsx` (загружается в Атлас
как «Шаблон конструкции») и `Свод_скважин_разбор.xlsx` (паспорт, проведённые работы, соответствие столбцов, проверка).
"""
from __future__ import annotations

import os
import sys

from pxg_core import well_construction as wc, параметры

# Запуск из подпроцесса: репозиторий в sys.path уже есть (корень задаёт runner)
_ = sys


def load_altitudes(args):
    """Альтитуды Атласа: файл главнее проекта; нет ни того ни другого или не прочиталось — сверка пропускается с пояснением."""
    try:
        if (args.alt_file or "").strip():
            return wc.file_altitudes(параметры.clean_path(args.alt_file))
        if (args.atlas_storage or "").strip() or os.environ.get("GAS_ATLAS_STORAGE") or (args.atlas_project or "").strip():
            return wc.atlas_altitudes(параметры.clean_path(args.atlas_storage or ""), args.atlas_project or "")
    except (ValueError, OSError, FileNotFoundError) as err:
        print("⚠️ Альтитуды Атласа не прочитаны, сверка пропущена: %s" % err)
    return None, ""


def main(argv=None):
    args = параметры.parse(
        "Шаблон конструкции из свода скважин", argv,
        file="свод скважин (Excel, форма ПХГ-01)",
        date="дата конструкции ДД.ММ.ГГГГ (по умолчанию «По состоянию на» из шапки свода)",
        atlas_storage="папка хранилища Атласа (по умолчанию GAS_ATLAS_STORAGE)",
        atlas_project="id проекта Атласа (по умолчанию самый свежий с расходами)",
        rotor="учитывать высоту стола ротора в а.о. (да/нет, по умолчанию да)",
        alt_file="«Глубины_перфораций.xlsx» с альтитудами, если проекта Атласа нет")
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
    atlas_alt, source = load_altitudes(args)
    rotor = параметры.yes(args.rotor if args.rotor is not None else "да")
    for f in wc.export(book, os.getcwd(), atlas_alt, source, rotor):
        print("✅ %s" % os.path.basename(f))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
