"""Объединение двух БД ГИС: «База ГИС» из Excel (первая) и «БД ГИС из отчётов» (вторая) → «Объединённая_БД_ГИС.xlsx» и таблицы gis_*.

Из первой берутся замеры, которых нет во второй; если замер есть в обеих, берётся вторая (она главнее). Решение по каждому замеру и причина — лист «Решения»;
список «взять из первой» (скважина + месяц) меняет решение. Альтитуды берутся из файла Атласа («Глубины_перфораций.xlsx»), ГВК а.о. пересчитывается
из MD; расхождения альтитуд и спорные значения показаны. Автоматика только подсказывает: последнее слово за инженером.
"""
from __future__ import annotations

import os
import sys

from pxg_core import gis_merge, параметры

_ = sys


def main(argv=None):
    args = параметры.parse("Объединение БД ГИС", argv,
                           a="папка первой БД ГИС (из Excel, gis_observations/packs/intervals)",
                           b="папка второй БД ГИС (из отчётов), главнее первой",
                           altitudes="файл альтитуд Атласа «Глубины_перфораций.xlsx», необязательно",
                           keep_first="файл решений «взять из первой»: столбцы «Скважина», «Месяц», необязательно")
    a = параметры.ask_path("Первая БД ГИС (папка, из Excel)", args.a, "folder")
    b = параметры.ask_path("Вторая БД ГИС (папка, из отчётов)", args.b, "folder")
    if not a or not b:
        print("❌ Нужны обе папки.")
        return 1
    try:
        path, res = gis_merge.export(a, b, os.getcwd(), параметры.clean_path(args.altitudes or ""), параметры.clean_path(args.keep_first or ""))
    except (ValueError, OSError) as e:
        print("❌ %s" % e)
        return 1
    for _i, r in res["Сводка"].iterrows():
        print("%s: %s" % (r["Показатель"], r["Значение"]))
    print("✅ %s и таблицы gis_observations / gis_packs / gis_intervals" % os.path.basename(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
