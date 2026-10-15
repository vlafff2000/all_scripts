"""Разбор «Учет газа … 2025-2026»: суточный отбор с выносом воды по объекту и закачка → одна книга Excel.

Листы результата: «Отбор» (по суткам), «Вынос воды по объекту» (по месяцам и итогом), «Закачка» (по суткам, если
дан файл закачки), «Проверки» (что посмотреть руками). Правила расчёта — в pxg_core/учёт_газа.py.
"""
from __future__ import annotations

import os

import pandas as pd

from pxg_core import параметры, учёт_газа


def main(argv=None):
    args = параметры.parse(
        "Учёт газа по месяцам: отбор с выносом воды и закачка", argv,
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
    withdrawal = учёт_газа.read_withdrawal(withdrawal_path)
    if withdrawal.empty:
        print("⚠️ Суточных строк с датами не найдено — книга не создана.")
        return 0
    by_month = учёт_газа.water_by_month(withdrawal)
    check = учёт_газа.checks(withdrawal)

    daily = pd.DataFrame({
        "Дата": withdrawal["Дата"].dt.date,
        "Лист": withdrawal["Лист"],
        "ПЗРГ-1,2,3, тыс. м³/сут": withdrawal["pzrg123"],
        "ПЗРГ-4, тыс. м³/сут": withdrawal["pzrg4"],
        "ПЗРГ-5, тыс. м³/сут": withdrawal["pzrg5"],
        "ПЗРГ всего (коммерческий узел учёта), тыс. м³/сут": withdrawal["pzrg_total"],
        "ГИС-Касимов, тыс. м³/сут": withdrawal["gis"],
        "Отбор за месяц, тыс. м³": withdrawal["month_total"],
        "Отбор за сезон, тыс. м³": withdrawal["season_total"],
        "Объём газа в пласте, тыс. м³": withdrawal["gas_in_reservoir"],
        "Вынос воды (пластовая жидкость), м³/сут": withdrawal["water"],
        "Водный фактор из файла, м³/млн м³": withdrawal["water_factor_file"],
        "Водный фактор пересчёт, м³/млн м³": withdrawal["water_factor_calc"].round(3),
        "Р пл. среднее (как в файле)": withdrawal["p_reservoir"],
    })

    out = (args.output or "").strip() or "Учёт_газа_отбор_вынос_воды.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        daily.to_excel(xw, sheet_name="Отбор", index=False)
        by_month.to_excel(xw, sheet_name="Вынос воды по объекту", index=False)
        if injection_path:
            print("📖 Закачка: %s" % os.path.basename(injection_path))
            injection = учёт_газа.read_injection(injection_path)
            pd.DataFrame({
                "Дата": injection["Дата"].dt.date,
                "Лист": injection["Лист"],
                "ПЗРГ-4, тыс. м³/сут": injection["pzrg4"],
                "ГИС-Касимов, тыс. м³/сут": injection["gis"],
                "Закачано за сутки, тыс. м³/сут": injection["inj_day"],
                "Закачано с начала месяца, тыс. м³": injection["inj_month"],
                "Объём газа в ПХГ, тыс. м³": injection["gas_in_reservoir"],
                "Среднее пластовое давление (как в файле)": injection["p_reservoir"],
            }).to_excel(xw, sheet_name="Закачка", index=False)
        check.to_excel(xw, sheet_name="Проверки", index=False)

    water = by_month.iloc[-1]
    print("✅ Учёт газа: %s" % out)
    print("   отбор: %d сут, вынос воды замерен в %d сут; вынос за период %.1f м³, фактор %s м³/млн м³"
          % (len(withdrawal), int(water["Дней с замером выноса"]), float(water["Вынос воды за месяц, м³"]),
             "н/д" if pd.isna(water["Водный фактор, м³/млн м³"]) else "%.2f" % water["Водный фактор, м³/млн м³"]))
    if len(check):
        print("⚠️ Проверок к просмотру: %d (лист «Проверки»)" % len(check))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
