"""Общий выбор проекта для всех программ: одна папка проекта, внутри две подпапки.

    <папка проекта>/готовые/    — готовые файлы (не пересобираются)
    <папка проекта>/выгрузки/   — данные после Базы ПХГ (сюда пишет База ПХГ)

Выбор хранится в одном файле ``рабочие_папки.json`` в каталоге пользователя (``~/.pxg/``, как ``ui.json`` проводника;
каталог меняется переменной PXG_HOME). Программы читают его и берут нужные файлы по роли.

Только стандартная библиотека (Python 3.12+, РЕД ОС 7.3, Windows). Битый файл не падает: работаем так, будто проект не выбран.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List

FILE_NAME = "рабочие_папки.json"
SUBFOLDERS = {"ready": "готовые", "exports": "выгрузки"}
LABELS = {"ready": "Готовые файлы", "exports": "Данные после Базы ПХГ"}


def settings_path() -> str:
    home = os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg")
    return os.path.join(home, FILE_NAME)


def load() -> str:
    """Путь папки проекта или '' (нет файла, битый файл или поле пустое)."""
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    value = data.get("project") if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) else ""


def save(project: str | None) -> str:
    """Записывает папку проекта (None — не менять, '' — сбросить). Возвращает сохранённый путь или ''."""
    current = load()
    if project is not None:
        current = os.path.abspath(os.path.expanduser(project.strip())) if project.strip() else ""
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"project": current}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return current


def folder(slot: str) -> str:
    """Путь подпапки ('ready' или 'exports') внутри выбранного проекта; '' если проект не выбран."""
    project = load()
    return os.path.join(project, SUBFOLDERS[slot]) if project else ""


def add_ready(paths: List[str]) -> List[Dict[str, str]]:
    """Копирует файлы с любых мест диска в подпапку «готовые» выбранного проекта.

    Готовые файлы не пересобираются, поэтому файл с таким же именем не перезаписывается: он пропускается с пометкой.
    Возвращает по каждому пути: {'source', 'name', 'status': 'copied' | 'exists' | 'missing' | 'error', 'message'}.
    """
    target = folder("ready")
    if not target:
        raise ValueError("Сначала выберите папку проекта.")
    os.makedirs(target, exist_ok=True)
    out: List[Dict[str, str]] = []
    for raw in paths:
        source = os.path.abspath(os.path.expanduser(str(raw).strip()))
        name = os.path.basename(source)
        if not os.path.isfile(source):
            out.append({"source": source, "name": name, "status": "missing", "message": "Файл не найден."})
            continue
        dest = os.path.join(target, name)
        if os.path.exists(dest):
            out.append({"source": source, "name": name, "status": "exists",
                        "message": "Такой файл уже есть в «готовых»: не перезаписан."})
            continue
        try:
            shutil.copy2(source, dest)
        except OSError as e:
            out.append({"source": source, "name": name, "status": "error", "message": f"Не скопирован: {e}"})
            continue
        out.append({"source": source, "name": name, "status": "copied", "message": "Скопирован."})
    return out


def status() -> List[Dict[str, Any]]:
    """По каждой подпапке: выбран ли проект, существует ли подпапка и какие файлы в ней (имена, без чтения содержимого)."""
    out: List[Dict[str, Any]] = []
    project = load()
    for slot, name in SUBFOLDERS.items():
        path = os.path.join(project, name) if project else ""
        exists = bool(path) and os.path.isdir(path)
        try:
            files = sorted(
                f for f in os.listdir(path)
                if os.path.isfile(os.path.join(path, f)) and not f.startswith("~$")
            ) if exists else []
        except OSError:          # нет прав на чтение папки: показываем её как не найденную
            files, exists = [], False
        out.append({
            "slot": slot,
            "label": LABELS[slot],
            "path": path,
            "chosen": bool(project),
            "found": exists,
            "files": files,
        })
    return out
