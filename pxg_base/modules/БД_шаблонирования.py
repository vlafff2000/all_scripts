"""БД шаблонирования: отбивки текущего забоя (доход прибора ГИС, шаблонирование, текущий забой) из всех мест в одну таблицу.

Источники (все необязательны): «БД ГИС из отчётов» (gis_templating), «Конструкции из Word» (лист «Замеры забоя»), свои Excel/CSV, отчёты ГИС (Word/PDF),
решения инженера. Результат — «БД_шаблонирования.xlsx» (лист «Замеры забоя» загружается в Атлас) и templating_db.parquet/csv.
У каждой строки — источник и основание; решение инженера главнее правил. Разбор — `pxg_core.templating_db`.
"""
from __future__ import annotations

import os
import sys

from pxg_core import append_mode, archives, gis_report, templating_db, параметры

# версия правил чтения отчётов ГИС: увеличивать при правке pxg_core/gis_report.py (parse_file и его помощников), иначе дополнение возьмёт старый разбор
PARSE_VERSION = 1
SCHEMA_VERSION = "templating_reports-1"

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
        decisions="решения инженера (Excel/CSV)",
        cache="папка кэша чтения отчётов (по умолчанию ~/.pxg/append_cache по набору путей)", **append_mode.FLAGS)
    gis_db, cons = параметры.clean_path(args.gis_db or ""), параметры.clean_path(args.construction or "")
    excel, notes = expand(_paths(args.excel), (".xlsx", ".xlsm", ".xls", ".csv"))
    reports, n2 = expand(_paths(args.reports), (".doc", ".docx", ".pdf"))
    for n in notes + n2:
        print("⚠️ %s" % n)
    if not (gis_db or cons or excel or reports):
        print("❌ Не указан ни один источник.")
        return 1
    parsed = None
    if reports:      # режим дополнения: отчёты (Word/PDF) читаются только новые и изменённые, остальное из кэша; итог тот же
        cache = append_mode.ParseCache(
            append_mode.cache_dir("templating_reports", sorted(_paths(args.reports)), параметры.clean_path(args.cache or "")),
            SCHEMA_VERSION, PARSE_VERSION)
        try:
            parsed, plan = append_mode.run_cached(
                cache, reports, os.path.commonpath([os.path.dirname(os.path.abspath(f)) for f in reports]),
                lambda ps: [gis_report.parse_file(p, {}) for p in ps], rebuild=параметры.yes(args.rebuild),
                drop_missing=параметры.yes(args.drop_missing), plan_only=параметры.yes(args.plan_only),
                rows_of=lambda r: 0 if r.error else 1, cacheable=lambda r: not r.error)
        except append_mode.AppendError as exc:
            print("❌ Дополнение невозможно: %s (параметр --rebuild=да)" % exc)
            return 1
        print("🧩 " + append_mode.summary(plan))
        for _i, row in plan[plan["Статус"] != append_mode.SAME].iterrows():
            print("   • %s: %s → %s (%s)" % (row["Файл"], row["Статус"], row["Действие"], row["Причина"]))
        if параметры.yes(args.plan_only):
            print("План дополнения показан, файл не создан.")
            return 0
        append_mode.write_registry_xlsx(cache)
        kept = plan[plan["Действие"].isin([append_mode.PROCESS, append_mode.SKIP, append_mode.KEEP])]
        reports = [p or f for p, f in zip(kept["Путь"], kept["Файл"])]       # «пропавшие» оставленные — в конце
    try:
        files, frames = templating_db.export(os.getcwd(), gis_db=gis_db, construction=cons, excel=excel, reports=reports,
                                             decisions=параметры.clean_path(args.decisions or ""), parsed_reports=parsed)
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
