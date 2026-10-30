"""Анализ технического состояния скважин: таблица «Анализ ревизии КРУ» → таблицы КРС для Газового Атласа, статистика и приоритет КР.

Читает таблицу анализа (.xls или .xlsx, с цветами ячеек): проведённые КР (год, коды работ, тип по цвету и легенде), песок по ревизиям
КРУ и отчётам АН, спец. ГДИ, потребность в КР. Результаты вскрытия КРУ нового сезона (отдельный файл: скважина + песок) подставляются
в тот же формат, после чего приоритет КР (1 — срочно) пересчитывается по полной истории; правила счёта — в pxg_core/krs.py.

Результат `КРС_для_Атласа.xlsx`: Ремонты, Ревизии КРУ, Спец ГДИ, Приоритет, Потребность (расчёт и сверка с таблицей), статистика (КР по годам и
по ГСП, потребность по годам и ГСП, очередь на ближайшие сезоны) и «Проверка». Приоритет — подсказка с причиной: столбец
«Приоритет вручную» на листе «Приоритет» решает за расчёт и не затирается, если дать прежний результат параметром --prev.
Вторая книга `Таблица_анализа_обновлённая.xlsx` — копия исходной таблицы с подставленными вскрытиями и приоритетом справа.

Параметры: --table, --kru (необязательно), --season (сезон вскрытий, «2025-2026»), --prev, --relapse (new|two), --per-season, --output.
"""
from __future__ import annotations

import os
import re

import pandas as pd

from pxg_core import krs, параметры


