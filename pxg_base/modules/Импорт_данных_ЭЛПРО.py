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

from pxg_core import append_mode, параметры, qc, элпро

# версия правил чтения файлов ЭЛПРО: увеличивать при правке pxg_core/элпро.py (read_file и всё, что она вызывает)
PARSE_VERSION = 1
SCHEMA_VERSION = "elpro-1"


def main(argv=None):
    args = параметры.parse(
        "Импорт данных ЭЛПРО", argv,
        folder="папка с месячными файлами ЭЛПРО (.xlsx)",
        db="прежняя база для дозаписи (Excel с листом «Данные»), необязательно",
        output="имя файла результата",
        cache="папка кэша чтения файлов (по умолчанию ~/.pxg/append_cache по папке с файлами)", **append_mode.FLAGS)
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
    cache = append_mode.ParseCache(append_mode.cache_dir("elpro", [folder], параметры.clean_path(args.cache or "")),
                                   SCHEMA_VERSION, PARSE_VERSION)
    try:     # режим дополнения: читаются только новые и изменённые файлы, остальное из кэша; покрытие считается по всем (итог тот же)
        parsed, plan = append_mode.run_cached(
            cache, files, os.path.abspath(folder), lambda paths: [элпро.read_safe(p) for p in paths],
            rebuild=параметры.yes(args.rebuild), drop_missing=параметры.yes(args.drop_missing),
            plan_only=параметры.yes(args.plan_only), rows_of=lambda r: len(r[0]), cacheable=lambda r: not r[0].empty)
    except append_mode.AppendError as exc:
        print("❌ Дополнение невозможно: %s (параметр --rebuild=да)" % exc)
        return 1
    print("🧩 " + append_mode.summary(plan))
    for _, row in plan[plan["Статус"] != append_mode.SAME].iterrows():
        print("   • %s: %s → %s (%s)" % (row["Файл"], row["Статус"], row["Действие"], row["Причина"]))
    if параметры.yes(args.plan_only):
        print("План дополнения показан, файл не создан.")
        return 0
    append_mode.write_registry_xlsx(cache)
    data, infos, cov, warn = элпро.build(files, old, parsed)
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
