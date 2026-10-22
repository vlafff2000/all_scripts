"""Каталог моделей: обход папок и группировка файлов расчёта tNavigator по имени модели.

Модель — файлы с одним именем в одной папке (MODEL.SMSPEC, MODEL.UNSMRY, MODEL.EGRID ...). Один и тот же код нужен
ГДМ и «Картам», поэтому модуль не зависит от приложения. Только стандартная библиотека, Python 3.8+.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Sequence

EXTS = ("EGRID", "INIT", "SMSPEC", "UNSMRY", "UNRST", "RSSPEC")
SUMMARY = ("SMSPEC", "UNSMRY")                 # нужны для давлений и дебитов
INDICATORS = ("EGRID", "INIT", "UNRST")        # нужны для газонасыщенного объёма и ГВК (SGAS в UNRST)


def folders_path() -> str:
    """Список папок с результатами общий для всех программ пользователя (как настройки проводника)."""
    home = os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg")
    return os.path.join(home, "tnav_folders.json")


def load_folders() -> List[str]:
    try:
        with open(folders_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


def save_folders(folders: Sequence[str]) -> None:
    """Пишет список папок. Нет прав на запись — OSError, его показывает API."""
    path = folders_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(list(folders), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def model_entry(anchor: str, files: Dict[str, str]) -> dict:
    """Описание одной модели. anchor — путь к одному из её файлов; по нему находятся остальные (results.find_files)."""
    stem = os.path.splitext(os.path.basename(anchor))[0]
    return {"id": anchor, "name": stem, "folder": os.path.dirname(anchor), "files": sorted(files),
            "summary": all(k in files for k in SUMMARY), "indicators": all(k in files for k in INDICATORS),
            "missing": [k for k in ("EGRID", "INIT", "SMSPEC", "UNSMRY", "UNRST") if k not in files]}


def scan(folders: Sequence[str]) -> List[dict]:
    """Все модели во всех подпапках указанных папок. Порядок — по папке и имени; одна модель не повторяется.

    Папки, которых нет на диске, пропускаются: список остаётся, пользователь видит это по пустому результату.
    """
    groups: Dict[tuple, Dict[str, str]] = {}
    for root in folders:
        root = str(root or "").strip().strip('"')
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for n in sorted(filenames):
                stem, ext = os.path.splitext(n)
                kind = ext[1:].upper()
                if kind not in EXTS:
                    continue
                key = (os.path.normcase(os.path.abspath(dirpath)), stem.lower())
                groups.setdefault(key, {})[kind] = os.path.join(dirpath, n)
    out = []
    for key in sorted(groups):
        files = groups[key]
        anchor = files.get("SMSPEC") or files.get("EGRID") or next(iter(files.values()))
        out.append(model_entry(anchor, files))
    return out
