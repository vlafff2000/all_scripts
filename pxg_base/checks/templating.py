"""Проверка исходников модуля «БД шаблонирования»."""
from __future__ import annotations

import os
from typing import Dict

from pxg_core import qc, templating_db
from pxg_core.qc import Report


def check_templating(values: Dict[str, str]) -> Report:
    rep = Report(title="БД шаблонирования")
    got = 0
    gis, cons = (values.get("gis_db") or "").strip(), (values.get("construction") or "").strip()
    for path, label, fn in ((gis, "БД ГИС из отчётов", templating_db.from_gis_db), (cons, "Конструкции из Word", templating_db.from_construction)):
        if not path:
            continue
        qc.check_path(rep, path, label, "folder" if path is gis else "file")
        try:
            n = len(fn(path))
            got += n
            rep.saw("%s: отбивок %d" % (label, n))
        except Exception as e:
            rep.error("FILE", str(e), file=path)
    for line in (values.get("excel") or "").splitlines():
        p = line.strip().strip('"')
        if not p:
            continue
        files = [os.path.join(d, f) for d, _s, fs in os.walk(p) for f in fs if f.lower().endswith((".xlsx", ".xlsm", ".csv"))] if os.path.isdir(p) else [p]
        for f in files:
            try:
                rows, notes = templating_db.from_excel(f)
                got += len(rows)
                rep.saw("%s: отбивок %d" % (os.path.basename(f), len(rows)))
                for n in notes:
                    rep.warn("FILE", n, file=f)
            except Exception as e:
                rep.error("FILE", str(e), file=f)
    dec = (values.get("decisions") or "").strip()
    if dec:
        try:
            rep.saw("Решений инженера: %d" % len(templating_db.load_decisions(dec)))
        except Exception as e:
            rep.error("FILE", str(e), file=dec)
    if not (gis or cons or (values.get("excel") or "").strip() or (values.get("reports") or "").strip()):
        rep.error("FILE", "Не указан ни один источник")
    elif not got and not (values.get("reports") or "").strip():
        rep.warn("DATA", "В источниках не найдено ни одной отбивки забоя")
    return rep
