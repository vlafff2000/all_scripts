"""Легенда пачек «цвет → пачка» по листам: запоминание выбора инженера (этап А10).

Выбор хранится в ``gis_legend.json`` каталога пользователя (``~/.pxg/``, меняется PXG_HOME) отдельно для каждой книги
(по полному пути) и для каждого листа. Запомненное подставляется при следующем запуске как «вручную»; цвет, которого в
запомненном нет (на листе появилась новая заливка), остаётся подсказкой и ждёт подтверждения. Нераспознанный цвет без
подтверждения не даёт пачки, и его строки не попадают в БД для Атласа (они остаются в Excel и в «Проверке»).
"""
from __future__ import annotations

import json
import os
from typing import Dict, List

from . import gis

FILE_NAME = "gis_legend.json"


def store_path() -> str:
    home = os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg")
    return os.path.join(home, FILE_NAME)


def _read_store() -> dict:
    try:
        with open(store_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _key(book: str) -> str:
    return os.path.abspath(os.path.expanduser(book))


def load_saved(book: str) -> Dict[str, Dict[str, str]]:
    """{лист: {цвет: пачка}} для книги; пусто, если ничего не запомнено или файл битый."""
    entry = _read_store().get(_key(book))
    legends = entry.get("legends") if isinstance(entry, dict) else None
    if not isinstance(legends, dict):
        return {}
    return {str(s): {str(c): str(p) for c, p in m.items()} for s, m in legends.items() if isinstance(m, dict)}


def load_file(path: str) -> Dict[str, Dict[str, str]]:
    """Легенда из отдельного JSON (параметр запуска); пусто, если файла нет."""
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(book: str, choices: List[dict]) -> int:
    """Запоминает подтверждённые строки таблицы: [{sheet, color, pack}]. Пачка должна быть из списка или пустая (убрать)."""
    store = _read_store()
    entry = store.setdefault(_key(book), {})
    legends = entry.setdefault("legends", {})
    n = 0
    for c in choices:
        sheet, color, pack = str(c["sheet"]), str(c["color"]), str(c.get("pack") or "")
        if pack and pack not in gis.PACKS:
            raise ValueError("Неизвестная пачка: %s" % pack)
        if pack:
            legends.setdefault(sheet, {})[color] = pack
        else:
            legends.get(sheet, {}).pop(color, None)
        n += 1
    path = store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return n


def table(results: Dict[str, gis.SheetResult], saved: Dict[str, Dict[str, str]]) -> List[dict]:
    """Таблица для формы: лист — цвет — пачка — сколько строк; confirmed = выбор уже запомнен."""
    out = []
    for res in results.values():
        for e in res.legend:
            out.append({"sheet": e.sheet, "well": res.well, "color": e.color, "pack": e.pack, "source": e.source,
                        "status": e.status, "reason": e.reason, "rows": e.rows, "labels": e.labels,
                        "confirmed": e.color in saved.get(e.sheet, {}), "hints": res.hints})
    return out
