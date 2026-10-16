"""Проверка исходников «Импорта данных ЭЛПРО»: разбор всех файлов папки без записи результата."""
from __future__ import annotations

import os

from pxg_core import элпро, qc
from pxg_core.qc import Report


def check_elpro(values: dict) -> Report:
    rep = Report(title="Импорт данных ЭЛПРО")
    folder = (values.get("folder") or "").strip()
    if not qc.check_path(rep, folder, "Папка с файлами ЭЛПРО", "folder"):
        if not folder:
            rep.error("FILE", "Не указана папка с файлами ЭЛПРО")
        return rep
    db = (values.get("db") or "").strip()
    if db:
        qc.check_path(rep, db, "Прежняя база")
    files = [f for f in qc.list_excel(folder, recursive=True) if not os.path.basename(f).startswith("~$")]  # и подпапки сезонов
    if not files:
        rep.note("FILE", "В папке нет файлов Excel")
        return rep
    data, infos, cov, warn = элпро.build(files)
    for text in warn:
        rep.warn("ELPRO", text)
    if data.empty:
        rep.error("ELPRO", "Данные ЭЛПРО не найдены ни в одном файле")
        return rep
    rep.saw("%d файл(ов), %d строк, %d скважин, групп: %d"
            % (len(files), len(data), data["Скважина"].nunique(), data["ГСП"].nunique()))
    for row in cov[cov["Статус"] != "есть"].itertuples():
        rep.warn("COVER", "%s, %s: %s" % (row.ГСП, row.Месяц, row.Статус.replace("ПРОПУСК: ", "пропуск — ")))
    return rep
