"""База ГИС: книга «База ГИС-контроль» (лист = скважина) → замеры по датам и пачкам, свод в Excel и таблицы для Атласа.

Разбор, формулы и правила — `pxg_core.gis`; проверка содержания — `pxg_core.gis_qc`; выгрузка — `pxg_core.gis_export`.
Легенда пачек («цвет → пачка») берётся из запомненного выбора (форма модуля, `pxg_core.gis_legend`); цвет без подтверждённой
пачки в таблицы для Атласа не попадает. Параметры: --file (книга), --perf («Глубины_перфораций.xlsx», необязательно),
--legend (отдельный JSON с легендой, необязательно). Результаты пишутся в текущую папку.
"""
from __future__ import annotations

import os
import sys

from pxg_core import gis, gis_export, gis_legend, gis_qc, параметры

# Запуск из подпроцесса: репозиторий в sys.path уже есть (корень задаёт runner)
_ = sys


def main(argv=None):
    args = параметры.parse(
        "База ГИС", argv,
        file="книга «База ГИС-контроль» (Excel)",
        perf="«Глубины_перфораций.xlsx» (листы «перфорации» и «альтитуды»), необязательно",
        legend="JSON с легендой пачек {лист: {цвет: пачка}}, необязательно")
    path = параметры.ask_path("Книга «База ГИС-контроль»", args.file)
    if not path:
        print("❌ Книга не выбрана.")
        return 1
    file_alts = perfs = None
    perf = параметры.ask_path("Файл «Глубины_перфораций» (Enter — без него)", args.perf if args.perf is not None else "")
    if perf:
        from gsp_maps.inputs import load_perforations
        depths, alt = load_perforations(perf)
        file_alts, perfs = gis.keyed(alt), gis.keyed(depths)
        print("📍 Из файла перфораций: %d альтитуд, %d перфораций" % (len(alt), len(depths)))
    legends = gis_legend.load_file((args.legend or "").strip()) or gis_legend.load_saved(path)
    results = gis.load_book(path, legends=legends, file_alts=file_alts, perfs=perfs)
    if not results:
        print("⚠️ В книге нет листов-скважин (лист с шапкой «Дата»).")
        return 0
    bottom = gis.read_bottom(path)
    report = gis.report(results)
    print("📚 Листов скважин: %d, замеров: %d, строк интервалов: %d" % (
        len(results), int(report["Замеров"].sum()), int(report["Строк интервалов"].sum())))
    unconfirmed = sum(1 for r in results.values() for e in r.legend if e.status != "ок")
    unassigned = sum(1 for r in results.values() for x in r.data_rows if not x.pack)
    if unconfirmed:
        print("⚠️ В легенде пачек цветов «проверить» / «не распознан»: %d (подтвердите в форме)" % unconfirmed)
    if unassigned:
        print("⚠️ Строк без пачки: %d — в таблицы для Атласа не попадут (останутся в Excel и в «Проверке»)" % unassigned)
    found, dropped = gis_qc.check_results(results, bottom)
    kinds = {}
    for i in found:
        kinds[i.level] = kinds.get(i.level, 0) + 1
    print("🔎 Проверка содержания: %s" % (", ".join("%s: %d" % kv for kv in sorted(kinds.items())) or "замечаний нет"))
    files = gis_export.export(results, os.getcwd(), bottom, source=path)
    for f in files:
        print("✅ %s" % os.path.basename(f))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
