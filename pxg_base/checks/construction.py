"""Проверка исходников «Шаблона конструкции из свода скважин»: разбор свода (pxg_core.well_construction) в общем отчёте."""
from __future__ import annotations

from typing import Dict

from pxg_core import qc, well_construction as wc
from pxg_core.qc import Report

LEVEL = {"ошибка": qc.ERROR, "предупреждение": qc.WARN, "заметка": qc.NOTE}
LABELS = {"NOPROD": "Нет эксплуатационной колонны", "SWAP": "«От» больше «до»", "SKIP": "Элемент не выгружен",
          "NUM": "Текст в числе", "DEPTH": "Глубина выше/ниже башмака", "ORDER": "Порядок колонн", "EMPTY": "Нет конструкции",
          "TEXT": "Текст в графе работ"}


def check_construction(values: Dict[str, str]) -> Report:
    rep = Report(title="Шаблон конструкции из свода скважин")
    path = (values.get("file") or "").strip()
    if not qc.check_path(rep, path, "Свод скважин", "file"):
        if not path:
            rep.error("FILE", "Не указан свод скважин")
        return rep
    try:
        book = wc.read(path, date=values.get("date") or "")
    except ValueError as err:
        rep.error("HEADER", str(err), file=path)
        return rep
    rep.saw("%d скважин, %d элементов конструкции" % (len(book.wells), sum(len(w.elements) for w in book.wells)))
    for i in book.issues:
        rep.add(LEVEL[i.level], i.code, i.message, file=path, row=i.row, well=i.well, hint=i.hint)
    return rep


qc.CODES.update(LABELS)
