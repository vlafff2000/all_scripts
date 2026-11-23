"""БД по учету газа: суточные данные эксплуатации из файлов «Учет газа» (отбор и закачка) в одну таблицу.

Вход — файлы или папки: папка берётся рекурсивно (подпапки по сезонам/годам или все файлы в одной папке).
Выход — книга Excel в формате остальных БД «Базы ПХГ»: одна строка — сутки режима (отбор или закачка),
один параметр — один столбец. Листы: «БД» (основной), «Параметры» (названия и единицы), «Вынос воды по объекту»
(по месяцам и итогом), «Исключено» (что не вошло и адрес ячейки), «Листы», «Проверки».
Правила разбора — в pxg_core/учёт_газа.py.
"""
from __future__ import annotations

import os

import pandas as pd

from pxg_core import append_mode, параметры, учёт_газа

# версия правил чтения книг учёта газа: увеличивать при правке pxg_core/учёт_газа.py (read_book, read_sheet и их помощников),
# иначе дополнение возьмёт старый разбор
PARSE_VERSION = 1
SCHEMA_VERSION = "gas_accounting-1"


def _paths(value: str) -> list:
    return [x.strip().strip('"') for x in (value or "").splitlines() if x.strip()]


def main(argv=None):
    args = параметры.parse(
        "БД по учету газа: отбор с выносом воды и закачка", argv,
        withdrawal="файлы или папки учёта газа по отбору (папка — со всеми подпапками)",
        injection="файлы или папки учёта газа по закачке, необязательно",
        output="имя файла результата",
        cache="папка кэша чтения книг (по умолчанию ~/.pxg/append_cache по набору папок)", **append_mode.FLAGS)
    withdrawal = _paths(args.withdrawal)
    if not withdrawal:
        withdrawal = _paths(параметры.ask_path("Файл или папка учёта газа по отбору", "", "folder"))
    if not withdrawal:
        print("❌ Учёт газа по отбору не выбран.")
        return 1
    injection = _paths(args.injection)

    books_w, skipped = учёт_газа.collect_books(withdrawal)
    books_i, skipped_i = учёт_газа.collect_books(injection) if injection else ([], [])
    skipped += skipped_i
    if not books_w and not books_i:
        print("❌ Книг учёта газа не найдено (нужны листы с месяцами, например «Октябрь 2025»).")
        return 1
    print("📚 Книг отбора: %d, закачки: %d" % (len(books_w), len(books_i)))
    for p in skipped:
        print("⚠️ Пропущено (не учёт газа или нет пути): %s" % p)

    parts, excl_parts, logs = [], [], []
    plan_only = False
    for kind, books, label in (("отбор", books_w, "Отбор"), ("закачка", books_i, "Закачка")):
        if not books:
            continue
        # режим дополнения: читаются только новые и изменённые книги, остальное из кэша (итог тот же)
        cache = append_mode.ParseCache(
            append_mode.cache_dir("gas_accounting_" + kind, sorted(set(withdrawal + injection)),
                                  os.path.join(параметры.clean_path(args.cache), kind) if args.cache else ""),
            SCHEMA_VERSION, PARSE_VERSION)
        try:
            got, plan = append_mode.run_cached(
                cache, books, os.path.commonpath([os.path.dirname(os.path.abspath(b)) for b in books]),
                lambda paths, kind=kind: [учёт_газа.read_book(p, kind) for p in paths],
                rebuild=параметры.yes(args.rebuild), drop_missing=параметры.yes(args.drop_missing),
                plan_only=параметры.yes(args.plan_only), rows_of=lambda r: len(r[0]), cacheable=lambda r: not r[0].empty)
        except append_mode.AppendError as exc:
            print("❌ Дополнение невозможно (%s): %s (параметр --rebuild=да)" % (label.lower(), exc))
            return 1
        print("🧩 %s: %s" % (label, append_mode.summary(plan)))
        for _, row in plan[plan["Статус"] != append_mode.SAME].iterrows():
            print("   • %s: %s → %s (%s)" % (row["Файл"], row["Статус"], row["Действие"], row["Причина"]))
        if параметры.yes(args.plan_only):
            plan_only = True
            continue
        append_mode.write_registry_xlsx(cache)
        kept = plan[plan["Действие"].isin([append_mode.PROCESS, append_mode.SKIP, append_mode.KEEP])]
        for path, (long_df, excl, log) in zip([p or f for p, f in zip(kept["Путь"], kept["Файл"])], got):
            print("📖 %s: %s" % (label, os.path.basename(path)))
            parts.append(long_df), excl_parts.append(excl), logs.append(log)
    if plan_only:
        print("План дополнения показан, файл не создан.")
        return 0

    everything = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    excluded = pd.concat(excl_parts, ignore_index=True)
    sheets_log = pd.concat(logs, ignore_index=True)
    if everything.empty:
        print("⚠️ Значений в строках суток не найдено — книга не создана.")
        return 0

    db, dictionary, excluded, db_checks = учёт_газа.build_db(everything, excluded)
    long_w = everything[everything["Тип"] == "отбор"]
    water = учёт_газа.water_by_month(long_w) if len(long_w) else pd.DataFrame()
    check = учёт_газа.checks(long_w) if len(long_w) else pd.DataFrame()
    check = pd.concat([db_checks, check], ignore_index=True)

    out = (args.output or "").strip() or "БД_по_учету_газа.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        db.to_excel(xw, sheet_name="БД", index=False)
        dictionary.to_excel(xw, sheet_name="Параметры", index=False)
        if len(water):
            water.to_excel(xw, sheet_name="Вынос воды по объекту", index=False)
        excluded.to_excel(xw, sheet_name="Исключено", index=False)
        sheets_log.to_excel(xw, sheet_name="Листы", index=False)
        check.to_excel(xw, sheet_name="Проверки", index=False)

    print("✅ БД по учету газа: %s — %d суток (отбор %d, закачка %d), параметров %d, исключено ячеек %d"
          % (out, len(db), int((db["Режим"] == "отбор").sum()), int((db["Режим"] == "закачка").sum()),
             len(dictionary), len(excluded)))
    if len(water):
        total = water.iloc[-1]
        print("   вынос воды замерен в %d из %d суток с отбором; вынос за период %.1f м³, фактор %s м³/млн м³"
              % (int(total["Дней с замером выноса"]), int(total["Дней с отбором"]), float(total["Вынос воды, м³"]),
                 "н/д" if pd.isna(total["Водный фактор, м³/млн м³"]) else "%.2f" % total["Водный фактор, м³/млн м³"]))
    if len(check):
        print("⚠️ Проверок к просмотру: %d (лист «Проверки»)" % len(check))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
