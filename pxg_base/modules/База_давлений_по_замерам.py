"""База давлений по замерам: Руст, избыточное давление, Рпл и уровень жидкости из месячных файлов «Результаты замеров».

Вторая строка — еженедельные замеры эксплуатационных скважин («Итоговая таблица 2006–2026», её читает `замеры.parse_weekly`):
месячные отчёты теряют по 3–5 замеров в месяц, поэтому в базу попадает объединение обоих источников без дублей. Приоритет
при одном ключе (скважина, день, горизонт): месячный отчёт, затем еженедельный файл, затем прежняя база; пустые поля
дополняются из следующего источника. Опция «пересчитать» сразу выполняет модуль «Пересчёт давлений» по готовой базе.
Скважины с соседними номерами (437 и 438) выполняют одну функцию: скважина без горизонта заменяется соседом с горизонтом,
пары можно задать вручную (--neighbors).
Параметры: --folder, --weekly, --db (прежняя база, необязательно), --excess-limit, --recalc, --refs, --output.
Новые замеры заменяют старые с тем же ключом (скважина + дата + горизонт).
"""
from __future__ import annotations

import importlib
import os
import sys

import pandas as pd

from pxg_core import append_mode, замеры, параметры, qc
from pxg_core.parallel import map_jobs

# версия правил чтения файлов замеров: увеличивать при правке pxg_core/замеры.py (parse_file, parse_weekly и их помощников),
# иначе дополнение возьмёт старый разбор
PARSE_VERSION = 1
SCHEMA_VERSION = "pressure-1"


def _read_cached(name, files, root, parse_many, args, label):
    """Разобрать только новые и изменённые файлы (остальное из кэша). Возврат: список разборов в порядке файлов или None (ошибка / только план)."""
    cache = append_mode.ParseCache(append_mode.cache_dir(name, [root], параметры.clean_path(args.cache or "")),
                                   SCHEMA_VERSION, PARSE_VERSION)
    try:
        got, plan = append_mode.run_cached(
            cache, files, root, parse_many, rebuild=параметры.yes(args.rebuild), drop_missing=параметры.yes(args.drop_missing),
            plan_only=параметры.yes(args.plan_only), rows_of=lambda p: len(p.rows),
            cacheable=lambda p: not any(code == "FILE" for code, _, _ in p.problems))
    except append_mode.AppendError as exc:
        print("❌ Дополнение невозможно (%s): %s (параметр --rebuild=да)" % (label, exc))
        return None, files
    print("🧩 %s: %s" % (label, append_mode.summary(plan)))
    for _, row in plan[plan["Статус"] != append_mode.SAME].iterrows():
        print("   • %s: %s → %s (%s)" % (row["Файл"], row["Статус"], row["Действие"], row["Причина"]))
    if параметры.yes(args.plan_only):
        return None, files
    append_mode.write_registry_xlsx(cache)
    kept = plan[plan["Действие"].isin([append_mode.PROCESS, append_mode.SKIP, append_mode.KEEP])]
    return got, [p or f for p, f in zip(kept["Путь"], kept["Файл"])]       # «пропавшие» оставленные — в конце


