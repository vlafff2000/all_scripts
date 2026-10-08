"""Пересчёт давлений: Рпл приведённое -> давление на верх перфораций, include-таблицы для tNavigator.

Заменяет Excel «ФАЙЛ_СО_ВСЕМИ_ДАВЛЕНИЯМИ». Параметры: --db (база «База давлений по замерам»), --refs (книга с листами
«Альтитуды» и «Перфорации»), --excluded, --level-sign, --add-atm, --inc-mean, --inc-exploit, --inc-obs, --inc-obs-raw,
--output. Формулы и обоснование — pxg_core/пересчет_давлений.py.
"""
from __future__ import annotations

import sys

import pandas as pd

from pxg_core import параметры, пересчет_давлений as pc


def _yes(value, default=False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in ("да", "y", "yes", "1", "true")


def main(argv=None):
    args = параметры.parse(
        "Пересчёт давлений на верх перфораций", argv,
        db="база «База давлений по замерам» (Excel, лист «Данные»)",
        refs="книга со справочниками: листы «Альтитуды» и «Перфорации»",
        excluded="скважины без пересчёта через запятую (по умолчанию 8, 11, 110, 122, 447)",
        level_sign="auto: уровень всегда ниже устья (−|Нст|); as_is: знак как в отчёте",
        add_atm="да: прибавлять 1,01325 (абсолютное давление в барах)",
        inc_mean="include: среднее пластовое", inc_exploit="include: эксплуатационные",
        inc_obs="include: наблюдательные с пересчётом", inc_obs_raw="include: наблюдательные без пересчёта",
        output="имя файла результата")
    db_path = параметры.ask_path("База давлений по замерам", args.db)
    refs_path = параметры.ask_path("Книга со справочниками (Альтитуды, Перфорации)", args.refs)
    if not db_path or not refs_path:
        print("❌ Нужны база давлений и справочники.")
        return 1
    try:
        excluded = [int(x) for x in str(args.excluded if args.excluded not in (None, "") else
                                        ",".join(map(str, pc.DEFAULT_EXCLUDED))).replace(";", ",").split(",") if x.strip()]
    except ValueError:
        print("❌ Исключения должны быть номерами скважин через запятую: %s" % args.excluded)
        return 1
    sign = "as_is" if str(args.level_sign or "auto").strip() == "as_is" else "auto"
    atm = _yes(args.add_atm)

    refs = pc.read_refs(refs_path)
    print("📚 Справочники: альтитуд %d, отметок перфорации %d" % (len(refs.altitude), len(refs.perf_mark)))
    db = pc.read_measurements(db_path)
    print("📄 Замеров в базе: %d" % len(db))
    res = pc.recalc(db, refs, excluded, sign, atm)
    stat = res["Способ расчёта"].value_counts()
    for how, n in stat.items():
        print("   %-45s %d" % (how, n))
    missing = sorted(set(res.loc[res["Способ расчёта"] == pc.M_NO_ALT, "Скважина"]))
    if missing:
        print("⚠️ Нет альтитуды: %s" % ", ".join(map(str, missing[:30])))
    missing = sorted(set(res.loc[res["Способ расчёта"] == pc.M_NO_PERF, "Скважина"]))
    if missing:
        print("⚠️ Нет отметки перфорации: %s" % ", ".join(map(str, missing[:30])))

    inc = pc.include_frames(res, atm)
    wanted = {"include_среднее_пластовое": _yes(args.inc_mean, True), "include_эксплуатационные": _yes(args.inc_exploit, True),
              "include_набл_с_пересчётом": _yes(args.inc_obs, True),
              "include_набл_без_пересчёта": _yes(args.inc_obs_raw, False)}
    out = (args.output or "").strip() or "Пересчёт_давлений.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        res.to_excel(xw, sheet_name="Пересчёт", index=False)
        for name, frame in inc.items():
            if wanted[name]:
                frame.to_excel(xw, sheet_name=name[:31], index=False)
                print("📝 %s: %d строк" % (name, len(frame)))
        pd.DataFrame({"Способ расчёта": stat.index, "Строк": stat.values}).to_excel(xw, sheet_name="Сводка", index=False)
    print("✅ %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
