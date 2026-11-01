"""Базовые параметры скважин из входных файлов модели tNavigator: устье, альтитуда, группа, перфорации.

Читает то же, что ``perforations`` (.data и INCLUDE), и сводит по скважинам. Каждое значение несёт источник (ключевое слово и
файл:строка), чтобы инженер видел, откуда оно, и мог заменить его файлом или вручную; сверку с файлом делает вызывающая сторона
(``compare``). Только стандартная библиотека, Python 3.8+.

Допущения (не проверены на файлах Егора): устье — первая точка WELLTRACK (X, Y в координатах модели), альтитуда стола = −Z этой точки
(Z в модели — глубина вниз от уровня моря); группа и ячейка I,J — из WELSPECS; опорная глубина — пятая колонка WELSPECS.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from . import perforations as P


def well_params(path: str, date=None) -> dict:
    """Параметры по скважинам: {wells: {имя: {...}}, notes, files}. Перфорации — на дату (``None`` — после последней записи).

    Поля скважины: group, i, j, ref_depth, x, y, altitude (None, если в модели нет WELLTRACK), intervals (PerfRow как словари
    без отметок; отметки добавляет ``perforations.add_depths`` с сеткой), sources (поле → «ключевое слово файл:строка»)."""
    res = P.read_perforations(path)
    wells: Dict[str, dict] = {}
    for w in res.wells:                    # последняя запись WELSPECS главнее
        d = wells.setdefault(w.well, {"sources": {}})
        d.update(group=w.group, i=w.i, j=w.j, ref_depth=w.ref_depth)
        d["sources"].update({k: "WELSPECS %s:%d" % (w.file, w.line) for k in ("group", "i", "j", "ref_depth")})
    for name, pts in (res.tracks or {}).items():
        d = wells.setdefault(name, {"sources": {}})
        x, y, z, _md = pts[0]
        d.update(x=x, y=y, altitude=-z)
        d["sources"].update({k: "WELLTRACK (первая точка)" for k in ("x", "y", "altitude")})
    for name in {r.well for r in P.perforations_at(res, date, only_open=False)}:
        wells.setdefault(name, {"sources": {}})
    for name, d in wells.items():
        for k in ("group", "i", "j", "ref_depth", "x", "y", "altitude"):
            d.setdefault(k, None)
        d["intervals"] = [r._asdict() for r in P.perforations_at(res, date, wells=[name])]
    return {"wells": wells, "notes": list(res.notes), "files": list(res.files)}


def compare(model: Dict[str, dict], file_values: Dict[str, float], field: str = "altitude", tol: float = 1.0) -> List[dict]:
    """Сверка значения модели с файлом по скважинам (ключ — имя скважины как в модели): строки {well, model, file, diff, ok}.
    Расхождение больше tol (м) помечается ok=False; решение — за инженером, программа ничего не меняет сама."""
    out = []
    for well, d in sorted(model.items()):
        m, f = d.get(field), file_values.get(well)
        if m is None or f is None:
            continue
        out.append({"well": well, "model": m, "file": f, "diff": m - f, "ok": abs(m - f) <= tol})
    return out


BIG_FILE = 30 * 1024 * 1024


def inventory(path: str) -> dict:
    """Опись входных файлов модели: какие файлы подключены (.data и дерево INCLUDE/IMPORT) и какие ключевые слова в них встречаются.

    Ничего не интерпретирует, только перечисляет: {files: [{path, name, parent, line, found, size}], keywords: {СЛОВО: {count, files}},
    notes}. Ключевое слово — первый токен строки, записанный заглавными (одиночный) или известный читалке; числа и «/» не считаются.
    Какие слова читаются и куда попадают, решает вызывающая сторона (каталог в Атласе)."""
    import os
    from . import perforations as P

    if not path.lower().endswith((".data", ".inc", ".include", ".sch", ".schedule", ".txt")):
        found = P.find_data_files(path)
        path = found[0] if found else ""
    files: List[dict] = []
    kws: Dict[str, dict] = {}
    notes: List[str] = []

    def walk(p: str, parent: str, line: int, seen: tuple, depth: int) -> None:
        ap = os.path.abspath(p)
        if depth > 12 or ap in seen:
            notes.append("INCLUDE зациклен или слишком вложен: %s" % p)
            return
        entry = {"path": ap, "name": os.path.basename(p), "parent": parent, "line": line, "found": True, "size": 0}
        files.append(entry)
        try:
            entry["size"] = os.path.getsize(ap)
            if entry["size"] > BIG_FILE:      # сетка и кубы на сотни МБ: только строки из одного слова, без разбора записей
                entry["big"] = True
                with open(ap, "r", encoding="utf-8", errors="replace") as f:
                    for ln, raw in enumerate(f, 1):
                        w = raw.strip()
                        if 3 <= len(w) <= 24 and P._WORD.match(w) and w.isupper():
                            d = kws.setdefault(w, {"count": 0, "files": []})
                            d["count"] += 1
                            if entry["name"] not in d["files"]:
                                d["files"].append(entry["name"])
                return
            with open(ap, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            entry["found"] = False
            notes.append("файл не открыт: %s (%s)" % (p, e))
            return
        toks = P._tokenize(text)
        base = os.path.dirname(ap)
        for n, t in enumerate(toks):
            key = t.text.upper()
            if not (P._WORD.match(t.text) and t.first and (key in P.KNOWN or (t.alone and t.text.isupper() and len(key) >= 3))):
                continue
            d = kws.setdefault(key, {"count": 0, "files": []})
            d["count"] += 1
            if entry["name"] not in d["files"]:
                d["files"].append(entry["name"])
            if key in ("INCLUDE", "IMPORT") and n + 1 < len(toks):
                name = P._unquote(toks[n + 1].text)
                cand = [os.path.join(base, name), os.path.join(os.path.dirname(files[0]["path"]), name)]
                real = next((c for c in cand if os.path.isfile(c)), None)
                if real:
                    walk(real, entry["name"], t.line, seen + (ap,), depth + 1)
                else:
                    files.append({"path": os.path.join(base, name), "name": name, "parent": entry["name"], "line": t.line,
                                  "found": False, "size": 0})
                    notes.append("%s: INCLUDE-файл не найден: %s" % (entry["name"], name))

    if path and os.path.isfile(path):
        walk(path, "", 0, (), 0)
    else:
        notes.append("рядом с моделью нет файла .data")
    return {"files": files, "keywords": kws, "notes": notes}
