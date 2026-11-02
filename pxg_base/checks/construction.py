"""Проверка исходников «Шаблона конструкции из свода скважин»: разбор свода (pxg_core.well_construction) в общем отчёте."""
from __future__ import annotations

from typing import Dict

from pxg_core import qc, well_construction as wc
from pxg_core.qc import Report

LEVEL = {"ошибка": qc.ERROR, "предупреждение": qc.WARN, "заметка": qc.NOTE}
LABELS = {"NOPROD": "Нет эксплуатационной колонны", "SWAP": "«От» больше «до»", "SKIP": "Элемент не выгружен",
          "NUM": "Текст в числе", "DEPTH": "Глубина выше/ниже башмака", "ORDER": "Порядок колонн", "EMPTY": "Нет конструкции",
          "TEXT": "Текст в графе работ", "ALT": "Альтитуда: свод и Атлас", "FILTER": "Перфорации отсеяны по глубине"}


def check_construction(values: Dict[str, str]) -> Report:
    rep = Report(title="Шаблон конструкции из свода скважин")
    path = (values.get("file") or "").strip()
    if not qc.check_path(rep, path, "Свод скважин", "file"):
        if not path:
            rep.error("FILE", "Не указан свод скважин")
        return rep
    try:
        text = (values.get("max_perf") or "").strip().replace(",", ".")
        book = wc.read(path, date=values.get("date") or "", max_perf=float(text) if text else wc.DEFAULT_MAX_PERF_DEPTH)
    except ValueError as err:
        rep.error("HEADER", str(err), file=path)
        return rep
    atlas_alt, source = None, ""
    try:
        if (values.get("alt_file") or "").strip():
            atlas_alt, source = wc.file_altitudes(values["alt_file"].strip())
        elif (values.get("atlas_storage") or "").strip() or (values.get("atlas_project") or "").strip():
            atlas_alt, source = wc.atlas_altitudes(values.get("atlas_storage") or "", values.get("atlas_project") or "")
    except (ValueError, OSError) as err:
        rep.warn("FILE", "Альтитуды Атласа не прочитаны, сверка не делается: %s" % err)
    if atlas_alt is not None:
        wc.compare_altitudes(book, atlas_alt, source)
        rep.saw("альтитуды сверены с источником: %s (%d скважин)" % (source, len(atlas_alt)))
    wc.ao_table(book, atlas_alt, rotor=(values.get("rotor", "1") in ("1", "true", "y", "да")))   # замечания о высоте стола
    rep.saw("%d скважин, %d элементов конструкции" % (len(book.wells), sum(len(w.elements) for w in book.wells)))
    for i in book.issues:
        rep.add(LEVEL[i.level], i.code, i.message, file=path, row=i.row, well=i.well, hint=i.hint)
    return rep


qc.CODES.update(LABELS)


def check_construction_word(values: Dict[str, str]) -> Report:
    """Проверка исходников «Конструкции из Word для Атласа»: тот же разбор, что у запуска."""
    from pxg_core import well_construction_word as wcw
    rep = Report(title="Конструкции из Word для Атласа")
    paths = [x.strip().strip('"') for x in (values.get("files") or "").splitlines() if x.strip()]
    if not paths:
        rep.error("FILE", "Не указаны файлы Word")
        return rep
    text = (values.get("max_perf") or "").strip().replace(",", ".")
    total = 0
    for p in paths:
        if not qc.check_path(rep, p, "Перечень скважин", "file"):
            continue
        try:
            res = wcw.read(p, max_perf=float(text) if text else wcw.DEFAULT_MAX_PERF_DEPTH)
        except (ValueError, OSError, KeyError) as err:
            rep.error("FILE", "Файл не прочитан: %s" % err, file=p)
            continue
        total += len(res.snapshots)
        for i in res.issues:
            rep.add(LEVEL[i.level], i.code, i.message, file=p, well=i.well, row=i.source)
    rep.saw("%d снимков конструкции" % total)
    return rep


qc.CODES.update({"LINE": "Строка конструкции не разобрана", "DATE": "Нет даты исследования", "EMPTY": "Нет элементов конструкции",
                 "BOTTOM": "Нет текущего забоя", "DUP": "Повтор строки"})
