"""Данные для мастера сопоставления шапок ГДИ: шаблоны отчётов в папке, поля базы, подсказки и варианты выбора.

Мастер (панель «Сопоставление шапок» в «Базе ПХГ») показывает по каждому найденному шаблону таблицу «поле базы → величина
отчёта» с пробным значением; подсказка автоматическая, выбор за инженером и запоминается за шаблоном (`гдис_карта.save`).
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from . import гдис_карта as kart
from . import гдис_pdf as pdf

_CACHE: Dict[str, pdf.Scan] = {}


def _key(path: str) -> str:
    st = os.stat(path)
    return "%s|%d|%d" % (os.path.abspath(path), st.st_size, int(st.st_mtime))


def scan_cached(path: str) -> pdf.Scan:
    """Чтение отчёта с кэшем по пути, размеру и времени изменения: повторное открытие мастера быстрое."""
    key = _key(path)
    if key not in _CACHE:
        if len(_CACHE) > 500:
            _CACHE.clear()
        _CACHE[key] = pdf.scan_report(path)
    return _CACHE[key]


def scan_many(files: List[str]) -> List[pdf.Scan]:
    """Чтение многих отчётов: непрочитанные — по ядрам (процессы), прочитанные берутся из кэша."""
    from .parallel import map_jobs
    new = [f for f in files if _key(f) not in _CACHE]
    if len(new) > 1:
        for f, sc in zip(new, map_jobs(pdf.scan_report, new, 150.0)):
            _CACHE[_key(f)] = sc
    return [scan_cached(f) for f in files]


def _item_view(it: pdf.Item) -> dict:
    return {"loc": kart.locator(it), "label": it.label, "unit": it.unit, "method": it.method, "kind": it.kind,
            "heading": it.heading, "sample": it.sample[:80]}


def templates(folder: str, mapping_file: str = "", method_pref: str = "4") -> dict:
    """Шаблоны отчётов папки: {templates: [...], files, errors: [{file, error}]}."""
    files = pdf.find_reports(folder)
    scans = scan_many(files)
    errors = [{"file": s.file, "error": s.error} for s in scans if s.error]
    groups: Dict[str, List[pdf.Scan]] = {}
    for s in scans:
        if not s.error:
            groups.setdefault(s.fingerprint, []).append(s)
    out = []
    for fp, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        rep = max(members, key=lambda s: len(s.items))
        mapping, source = kart.effective(rep, kart.load_saved(fp, mapping_file), method_pref)
        auto = kart.suggest(rep, method_pref)
        rows = []
        for t in kart.TARGETS:
            cur = mapping.get(t.key)
            item = kart.find_item(rep.items, cur) if cur else None
            rows.append({"key": t.key, "label": t.label, "scope": t.scope, "dim": t.dim, "required": t.required,
                         "hint": t.hint, "current": cur, "auto": auto.get(t.key), "source": source[t.key],
                         "found": item is not None or not cur, "sample": item.sample[:80] if item else "",
                         "options": [_item_view(it) for it in kart.candidates(rep, t)]})
        out.append({"id": fp, "files": len(members), "program": rep.program, "example": rep.file,
                    "names": [m.file for m in members[:6]], "rows": rows,
                    "saved": bool(kart.load_saved(fp))})
    return {"templates": out, "files": len(files), "errors": errors}
