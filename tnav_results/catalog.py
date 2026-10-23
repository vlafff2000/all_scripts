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


GENERIC = {"result", "results", "res", "output", "out", "restart", "run"}   # так называют папку или файлы результатов, не модель


def names_path() -> str:
    home = os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg")
    return os.path.join(home, "tnav_names.json")


def load_names() -> Dict[str, str]:
    """Имена, заданные вручную: {id модели: имя}. Ручное главнее найденного."""
    try:
        with open(names_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items() if str(v).strip()} if isinstance(data, dict) else {}


def save_name(model_id: str, name: str) -> None:
    """Задаёт имя вручную; пустое имя возвращает автоматическое."""
    names = load_names()
    if str(name or "").strip():
        names[model_id] = str(name).strip()
    else:
        names.pop(model_id, None)
    path = names_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _data_stems(folder: str) -> List[str]:
    try:
        return sorted(os.path.splitext(n)[0] for n in os.listdir(folder) if n.lower().endswith(".data"))
    except OSError:
        return []


def model_name(anchor: str) -> str:
    """Имя модели: файл .data рядом с результатами (или на 1–2 папки выше), затем префикс файлов результатов,
    затем имя ближайшей родительской папки; «result» и подобные общие слова не годятся."""
    folder = os.path.dirname(os.path.abspath(anchor))
    stem = os.path.splitext(os.path.basename(anchor))[0]
    probe = [stem.lower(), os.path.basename(folder).lower()]
    cur = folder
    for _ in range(3):
        stems = _data_stems(cur)
        pick = [x for x in stems if x.lower() in probe]
        if pick:
            return pick[0]
        if len(stems) == 1:
            return stems[0]
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        probe.append(os.path.basename(cur).lower())
        cur = nxt
    if stem.lower() not in GENERIC:
        return stem
    cur = folder
    while True:
        base = os.path.basename(cur)
        if base and base.lower() not in GENERIC:
            return base
        nxt = os.path.dirname(cur)
        if nxt == cur:
            return stem
        cur = nxt


def model_entry(anchor: str, files: Dict[str, str]) -> dict:
    """Описание одной модели. anchor — путь к одному из её файлов; по нему находятся остальные (results.find_files)."""
    name = load_names().get(anchor) or model_name(anchor)
    return {"id": anchor, "name": name, "folder": os.path.dirname(anchor), "files": sorted(files),
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
    manual = load_names()
    count: Dict[str, int] = {}
    for m in out:
        count[m["name"]] = count.get(m["name"], 0) + 1
    for m in out:                       # одинаковые имена различаем родительской папкой (ручное имя не трогаем)
        if count[m["name"]] > 1 and m["id"] not in manual:
            m["name"] = m["name"] + " (" + os.path.basename(os.path.dirname(m["folder"]) or m["folder"]) + ")"
    return out
