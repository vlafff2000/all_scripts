"""Проверка исходников «Базы ГИС»: разбор книги (pxg_core.gis) и правила содержания (pxg_core.gis_qc) в общем отчёте."""
from __future__ import annotations

from typing import Dict

from pxg_core import gis, gis_legend, gis_qc, qc
from pxg_core.qc import Report

LEVEL = {"error": qc.ERROR, "warn": qc.WARN, "note": qc.NOTE}
LABELS = {**gis_qc.CODES, "no_header": "Нет шапки листа", "date_unparsed": "Дата не распознана", "date_year_only": "В дате нет месяца",
          "season_none": "Месяц вне сезонов", "interval_text": "Текст в интервале", "kg_text": "Кг не число",
          "interval_reversed": "«До» меньше «от»", "interval_incomplete": "Интервал неполный", "no_alt": "Нет альтитуды",
          "alt_mismatch": "Альтитуда: лист и файл расходятся", "legend_check": "Легенда пачек: проверить",
          "legend_unknown": "Цвет без пачки", "gvk_twice": "Второй ГВК в пачке", "block_empty": "Замер без данных",
          "rows_without_date": "Строки без даты", "tab_color": "Цвет ярлыка", "date_shifted": "Дата ниже первого интервала"}


def load(values: Dict[str, str]):
    """Читает книгу и необязательный файл «Глубины_перфораций» так же, как запуск; возвращает (результаты, забой) или None."""
    path = (values.get("file") or "").strip()
    perf = (values.get("perf") or "").strip()
    file_alts = perfs = None
    if perf:
        from gsp_maps.inputs import load_perforations
        depths, alt = load_perforations(perf)
        file_alts, perfs = gis.keyed(alt), gis.keyed(depths)
    legends = gis_legend_values(values)
    return gis.load_book(path, legends=legends, file_alts=file_alts, perfs=perfs), gis.read_bottom(path)


def gis_legend_values(values: Dict[str, str]) -> dict:
    """Запомненный выбор пачек для этой книги; отдельный файл легенды (параметр `legend`) главнее."""
    path = (values.get("file") or "").strip()
    return gis_legend.load_file((values.get("legend") or "").strip()) or gis_legend.load_saved(path)


def check_gis(values: Dict[str, str]) -> Report:
    rep = Report(title="База ГИС")
    path = (values.get("file") or "").strip()
    if not qc.check_path(rep, path, "Книга «База ГИС-контроль»", "file"):
        if not path:
            rep.error("FILE", "Не указана книга ГИС")
        return rep
    perf = (values.get("perf") or "").strip()
    if perf:
        qc.check_path(rep, perf, "Файл «Глубины_перфораций»")
    results, bottom = load(values)
    rep.saw("%d лист(ов) скважин, %d замеров, %d строк интервалов" % (
        len(results), sum(len(r.blocks) for r in results.values()), sum(len(r.data_rows) for r in results.values())))
    for res in results.values():
        for i in res.issues:
            rep.add(LEVEL[i.level], i.code, i.message, file=path, sheet=res.sheet, row=i.row or "", well=res.well, value=i.value)
    found, dropped = gis_qc.check_results(results, bottom)
    sheet_well = {r.sheet: r.well for r in results.values()}
    for i in found:
        rep.add(LEVEL[i.level], i.code, i.message, file=path, sheet=i.sheet, row=i.row or "", well=sheet_well.get(i.sheet, ""),
                value=i.value)
    return rep


qc.CODES.update(LABELS)
