"""Последнее сравнение ГВК «факт ГИС и модель» из ГДМ для «Карт»: общий файл пользователя рядом со списком папок моделей.

ГДМ пишет файл после каждого сравнения, «Карты» его читают и ничего не меняют. Исключённые инженером пары остаются в файле
с пометкой `excluded`. Только стандартная библиотека, Python 3.8+.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import List, Optional

from .catalog import folders_path

KEYS = ("well", "group", "date", "season", "slice", "pack", "fact", "model", "delta", "status", "excluded")


def share_path() -> str:
    return os.path.join(os.path.dirname(folders_path()), "gwc_compare.json")


def save(model: str, thr: float, rows: List[dict], wells_all: bool) -> None:
    """Пишет строки сравнения; wells_all=False — сравнение по части скважин (в «Картах» это видно в пояснении)."""
    path = share_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"model": model, "thr": thr, "saved": dt.datetime.now().isoformat(timespec="seconds"), "wells_all": bool(wells_all),
            "rows": [{k: r.get(k) for k in KEYS} for r in rows]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def load() -> Optional[dict]:
    try:
        with open(share_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("rows"), list) else None
