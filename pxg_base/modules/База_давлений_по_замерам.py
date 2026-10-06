"""База давлений по замерам: Руст, избыточное давление, Рпл и уровень жидкости из месячных файлов «Результаты замеров».

Параметры: --folder (папка с файлами замеров), --db (прежняя база для дозаписи, необязательно), --excess-limit,
--output. Новые замеры заменяют старые с тем же ключом (скважина + дата + горизонт).
"""
from __future__ import annotations

import os
import sys

import pandas as pd

from pxg_core import замеры, параметры, qc


def main(argv=None):
    args = параметры.parse(
        "База давлений по замерам", argv,
        folder="папка с файлами «Результаты замеров» (Excel)",
        db="прежняя база для дозаписи (Excel с листом «Данные»), необязательно",
        excess_limit="Руст ниже этого значения у наблюдательных, контрольных и поглотительных — избыточное давление",
        output="имя файла результата")
    folder = параметры.ask_path("Папка с файлами замеров", args.folder, "folder")
    if not folder:
        print("❌ Папка не выбрана.")
        return 1
    db_path = параметры.ask_path("Прежняя база для дозаписи (Enter — создать новую)", args.db if args.db is not None else "")
    try:
        limit = float(str(args.excess_limit).replace(",", ".")) if args.excess_limit not in (None, "") else замеры.EXCESS_LIMIT
    except ValueError:
        print("❌ Порог избыточного давления не число: %s" % args.excess_limit)
        return 1
    files = [f for f in qc.list_excel(folder) if not os.path.basename(f).startswith("~$")]
    if not files:
        print("⚠️ В папке нет файлов Excel: %s" % folder)
        return 0

    frames, stat = [], []
    for f in files:
        parsed = замеры.parse_file(f, limit)
        for code, text, where in parsed.problems:
            print("⚠️ %s (%s)" % (text, where))
        print("📄 %s: %d замеров" % (os.path.basename(f), len(parsed.rows)))
        stat.append([os.path.basename(f), len(parsed.rows)])
        if parsed.rows:
            frames.append(замеры.to_frame(parsed.rows))
    if not frames:
        print("⚠️ Замеры не найдены, база не создана.")
        return 0
    new = pd.concat(frames, ignore_index=True)

    old = None
    if db_path:
        old = pd.read_excel(db_path, sheet_name="Данные")
        print("📚 Прежняя база: %d строк" % len(old))
    data = замеры.merge(old, new)
    out = (args.output or "").strip() or "БД_давлений_по_замерам.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        data.to_excel(xw, sheet_name="Данные", index=False)
        for sheet, col in (("Руст по месяцам", "Руст"), ("Избыточное по месяцам", "Избыточное давление"),
                           ("Рпл по месяцам", "Рпл"), ("Уровень по месяцам", "Уровень жидкости")):
            wide = замеры.by_month(data, col)
            if not wide.empty:
                wide.to_excel(xw, sheet_name=sheet)
        pd.DataFrame([["Всего записей", len(data)], ["Уникальных скважин", data["Скважина"].nunique()],
                      ["Горизонтов", data["Горизонт"].nunique()],
                      ["Замеров Руст", int(data["Руст"].notna().sum())],
                      ["Замеров избыточного давления", int(data["Избыточное давление"].notna().sum())],
                      ["Замеров Рпл", int(data["Рпл"].notna().sum())],
                      ["Замеров уровня", int(data["Уровень жидкости"].notna().sum())]],
                     columns=["Параметр", "Значение"]).to_excel(xw, sheet_name="Статистика", index=False)
        pd.DataFrame(stat, columns=["Файл", "Замеров"]).to_excel(xw, sheet_name="Файлы", index=False)
    print("✅ %s: %d строк, %d скважин" % (out, len(data), data["Скважина"].nunique()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
