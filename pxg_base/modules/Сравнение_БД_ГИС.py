"""Сравнение двух БД ГИС: прежней («База ГИС» из Excel) и новой («БД ГИС из отчётов») → «Сравнение_БД_ГИС.xlsx».

Листы: «Сводка», «Замеры» (только в одной базе, разные даты), «Пачки» (кровля, подошва, hг эф, Кг ср.взв, ГВК в MD и а.о.), «Интервалы»
(нет в одной из баз, разный Кг). Ничего не исправляется: расхождение — повод открыть источник; последнее слово за инженером.
Параметры: --a (папка прежней БД с gis_*.parquet/csv), --b (папка новой БД), --tol-depth и --tol-kg (допуски), --marks (прежняя выгрузка с решениями инженера: они переносятся). Если в обеих папках есть gis_templating / gis_complex, добавляются листы «Доход шаблона» и «Комплекс ГИС». Результат — в текущую папку.
"""
from __future__ import annotations

import os
import sys

from pxg_core import gis_compare, параметры

_ = sys


def main(argv=None):
    args = параметры.parse("Сравнение БД ГИС", argv,
                           a="папка прежней БД ГИС (gis_observations/packs/intervals), А",
                           b="папка новой БД ГИС (из отчётов), Б", tol_depth="допуск по глубине, м (по умолчанию 0,15)",
                           tol_kg="допуск по Кг, доля (по умолчанию 0,03)", marks="прежняя выгрузка сравнения с решениями инженера, необязательно")
    a = параметры.ask_path("Прежняя БД ГИС (папка), А", args.a, "folder")
    b = параметры.ask_path("Новая БД ГИС (папка), Б", args.b, "folder")
    if not a or not b:
        print("❌ Нужны обе папки.")
        return 1
    try:
        num = lambda v, d: float(str(v).replace(",", ".")) if v not in (None, "") else d      # noqa: E731
        path, frames = gis_compare.export(a, b, os.getcwd(), num(args.tol_depth, gis_compare.TOL_DEPTH), num(args.tol_kg, gis_compare.TOL_KG),
                                          параметры.clean_path(args.marks or ""))
    except (ValueError, OSError) as e:
        print("❌ %s" % e)
        return 1
    for _i, r in frames["Сводка"].iterrows():
        print("%s: %s" % (r["Показатель"], r["Значение"]))
    print("✅ %s" % os.path.basename(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
