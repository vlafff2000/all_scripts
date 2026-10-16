"""Общий выбор двух папок для всех программ: «готовые файлы» и «данные после Базы ПХГ» (выгрузки).

Хранится в одном файле ``рабочие_папки.json`` в каталоге пользователя (``~/.pxg/``, как ``ui.json`` проводника;
каталог меняется переменной PXG_HOME). Выбор делается один раз; программы читают файл и берут нужные файлы по роли.

Только стандартная библиотека (Python 3.12+, РЕД ОС 7.3, Windows). Битый файл не падает: работаем так, будто папки не выбраны.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

FILE_NAME = "рабочие_папки.json"
SLOTS = ("ready", "exports")
LABELS = {"ready": "Готовые файлы", "exports": "Данные после Базы ПХГ"}


def settings_path() -> str:
    home = os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg")
    return os.path.join(home, FILE_NAME)


def load() -> Dict[str, str]:
    """Текущий выбор: {'ready': путь или '', 'exports': путь или ''}. Нет файла или он битый — пустые значения."""
    empty = {slot: "" for slot in SLOTS}
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    return {slot: str(data.get(slot) or "").strip() for slot in SLOTS}


def save(ready: str | None = None, exports: str | None = None) -> Dict[str, str]:
    """Меняет только переданные поля (None — оставить как есть, '' — очистить). Запись атомарная."""
    current = load()
    for slot, value in (("ready", ready), ("exports", exports)):
        if value is not None:
            current[slot] = os.path.abspath(value.strip()) if value.strip() else ""
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return current


def status() -> List[Dict[str, Any]]:
    """Для каждой папки: выбрана ли она, существует ли и какие файлы в ней лежат (имена, без чтения содержимого)."""
    out: List[Dict[str, Any]] = []
    chosen = load()
    for slot in SLOTS:
        path = chosen[slot]
        exists = bool(path) and os.path.isdir(path)
        try:
            files = sorted(
                name for name in os.listdir(path)
                if os.path.isfile(os.path.join(path, name)) and not name.startswith("~$")
            ) if exists else []
        except OSError:          # нет прав на чтение папки: показываем её как не найденную
            files, exists = [], False
        out.append({
            "slot": slot,
            "label": LABELS[slot],
            "path": path,
            "chosen": bool(path),
            "found": exists,
            "files": files,
        })
    return out
