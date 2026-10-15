"""Разбор «Учет газа …»: все данные листов месяцев одной длинной таблицей + вынос воды по объекту.

Листы результата: «Все данные» (каждое значение: тип, файл, лист, дата, столбец, параметр, единица, значение),
«Вынос воды по объекту» (по месяцам и итогом), «Исключено» (что не вошло и почему — остатки, итоги, расчёты
вне таблицы), «Листы» (что разобрано на каждом листе), «Проверки». Правила — в pxg_core/учёт_газа.py.
"""
from __future__ import annotations

import os

import pandas as pd

from pxg_core import параметры, учёт_газа


def main(argv=None):
    args = параметры.parse(
        "Учёт газа по месяцам: все данные листов и вынос воды", argv,
        withdrawal="файл учёта газа по отбору (листы по месяцам)",
        injection="файл учёта газа по закачке, необязательно",
        output="имя файла результата")
    withdrawal_path = параметры.ask_path("Файл учёта газа по отбору", args.withdrawal, "file")
    if not withdrawal_path:
        print("❌ Файл отбора не выбран.")
        return 1
    injection_path = параметры.ask_path("Файл учёта газа по закачке (Enter — пропустить)",
                                        args.injection if args.injection is not None else "")

    print("📖 Отбор: %s" % os.path.basename(withdrawal_path))
    long_w, excl_w, log_w = учёт_газа.read_book(withdrawal_path, "отбор")
    parts, excl_parts, logs = [long_w], [excl_w], [log_w]
    if injection_path:
        print("📖 Закачка: %s" % os.path.basename(injection_path))
        long_i, excl_i, log_i = учёт_газа.read_book(injection_path, "закачка")
        parts.append(long_i)
        excl_parts.append(excl_i)
        logs.append(log_i)
    everything = pd.concat(parts, ignore_index=True)
    excluded = pd.concat(excl_parts, ignore_index=True)
    sheets_log = pd.concat(logs, ignore_index=True)
    if everything.empty:
        print("⚠️ Значений в строках суток не найдено — книга не создана.")
        return 0

    water = учёт_газа.water_by_month(long_w) if len(long_w) else pd.DataFrame()
    check = учёт_газа.checks(long_w) if len(long_w) else pd.DataFrame()

    out = (args.output or "").strip() or "Учёт_газа_все_данные.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        everything.to_excel(xw, sheet_name="Все данные", index=False)
        if len(water):
            water.to_excel(xw, sheet_name="Вынос воды по объекту", index=False)
        excluded.to_excel(xw, sheet_name="Исключено", index=False)
        sheets_log.to_excel(xw, sheet_name="Листы", index=False)
        check.to_excel(xw, sheet_name="Проверки", index=False)

    print("✅ Учёт газа: %s — %d значений, %d листов, исключено %d ячеек"
          % (out, len(everything), len(sheets_log), len(excluded)))
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
