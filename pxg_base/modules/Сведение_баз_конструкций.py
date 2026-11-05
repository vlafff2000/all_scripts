"""Сведение баз конструкций: две таблицы конструкции (формат шаблона Атласа) → расхождения с подсказкой → единая база.

База A — из «Шаблона конструкции из свода» (дата ничего не значит, одна конструкция на скважину), база B — из Word (у скважины могут быть несколько дат):
сравнивается A с САМОЙ СВЕЖЕЙ конструкцией B (дата показана в таблице), более ранние даты B не проверяются и остаются как есть.
Шаг 1: запуск с --a и --b даёт `Расхождения_конструкций.xlsx` (лист «Расхождения»: что где не сходится, подсказка и причина, столбец «Решение»).
Шаг 2: инженер заполняет «Решение» (A / B / вручную / исключить) и вносит ручные значения; запуск с --decisions собирает `Сведённая_конструкция.xlsx`
(загружается в Атлас как шаблон конструкции). Ручное решение главнее подсказки; без файла решений свод строится по подсказкам и честно говорит об этом.
Параметры: --a, --b (файлы), --decisions, --tolerance (допуск глубин, м; по умолчанию 0,5), --prefer (A или B при спорных значениях; по умолчанию B: данные из отчётов ГИС (OCR) главнее).
"""
from __future__ import annotations

import os
import sys

import pandas as pd

from pxg_core import construction_merge as cm, параметры

_ = sys


def main(argv=None):
    args = параметры.parse(
        "Сведение баз конструкций", argv,
        a="база A: из свода скважин (одна конструкция на скважину, дата не важна)", b="база B: из Word (может быть несколько дат; сравнивается самая свежая)",
        decisions="файл расхождений с решениями инженера (необязательно)",
        tolerance="допуск глубин, м (по умолчанию 0,5)", prefer="какая база главнее в спорных случаях: A или B (по умолчанию B: данные из отчётов ГИС (OCR) главнее)")
    pa, pb = параметры.ask_path("База A (Excel)", args.a), параметры.ask_path("База B (Excel)", args.b)
    if not pa or not pb:
        print("❌ Нужны обе базы конструкций.")
        return 1
    tol = float((args.tolerance or "").replace(",", ".") or cm.TOLERANCE)
    try:
        a, b = cm.read_base(pa), cm.read_base(pb)
    except (ValueError, OSError) as err:
        print("❌ %s" % err)
        return 1
    diffs = cm.compare(a, b, tol, args.prefer or "B")
    print("📚 A: %d строк, B: %d строк, расхождений: %d" % (len(a), len(b), len(diffs)))
    if len(diffs):
        for kind, n in diffs["Расхождение"].value_counts().items():
            print("   %s: %d" % (kind, n))
    out = os.getcwd()
    with pd.ExcelWriter(os.path.join(out, "Расхождения_конструкций.xlsx"), engine="openpyxl") as xw:
        diffs.to_excel(xw, sheet_name="Расхождения", index=False)
        xw.sheets["Расхождения"].freeze_panes = "A2"
    print("✅ Расхождения_конструкций.xlsx")
    decided = diffs
    if (args.decisions or "").strip():
        try:
            decided = cm.read_decisions(параметры.clean_path(args.decisions))
        except (ValueError, OSError) as err:
            print("❌ %s" % err)
            return 1
        print("📝 Решения инженера прочитаны: %d строк" % len(decided))
    merged, notes = cm.merge(a, b, decided, tol)
    for n in notes:
        print("⚠️ %s" % n)
    if not (args.decisions or "").strip() and len(diffs):
        print("ℹ️ Решений нет: сводная база построена по подсказкам. Проверьте «Расхождения», заполните «Решение» и запустите с --decisions")
    merged.to_excel(os.path.join(out, "Сведённая_конструкция.xlsx"), sheet_name="Конструкция", index=False)
    print("✅ Сведённая_конструкция.xlsx: %d строк" % len(merged))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
