"""Замеры давлений: исходная база по месячным файлам замеров и база с пересчётом на нужную глубину.

Объединяет «База давлений по замерам», «Пересчёт давлений» и разбор шаблонов из «копирования файлов замеров по шаблонам».
Параметры: --folder (папка с файлами замеров, подпапки тоже), --db (прежняя исходная база для дозаписи), --refs (книга
«Альтитуды» и «Перфорации»; без неё пересчёта нет), --target (perf: верх перфораций, depth: одна глубина для всех), --depth,
--excess-limit, --excluded, --level-sign, --add-atm. Результат в текущей папке: «БД_замеры_исходные.xlsx»,
«БД_замеры_пересчёт.xlsx» и txt-выгрузка «скважина, дата, давление (бар)».
"""
from __future__ import annotations

import os
import sys

import pandas as pd

from pxg_core import замеры, параметры, пересчет_давлений as pc

SOURCE_XLSX = "БД_замеры_исходные.xlsx"
RECALC_XLSX = "БД_замеры_пересчёт.xlsx"


def _yes(value, default=False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in ("да", "y", "yes", "1", "true")


def _number(text, name):
    try:
        return float(str(text).replace(",", ".").strip())
    except ValueError:
        print("❌ %s не число: %s" % (name, text))
        return None


def main(argv=None):
    args = параметры.parse(
        "Замеры давлений", argv,
        folder="папка с файлами замеров (Excel), подпапки тоже",
        db="прежняя исходная база для дозаписи (лист «Данные»), необязательно",
        refs="книга со справочниками: листы «Альтитуды» и «Перфорации»; без неё пересчёта нет",
        target="perf: на верх перфораций каждой скважины; depth: на одну глубину для всех",
        depth="глубина для target=depth: абсолютная отметка, м (ниже уровня моря со знаком минус или без него)",
        excess_limit="Руст ниже этого значения у наблюдательных, контрольных и поглотительных — избыточное давление",
        excluded="скважины без пересчёта через запятую (по умолчанию 8, 11, 110, 122, 447)",
        level_sign="auto: уровень всегда ниже устья; as_is: как в отчёте",
        add_atm="да: прибавлять 1,01325 к давлению в барах")
    folder = параметры.ask_path("Папка с файлами замеров", args.folder, "folder")
    if not folder:
        print("❌ Папка не выбрана.")
        return 1
    limit = _number(args.excess_limit, "Порог избыточного давления") if args.excess_limit not in (None, "") else замеры.EXCESS_LIMIT
    if limit is None:
        return 1
    target = None
    if str(args.target or "perf").strip() == "depth":
        target = _number(args.depth, "Глубина пересчёта") if args.depth not in (None, "") else None
        if target is None:
            print("❌ Для пересчёта на одну глубину укажите глубину (абсолютная отметка, м).")
            return 1
        target = abs(target)    # как у отметки перфорации: глубина ниже уровня моря, знак убирается
    try:
        excluded = [int(x) for x in str(args.excluded if args.excluded not in (None, "") else
                                        ",".join(map(str, pc.DEFAULT_EXCLUDED))).replace(";", ",").split(",") if x.strip()]
    except ValueError:
        print("❌ Исключения должны быть номерами скважин через запятую: %s" % args.excluded)
        return 1

    files = замеры.find_files(folder)
    if not files:
        print("⚠️ В папке и подпапках нет файлов замеров (имя с «набл», «замер» или «скважин»/«отчёт» и месяцем): %s" % folder)
        return 0
    print("🔎 Файлов замеров найдено: %d" % len(files))
    frames, stat, problems = [], [], []
    for f in files:
        parsed = замеры.parse_file(f, limit)
        rel = os.path.relpath(f, folder)
        for code, text, where in parsed.problems:
            print("⚠️ %s (%s)" % (text, where))
            problems.append([rel, code, text, where])
        print("📄 %s: %s, %d замеров" % (rel, замеры.TEMPLATES.get(parsed.template, "шаблон не определён"), len(parsed.rows)))
        stat.append([rel, замеры.TEMPLATES.get(parsed.template, "не определён"), len(parsed.rows)])
        if parsed.rows:
            frames.append(замеры.to_frame(parsed.rows))
    if not frames:
        print("⚠️ Замеры не найдены, базы не созданы.")
        return 0
    new = pd.concat(frames, ignore_index=True)
    old = None
    db_path = параметры.ask_path("Прежняя исходная база для дозаписи (Enter — создать новую)", args.db if args.db is not None else "")
    if db_path:
        old = pd.read_excel(db_path, sheet_name="Данные")
        print("📚 Прежняя база: %d строк" % len(old))
    data = замеры.merge(old, new)
    if data.attrs.get("replaced"):
        print("⚠️ Строк с тем же ключом (скважина, дата, горизонт) заменено новыми: %d" % data.attrs["replaced"])

    with pd.ExcelWriter(SOURCE_XLSX, engine="openpyxl") as xw:
        data.to_excel(xw, sheet_name="Данные", index=False)
        for sheet, col in (("Руст по месяцам", "Руст"), ("Избыточное по месяцам", "Избыточное давление"),
                           ("Рпл по месяцам", "Рпл"), ("Уровень по месяцам", "Уровень жидкости")):
            wide = замеры.by_month(data, col)
            if not wide.empty:
                wide.to_excel(xw, sheet_name=sheet)
        pd.DataFrame([["Всего записей", len(data)], ["Уникальных скважин", data["Скважина"].nunique()],
                      ["Замеров Руст", int(data["Руст"].notna().sum())],
                      ["Замеров избыточного давления", int(data["Избыточное давление"].notna().sum())],
                      ["Замеров Рпл", int(data["Рпл"].notna().sum())],
                      ["Замеров уровня", int(data["Уровень жидкости"].notna().sum())]],
                     columns=["Параметр", "Значение"]).to_excel(xw, sheet_name="Статистика", index=False)
        pd.DataFrame(stat, columns=["Файл", "Шаблон", "Замеров"]).to_excel(xw, sheet_name="Файлы", index=False)
        if problems:
            pd.DataFrame(problems, columns=["Файл", "Код", "Что не так", "Где"]).to_excel(xw, sheet_name="Проблемы", index=False)
    print("✅ Исходная база: %s, %d строк, %d скважин" % (SOURCE_XLSX, len(data), data["Скважина"].nunique()))

    refs_path = параметры.ask_path("Справочники: альтитуды и перфорации (Enter — без пересчёта)", args.refs if args.refs is not None else "")
    if not refs_path:
        print("ℹ️ Справочники не указаны: база с пересчётом не создаётся.")
        return 0
    refs = pc.read_refs(refs_path)
    print("📚 Справочники: альтитуд %d, отметок перфорации %d" % (len(refs.altitude), len(refs.perf_mark)))
    atm = _yes(args.add_atm)
    sign = "as_is" if str(args.level_sign or "auto").strip() == "as_is" else "auto"
    res = pc.recalc(pc.normalize_db(data), refs, excluded, sign, atm, target=target)
    stat = res["Способ расчёта"].value_counts()
    for how, n in stat.items():
        print("   %-45s %d" % (how, n))
    for how, name in ((pc.M_NO_ALT, "Нет альтитуды"), (pc.M_NO_PERF, "Нет отметки перфорации")):
        missing = sorted(set(res.loc[res["Способ расчёта"] == how, "Скважина"]))
        if missing and (how != pc.M_NO_PERF or target is None):
            print("⚠️ %s: %s" % (name, ", ".join(map(str, missing[:30]))))
    bar = res.attrs["bar_col"]
    differ = res[res["Сверка с файлом"].fillna("") != ""]
    with pd.ExcelWriter(RECALC_XLSX, engine="openpyxl") as xw:
        res.to_excel(xw, sheet_name="Пересчёт", index=False)
        differ.to_excel(xw, sheet_name="Расхождения с файлом", index=False)
        pd.DataFrame({"Способ расчёта": stat.index, "Строк": stat.values}).to_excel(xw, sheet_name="Сводка", index=False)
    suffix = "perf" if target is None else "%gm" % target
    txt = "давления_%s_бар.txt" % suffix
    n = замеры.write_txt(res, bar, txt)
    print("📝 %s: %d строк" % (txt, n))
    if len(differ):
        print("⚠️ Расхождений значений из файла (ES, плотность) с расчётом: %d, см. лист «Расхождения с файлом»" % len(differ))
    print("✅ База с пересчётом: %s (%s)" % (RECALC_XLSX, bar))
    return 0


if __name__ == "__main__":
    sys.exit(main())
