"""База_шахматка_Лена: шахматки отбора и закачки и книга воды в единую базу (Excel и SQLite).

Параметры: --otbor (шахматка отбора), --zakachka (шахматка закачки), --voda (книга воды), --output, --otbor-year, --zak-year.
Берётся Qгаз.пром: пересчитывается по исходным данным и сравнивается с тем, что в файле; ошибки формул — на листе «Контроль_формул».
"""
from __future__ import annotations

import os

from pxg_core import параметры, шахматка


def _year(text):
    try:
        return int(str(text).strip()) if text not in (None, "") else None
    except ValueError:
        return None


def main(argv=None):
    args = параметры.parse(
        "База шахматка (Лена)", argv,
        otbor="шахматка отбора (xlsx или xls)", zakachka="шахматка закачки (xlsx или xls)", voda="книга «Вода» (xlsx)",
        output="имя файла результата", otbor_year="год начала сезона для отбора (по умолчанию из имени файла)",
        zak_year="год первых суток закачки (по умолчанию из имени файла)")
    otbor = параметры.ask_path("Шахматка отбора (Enter — пропустить)", args.otbor)
    zak = параметры.ask_path("Шахматка закачки (Enter — пропустить)", args.zakachka)
    voda = параметры.ask_path("Книга «Вода» (Enter — пропустить)", args.voda)
    if not (otbor or zak or voda):
        print("❌ Не выбран ни один файл.")
        return 1
    out = (args.output or "").strip() or "База_шахматка_Лена.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    res = шахматка.build(otbor, zak, voda, out, _year(args.otbor_year), _year(args.zak_year))
    issues = res["issues"]
    if len(issues):
        bad = int((issues["Уровень"] == "ошибка").sum())
        print("⚠️ Замечаний к формулам: %d (ошибок %d), подробности на листе «Контроль_формул»" % (len(issues), bad))
        for _i, r in issues[issues["Уровень"] == "ошибка"].head(12).iterrows():
            print("   • [%s] %s: %s" % (r["Файл"], r["Вид"], str(r["Описание"])[:160]))
    print("✅ %s и %s: %d скважин" % (os.path.basename(res["out"]), os.path.basename(res["sqlite"]), res["wells"]))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