def main(argv=None):
    args = параметры.parse(
        "Анализ технического состояния скважин (КРС)", argv,
        table="таблица «Анализ ревизии КРУ» (.xls или .xlsx)",
        kru="результаты вскрытия КРУ нового сезона: Excel/CSV со столбцами «№ скв» и «Песок» (необязательно)",
        season="сезон вскрытий КРУ, например 2025-2026 (по умолчанию — последний сезон в таблице)",
        prev="прежний результат (КРС_для_Атласа.xlsx): ручные приоритеты переносятся",
        relapse="после замены фильтра: new — счёт заново с 3 (по умолчанию), two — повтор песка сразу даёт 2",
        per_season="сколько скважин ремонтировать за сезон в очереди (по умолчанию — среднее за 3 года)",
        output="имя файла результата")
    table = параметры.ask_path("Таблица «Анализ ревизии КРУ»", args.table)
    if not table:
        print("❌ Таблица не выбрана.")
        return 1
    try:
        data, grid = krs.parse(table)
    except ValueError as e:
        print("❌ %s" % e)
        return 1
    print("📚 Таблица: %d скважин, %d ремонтов, %d записей по песку" % (len(data.wells), len(data.works), len(data.revisions)))
    notes = list(data.notes)
    cols = data.columns
    season = (args.season or "").strip()
    if season and not re.fullmatch(r"20\d\d-20\d\d", season):
        print("❌ Сезон надо писать так: 2025-2026.")
        return 1
    if not season and cols.rev:
        season = sorted(cols.rev)[-1]
    kru = параметры.ask_path("", args.kru) if (args.kru or "").strip() else ""
    if (args.kru or "").strip() and not kru:
        return 1
    if kru:
        if not season:
            print("❌ Укажите сезон вскрытий (--season 2025-2026).")
            return 1
        try:
            new = krs.read_new_revisions(kru)
        except ValueError as e:
            print("❌ %s" % e)
            return 1
        notes += krs.add_revisions(data, new, season)
        print("🔧 Вскрытия КРУ %s: %d скважин, песок у %d" % (season, len(new), int(new["Песок"].eq("Да").sum())))
        if season not in cols.rev:
            notes.append(("предупреждение", "В таблице нет столбца «Ревизия КРУ после отбора %s»: вскрытия учтены в расчёте, но в обновлённую копию таблицы не записаны" % season))
    relapse = (args.relapse or krs.RELAPSE_NEW).strip().lower()
    if relapse not in (krs.RELAPSE_NEW, krs.RELAPSE_TWO):
        print("❌ --relapse: new или two.")
        return 1
    manual = krs.read_manual(args.prev) if (args.prev or "").strip() and os.path.isfile(args.prev.strip().strip('"')) else {}
    if manual:
        print("📌 Ручных приоритетов перенесено: %d" % len(manual))
    calc = krs.compute_priorities(data, relapse=relapse)
    prio = krs.final_priorities(data, calc, manual)
    per = int(args.per_season) if (args.per_season or "").strip().isdigit() else None
    stats = krs.stats_tables(data, prio, calc, per_season=per)

    diff = calc[(calc["Совпало"] == "нет") & calc["Год"].isin(list(cols.need))]   # сверка только за годы, по которым в таблице есть «Потребность»
    for _, r in diff.iterrows():
        notes.append(("предупреждение", "Скв. %d, конец %d: расчёт %s, в таблице %s — разберите вручную" % (
            r["Скважина"], r["Год"], "нет" if pd.isna(r["Потребность (расчёт)"]) else int(r["Потребность (расчёт)"]),
            "нет" if r["Потребность (таблица)"] is None or pd.isna(r["Потребность (таблица)"]) else r["Потребность (таблица)"])))
    if not data.gdi.empty and data.revisions is not None:
        sand_last = data.revisions[(data.revisions["Источник"] == "Ревизия КРУ") & (data.revisions["Песок"] == "Да")]
        for _, g in data.gdi[data.gdi["Результат"].str.contains("нет песка", case=False)].iterrows():
            y = krs.season_end_year(g["Сезон"])
            if ((sand_last["Скважина"] == g["Скважина"]) & sand_last["Сезон"].map(krs.season_end_year).eq(y - 1)).any() or \
               ((sand_last["Скважина"] == g["Скважина"]) & sand_last["Сезон"].map(krs.season_end_year).eq(y)).any():
                notes.append(("заметка", "Скв. %d: спец. ГДИ %s — «%s», а в ревизии рядом песок: приоритет по ревизии, решение за инженером" % (g["Скважина"], g["Сезон"], g["Результат"])))
    out = (args.output or "").strip() or "КРС_для_Атласа.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    prio_cols = list(prio.columns)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        data.works.to_excel(xw, sheet_name="Ремонты", index=False)
        data.revisions.sort_values(["Скважина", "Сезон", "Источник"]).to_excel(xw, sheet_name="Ревизии КРУ", index=False)
        data.gdi.to_excel(xw, sheet_name="Спец ГДИ", index=False)
        prio.sort_values(["Приоритет итог", "Скважина"], na_position="last")[prio_cols].to_excel(xw, sheet_name="Приоритет", index=False)
        calc.to_excel(xw, sheet_name="Потребность", index=False)
        for name, df in stats.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
        info = pd.DataFrame([["Версия формата", 1], ["Источник", os.path.basename(table)], ["Сезон вскрытий КРУ", season],
                             ["Правило после замены фильтра", relapse], ["Скважин", len(data.wells)]], columns=["Параметр", "Значение"])
        info.to_excel(xw, sheet_name="Параметры", index=False)
        krs.revision_notes(type("D", (), {"notes": notes})()).to_excel(xw, sheet_name="Проверка", index=False)
    upd = os.path.splitext(out)[0].replace("КРС_для_Атласа", "Таблица_анализа_обновлённая") + ".xlsx"
    if upd == out:
        upd = "Таблица_анализа_обновлённая.xlsx"
    krs.write_updated_table(grid, cols, data, prio, season, upd)
    warns = sum(1 for n in notes if n[0] == "предупреждение")
    need = int(prio["Приоритет итог"].notna().sum())
    print("✅ %s: ремонтов %d, нуждаются в КР %d (приоритет 1: %d), замечаний %d" % (
        out, len(data.works), need, int(prio["Приоритет итог"].eq(1).sum()), warns))
    print("✅ %s" % upd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