def main(argv=None):
    args = параметры.parse(
        "База давлений по замерам", argv,
        folder="папка с файлами «Результаты замеров» (Excel)",
        weekly="еженедельные замеры эксплуатационных скважин («Итоговая таблица 2006–2026», Excel), необязательно",
        db="прежняя база для дозаписи (Excel с листом «Данные»), необязательно",
        excess_limit="Руст ниже этого значения у наблюдательных, контрольных и поглотительных — избыточное давление",
        recalc="да: сразу выполнить «Пересчёт давлений» по готовой базе",
        neighbors="склейка соседних скважин: пары «437=438; 83=82» (слева заменяемая); пусто — автоматически, «нет» — не склеивать",
        refs="для пересчёта: книга со справочниками (листы «Альтитуды» и «Перфорации»)",
        output="имя файла результата",
        cache="папка кэша чтения файлов (по умолчанию ~/.pxg/append_cache по папке с файлами)", **append_mode.FLAGS)
    folder = параметры.ask_path("Папка с файлами замеров", args.folder, "folder")
    if not folder:
        print("❌ Папка не выбрана.")
        return 1
    weekly_path = параметры.ask_path("Еженедельные замеры («Итоговая таблица», Enter — без них)", args.weekly if args.weekly is not None else "")
    db_path = параметры.ask_path("Прежняя база для дозаписи (Enter — создать новую)", args.db if args.db is not None else "")
    try:
        limit = float(str(args.excess_limit).replace(",", ".")) if args.excess_limit not in (None, "") else замеры.EXCESS_LIMIT
    except ValueError:
        print("❌ Порог избыточного давления не число: %s" % args.excess_limit)
        return 1
    try:
        recalc = параметры.yes(args.recalc or "")
    except Exception as e:
        print("❌ %s" % e)
        return 1
    refs_path = ""
    if recalc:
        refs_path = параметры.ask_path("Книга со справочниками для пересчёта (Альтитуды, Перфорации)", args.refs)
        if not refs_path:
            print("❌ Для пересчёта давлений нужна книга со справочниками; базу без пересчёта можно собрать, снимите флажок.")
            return 1
    files = [f for f in qc.list_excel(folder) if not os.path.basename(f).startswith("~$")]
    if not files and not weekly_path:
        print("⚠️ В папке нет файлов Excel: %s" % folder)
        return 0

    frames, stat = [], []
    root = os.path.abspath(folder)
    parsed_files, files = _read_cached(
        "pressure_%s" % append_mode.context_key(limit), files, root,
        lambda paths: list(map_jobs(замеры.parse_job, [(p, limit) for p in paths], 400)), args, "месячные файлы") if files else ([], [])
    if files and parsed_files is None:
        if параметры.yes(args.plan_only):
            print("План дополнения показан, файл не создан.")
            return 0
        return 1
    for f, parsed in zip(files, parsed_files):
        for code, text, where in parsed.problems:
            print("⚠️ %s (%s)" % (text, where))
        print("📄 %s: %d замеров" % (os.path.basename(f), len(parsed.rows)))
        stat.append([os.path.basename(f), len(parsed.rows)])
        if parsed.rows:
            frames.append(замеры.to_frame(parsed.rows))
    weekly = None
    if weekly_path:
        got, _ = _read_cached("pressure_weekly", [weekly_path], os.path.dirname(os.path.abspath(weekly_path)),
                              lambda paths: [замеры.parse_weekly(p) for p in paths], args, "еженедельные")
        if got is None:
            if параметры.yes(args.plan_only):
                print("План дополнения показан, файл не создан.")
                return 0
            return 1
        parsed = got[0]
        for code, text, where in parsed.problems:
            print("⚠️ %s (%s)" % (text, where))
        print("📄 %s (еженедельные): %d замеров" % (os.path.basename(weekly_path), len(parsed.rows)))
        stat.append([os.path.basename(weekly_path) + " (еженедельные)", len(parsed.rows)])
        if parsed.rows:
            weekly = замеры.to_frame(parsed.rows)
    if not frames and weekly is None:
        print("⚠️ Замеры не найдены, база не создана.")
        return 0
    new = pd.concat(frames, ignore_index=True) if frames else None

    old = None
    if db_path:
        old = pd.read_excel(db_path, sheet_name="Данные")
        print("📚 Прежняя база: %d строк" % len(old))
    nb_text = str(args.neighbors or "").strip()
    nb = None if nb_text.lower() in ("нет", "no") else замеры.parse_pairs(nb_text)
    data = замеры.combine([new, weekly, old], neighbours=nb)
    if data.attrs.get("neighbours"):
        print("ℹ️ Соседние скважины склеены (%s), строк переименовано: %d" % (
            "; ".join("%s→%s" % kv for kv in data.attrs["neighbours"].items()), data.attrs["neighbours_rows"]))
    if data.attrs.get("replaced"):
        print("ℹ️ Дублей (один замер в нескольких источниках или в прежней базе) слито: %d" % data.attrs["replaced"])
    if data.attrs.get("layer_filled"):
        print("ℹ️ Горизонт не был проставлен, взят по скважине из последнего года: %d строк" % data.attrs["layer_filled"])
    if data.attrs.get("layer_conflicts"):
        print("⚠️ Горизонт в строках отличается от последнего года (оставлен из файла): %d" % data.attrs["layer_conflicts"])
    if data.attrs.get("layer_unresolved"):
        print("⚠️ Горизонт не определён ни в одном файле: %d строк" % data.attrs["layer_unresolved"])
    expl = data[data["Категория"] == "Эксплуатационные"]
    no_group = sorted(set(expl.loc[expl["ГСП"].fillna("").astype(str).str.strip() == "", "Скважина"]))
    if no_group:
        print("⚠️ Эксплуатационные без ГСП (не в справочнике скважин и не в строках файлов): %s" % ", ".join(map(str, no_group)))
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
                      ["Замеров уровня", int(data["Уровень жидкости"].notna().sum())],
                      ["Эксплуатационных скважин без ГСП", len(no_group)]],
                     columns=["Параметр", "Значение"]).to_excel(xw, sheet_name="Статистика", index=False)
        pd.DataFrame(stat, columns=["Файл", "Замеров"]).to_excel(xw, sheet_name="Файлы", index=False)
    print("✅ %s: %d строк, %d скважин" % (out, len(data), data["Скважина"].nunique()))
    if recalc:
        pc_module = importlib.import_module("pxg_base.modules.Пересчёт_давлений")
        pc_module.build(out, refs_path, "Пересчёт_давлений.xlsx", avg_path=weekly_path or None, log=print)
    return 0


if __name__ == "__main__":
    sys.exit(main())
