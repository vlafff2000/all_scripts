"""Импорт данных ЭЛПРО: месячные файлы «Параметры работы ГСП (за месяц)» → одна длинная таблица по дням и скважинам.

Понимает все три вида файлов ЭЛПРО (XML-таблица с расширением .xlsx ГСП-1,2,3,8 и настоящий xlsx ГСП-4,5,7,9),
отбор и закачку. Давления — кгс/см², объём — тыс. м³/сут, прочерки — пропуски, нули — простои.

Результат — лист «Данные»: дата, режим, ГСП, скважина, № п/п в файле, начало сезона, P, T, Y, Q, часы, файл.
Листы «Файлы» (разбор по файлам), «Покрытие» (ГСП × месяц, пропуски) и «Предупреждения».

Параметры: --folder (папка с файлами ЭЛПРО), --db (прежняя база для дозаписи, необязательно), --output.
Строки с тем же ключом (день, ГСП, скважина, режим, № п/п) заменяются новыми.
Листы «Файлы», «Покрытие» и «Предупреждения» описывают только файлы этой папки: при дозаписи в прежнюю базу
покрытие прежних месяцев там не показано.
"""
from __future__ import annotations

import os

import pandas as pd

from pxg_core import параметры, qc, элпро


def main(argv=None):
    args = параметры.parse(
        "Импорт данных ЭЛПРО", argv,
        folder="папка с месячными файлами ЭЛПРО (.xlsx)",
        db="прежняя база для дозаписи (Excel с листом «Данные»), необязательно",
        output="имя файла результата")
    folder = параметры.ask_path("Папка с файлами ЭЛПРО", args.folder, "folder")
    if not folder:
        print("❌ Папка не выбрана.")
        return 1
    db_path = параметры.ask_path("Прежняя база для дозаписи (Enter — создать новую)", args.db if args.db is not None else "")
    files = [f for f in qc.list_excel(folder, recursive=True) if not os.path.basename(f).startswith("~$")]  # и подпапки сезонов
    if not files:
        print("⚠️ В папке нет файлов Excel: %s" % folder)
        return 0
    old = pd.read_excel(db_path, sheet_name="Данные") if db_path else None
    if old is not None:
        print("📚 Прежняя база: %d строк" % len(old))
    data, infos, cov, warn = элпро.build(files, old)
    for text in warn:
        print("⚠️ %s" % text)
    if data.empty:
        print("⚠️ Данные ЭЛПРО не найдены, база не создана.")
        return 0
    out = (args.output or "").strip() or "БД_ЭЛПРО.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    with pd.ExcelWriter(out, engine="openpyxl", datetime_format="YYYY-MM-DD") as xw:
        data.to_excel(xw, sheet_name="Данные", index=False)
        элпро.file_stats(infos).to_excel(xw, sheet_name="Файлы", index=False)
        cov.to_excel(xw, sheet_name="Покрытие", index=False)
        pd.DataFrame({"Предупреждение": warn}).to_excel(xw, sheet_name="Предупреждения", index=False)
    gaps = int((cov["Статус"] != "есть").sum()) if not cov.empty else 0
    print("✅ База ЭЛПРО: %s (%d строк, %d скважин, %d групп(ы)); пропусков покрытия: %d"
          % (out, len(data), data["Скважина"].nunique(), data["ГСП"].nunique(), gaps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
