"""БД шаблонирования: отбивки текущего забоя (доход прибора ГИС, шаблонирование, текущий забой) из всех мест в одну таблицу.

Источники (все необязательны): «БД ГИС из отчётов» (gis_templating), «Конструкции из Word» (лист «Замеры забоя»), свои Excel/CSV, отчёты ГИС (Word/PDF),
решения инженера. Результат — «БД_шаблонирования.xlsx» (лист «Замеры забоя» загружается в Атлас) и templating_db.parquet/csv.
У каждой строки — источник и основание; решение инженера главнее правил. Разбор — `pxg_core.templating_db`.
"""
from __future__ import annotations

import os
import sys

from pxg_core import archives, templating_db, параметры

_ = sys


def _paths(value: str) -> list:
    return [x.strip().strip('"') for x in (value or "").splitlines() if x.strip()]


def expand(paths, exts):
    files, notes, _tmp = archives.expand(paths, exts)
    return files, notes


def main(argv=None):
    args = параметры.parse(
        "БД шаблонирования", argv,
        gis_db="папка «БД ГИС из отчётов» (gis_templating) или БД_шаблонировок.xlsx", construction="Конструкции_из_Word_для_Атласа.xlsx",
        excel="свои Excel/CSV с шаблонированием (файлы и папки, по одному в строке)", reports="отчёты ГИС (Word/PDF, папки, архивы)",
        decisions="решения инженера (Excel/CSV)")
    gis_db, cons = параметры.clean_path(args.gis_db or ""), параметры.clean_path(args.construction or "")
    excel, notes = expand(_paths(args.excel), (".xlsx", ".xlsm", ".xls", ".csv"))
    reports, n2 = expand(_paths(args.reports), (".doc", ".docx", ".pdf"))
    for n in notes + n2:
        print("⚠️ %s" % n)
    if not (gis_db or cons or excel or reports):
        print("❌ Не указан ни один источник.")
        return 1
    try:
        files, frames = templating_db.export(os.getcwd(), gis_db=gis_db, construction=cons, excel=excel, reports=reports,
                                             decisions=параметры.clean_path(args.decisions or ""))
    except (ValueError, OSError) as e:
        print("❌ %s" % e)
        return 1
    for _i, r in frames["Сводка"].iterrows():
        print("%s: %s" % (r["Показатель"], r["Значение"]))
    for _i, r in frames["Проверка"].iterrows():
        if r["Сообщение"] != "замечаний нет":
            print("⚠️ %s" % r["Сообщение"])
    for f in files:
        print("✅ %s" % os.path.basename(f))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
