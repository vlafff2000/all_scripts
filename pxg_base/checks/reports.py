"""Проверки модулей «Отчёты и файлы»: что найдётся до запуска, без копирования и распаковки."""
from __future__ import annotations

import contextlib
import importlib
import io
import os
from pathlib import Path
from typing import Dict

from pxg_core.qc import Report, check_path
from pxg_core.параметры import clean_path


def _module(name: str):
    return importlib.import_module("pxg_base.modules." + name)


def check_copy_by_mask(v: Dict[str, str]) -> Report:
    rep = Report("Копирование файлов по маске")
    cm = _module("Копирование_файлов_по_маске")
    source = clean_path(v.get("source", ""))
    if not check_path(rep, source, "Папка, где искать файлы", kind="folder"):
        return rep
    group = v.get("group", "")
    if group and group not in cm.GROUPS:
        rep.error("GROUP", "Неизвестная группа расширений: %s" % group)
        return rep
    exts = cm.wanted_extensions(group, v.get("extensions", ""))
    fragment = v.get("fragment", "")
    if exts is None and not fragment.strip():
        rep.error("NOCOND", "Задайте группу расширений, свои расширения или часть имени: иначе копировать нечего")
        return rep
    found = cm.collect(Path(source), exts, fragment, v.get("recursive", "1") in ("1", "true", "y"))
    if not found:
        rep.warn("EMPTY", "Подходящих файлов не найдено")
    else:
        rep.note("SUMMARY", "Подходящих файлов: %d" % len(found))
    dest = clean_path(v.get("dest", ""))
    if dest and not os.path.isdir(dest):
        rep.error("DEST", "Папка для копий не найдена: %s" % dest)
    return rep


def check_unpack(v: Dict[str, str]) -> Report:
    rep = Report("Распаковка архивов")
    um = _module("Распаковка_архивов")
    folder = clean_path(v.get("folder", ""))
    if not check_path(rep, folder, "Папка с архивами", kind="folder"):
        return rep
    recursive = v.get("recursive", "") in ("1", "true", "y")
    archives = um.find_archives(Path(folder), v.get("fragment", ""), recursive)
    if not archives:
        rep.warn("EMPTY", "Архивов не найдено")
        return rep
    rep.note("SUMMARY", "Архивов: %d" % len(archives))
    for a in archives:
        suffix = um.archive_suffix(a.name)
        if suffix == ".rar":
            try:
                import rarfile  # noqa: F401
            except ImportError:
                rep.warn("RAR", "Для RAR нужен пакет rarfile: pip install rarfile", file=str(a))
        if suffix == ".7z":
            try:
                import py7zr  # noqa: F401
            except ImportError:
                rep.warn("7Z", "Для 7Z нужен пакет py7zr: pip install py7zr", file=str(a))
        target = a.parent / um.folder_name(a.name)
        if target.exists() and any(target.iterdir()):
            rep.warn("EXISTS", "Папка «%s» уже не пустая: файлы могут смешаться" % target.name, file=str(a))
    return rep


def check_pressure_copy(v: Dict[str, str]) -> Report:
    rep = Report("Копирование замеров давлений по шаблонам")
    pm = _module("Копирование_замеров_давлений_по_шаблонам")
    folder = clean_path(v.get("folder", ""))
    if not check_path(rep, folder, "Корневая папка", kind="folder"):
        return rep
    with contextlib.redirect_stdout(io.StringIO()):
        files = pm.find_specific_excel_files(folder)
    if not files:
        rep.warn("EMPTY", "Нужных файлов (набл, замер, Результаты) не найдено")
        return rep
    rep.note("SUMMARY", "Подходящих файлов: %d" % len(files))
    for path in files:
        if pm.get_template_by_year(pm.extract_year_from_path(path)) is None:
            rep.warn("YEAR", "Год не определён или вне шаблонов 2016–2026: файл пойдёт в «год не определён»", file=path)
    return rep
