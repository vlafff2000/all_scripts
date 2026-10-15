"""Копирование файлов по расширению, группе расширений или фрагменту имени — из папки и её подпапок.

Нужно, чтобы вытянуть одинаковые файлы (например, все Word-отчёты) из множества подпапок в одну папку.
Условия складываются по «И»: группа (или свой список расширений) и фрагмент имени. Если не задано ни одно — программа
ничего не копирует, чтобы не скопировать весь диск по ошибке.

Файлы кладутся в одну папку без подпапок. Одинаковые имена получают суффикс _1, _2 …
Если в одной папке лежат файлы с одним именем и разными расширениями, берётся тот, чьё расширение стоит раньше в списке
(в группе — по порядку группы, в своём списке — как введено). Одинаковые по содержимому файлы копируются один раз.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from pxg_core import параметры

GROUPS: Dict[str, List[str]] = {
    "word": ["docx", "doc", "docm", "dotx", "dot", "dotm", "odt", "rtf"],
    "excel": ["xlsx", "xls", "xlsm", "xlsb", "ods", "csv"],
    "pdf": ["pdf"],
    "presentation": ["pptx", "ppt", "pptm", "odp"],
}
GROUP_TITLES = {
    "word": "Word и текстовые: .docx, .doc, .docm, .dot, .odt, .rtf",
    "excel": "Таблицы: .xlsx, .xls, .xlsm, .xlsb, .ods, .csv",
    "pdf": "PDF",
    "presentation": "Презентации: .pptx, .ppt, .pptm, .odp",
}
REPORT_NAME = "отчёт_копирования.txt"



def parse_extensions(text: str) -> List[str]:
    """«docx, .ODT;pdf» → ['docx', 'odt', 'pdf'] (без точки, в нижнем регистре, без повторов, в порядке ввода)."""
    out: List[str] = []
    for chunk in (text or "").replace(";", ",").replace(" ", ",").split(","):
        ext = chunk.strip().lstrip(".").lower()
        if ext and ext not in out:
            out.append(ext)
    return out


def wanted_extensions(group: str, extensions: str) -> Optional[List[str]]:
    """Список расширений: свой имеет приоритет над группой; None — расширение не ограничено."""
    own = parse_extensions(extensions)
    if own:
        return own
    if group:
        return list(GROUPS[group])
    return None


def priority(ext: str, order: Optional[List[str]]) -> Tuple[int, str]:
    """Меньше — важнее. Порядок расширений из списка; если список не ограничен — из общего порядка групп."""
    ordering = order or [e for g in GROUPS.values() for e in g]
    if ext in ordering:
        return (ordering.index(ext), ext)
    return (len(ordering), ext)


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def collect(source: Path, exts: Optional[List[str]], fragment: str, recursive: bool, skip_dir: Optional[Path] = None) -> List[Path]:
    """Файлы, подходящие под расширения и фрагмент имени. Папка назначения пропускается, чтобы не копировать копии."""
    needle = fragment.strip().lower()
    found: List[Path] = []
    walker = os.walk(str(source)) if recursive else [(str(source), [], os.listdir(str(source)))]
    for root, dirs, names in walker:
        root_path = Path(root)
        if skip_dir is not None and (root_path == skip_dir or skip_dir in root_path.parents):
            dirs[:] = []
            continue
        for name in names:
            path = root_path / name
            if not path.is_file():
                continue
            ext = path.suffix.lower().lstrip(".")
            if exts is not None and ext not in exts:
                continue
            if needle and needle not in name.lower():
                continue
            found.append(path)
    return sorted(found, key=lambda p: str(p).lower())


def pick_one_per_name(files: List[Path], exts: Optional[List[str]]) -> Tuple[List[Path], List[Tuple[Path, str]]]:
    """Из файлов одной папки с одинаковым именем (без расширения) оставляет самый важный; остальные — с причиной."""
    groups: Dict[Tuple[str, str], List[Path]] = defaultdict(list)
    for path in files:
        groups[(str(path.parent), path.stem.lower())].append(path)
    chosen: List[Path] = []
    skipped: List[Tuple[Path, str]] = []
    for group in groups.values():
        group.sort(key=lambda p: priority(p.suffix.lower().lstrip("."), exts))
        chosen.append(group[0])
        for other in group[1:]:
            skipped.append((other, "в папке есть %s с тем же именем, он важнее" % group[0].name))
    return sorted(chosen, key=lambda p: str(p).lower()), skipped


def _free_name(dest: Path, name: str, taken: set) -> str:
    """Имя в папке назначения: если занято, добавляется суффикс _1, _2 …"""
    stem, suffix = os.path.splitext(name)
    candidate, counter = name, 1
    while (dest / candidate).exists() or candidate in taken:
        candidate = "%s_%d%s" % (stem, counter, suffix)
        counter += 1
    return candidate


def run(source: Path, dest: Optional[Path], exts: Optional[List[str]], fragment: str = "", recursive: bool = True,
        one_per_name: bool = True, skip_duplicates: bool = True, dry_run: bool = False, report_dir: Optional[Path] = None) -> Dict:
    """Собирает список и (если не режим «только список») копирует. Возвращает сводку и путь к отчёту."""
    found = collect(source, exts, fragment, recursive, skip_dir=dest)
    skipped: List[Tuple[Path, str]] = []
    if one_per_name:
        found, same_name = pick_one_per_name(found, exts)
        skipped.extend(same_name)
    copied: List[Tuple[Path, str]] = []
    errors: List[Tuple[Path, str]] = []
    seen_hashes: Dict[str, Path] = {}
    taken: set = set()
    if dest is not None and not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
    for path in found:
        try:
            digest = file_md5(path) if skip_duplicates else ""
        except OSError as e:
            errors.append((path, str(e)))
            continue
        if digest and digest in seen_hashes:
            skipped.append((path, "одинаковое содержимое с %s" % seen_hashes[digest]))
            continue
        if digest:
            seen_hashes[digest] = path
        if dry_run or dest is None:
            copied.append((path, ""))
            continue
        name = _free_name(dest, path.name, taken)
        try:
            shutil.copy2(str(path), str(dest / name))
            taken.add(name)
            copied.append((path, name))
        except OSError as e:
            errors.append((path, str(e)))
    report = _write_report(source, dest, exts, fragment, recursive, copied, skipped, errors, dry_run, report_dir)
    return {"found": len(found), "copied": copied, "skipped": skipped, "errors": errors, "report": report}


def _write_report(source, dest, exts, fragment, recursive, copied, skipped, errors, dry_run, report_dir) -> Optional[Path]:
    target_dir = report_dir or Path.cwd()
    lines = [
        "ОТЧЁТ О КОПИРОВАНИИ ПО МАСКЕ",
        "Дата: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Исходная папка: %s" % source,
        "Папка назначения: %s" % (dest if dest is not None else "(не задана, только список)"),
        "Расширения: %s" % (", ".join("." + e for e in exts) if exts else "любые"),
        "Фрагмент имени: %s" % (fragment or "не задан"),
        "Подпапки: %s" % ("да" if recursive else "нет"),
        "Режим: %s" % ("только список, без копирования" if dry_run else "копирование"),
        "",
        "Скопировано (или подходит): %d" % len(copied),
    ]
    lines += ["  %s%s" % (p, (" -> " + n) if n else "") for p, n in copied]
    lines += ["", "Пропущено: %d" % len(skipped)]
    lines += ["  %s — %s" % (p, why) for p, why in skipped]
    lines += ["", "Ошибок: %d" % len(errors)]
    lines += ["  %s — %s" % (p, why) for p, why in errors]
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / REPORT_NAME
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    except OSError:
        return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Копирование файлов по маске из папки и подпапок")
    parser.add_argument("--source", help="папка, где искать")
    parser.add_argument("--dest", help="папка для копий (без подпапок)")
    parser.add_argument("--group", default="", choices=[""] + list(GROUPS), help="группа расширений")
    parser.add_argument("--extensions", default="", help="свои расширения через запятую, например docx, odt")
    parser.add_argument("--fragment", default="", help="часть имени файла, без учёта регистра")
    parser.add_argument("--recursive", type=параметры.yes, default=True, help="искать в подпапках: да/нет")
    parser.add_argument("--one-per-name", type=параметры.yes, default=True, help="из одинаковых имен в папке брать один файл: да/нет")
    parser.add_argument("--skip-duplicates", type=параметры.yes, default=True, help="не копировать одинаковое содержимое дважды: да/нет")
    parser.add_argument("--dry-run", type=параметры.yes, default=False, help="только показать список, ничего не копировать: да/нет")
    args = parser.parse_args(argv)

    interactive = args.source is None
    source_text = args.source if not interactive else параметры.ask("Папка, где искать файлы")
    source = Path(параметры.clean_path(source_text)) if source_text else None
    if source is None or not source.is_dir():
        print("Исходная папка не найдена: %s" % (source_text or "(не задана)"))
        return 1
    group, extensions, fragment = args.group, args.extensions, args.fragment
    if interactive:
        print("Группы: " + ", ".join("%s (%s)" % (k, GROUP_TITLES[k]) for k in GROUPS))
        group = параметры.ask("Группа расширений (пусто — не выбирать)", "")
        extensions = параметры.ask("Свои расширения через запятую (пусто — не задавать)", "")
        fragment = параметры.ask("Часть имени файла (пусто — не задавать)", "")
    if group and group not in GROUPS:
        print("Неизвестная группа: %s" % group)
        return 1
    exts = wanted_extensions(group, extensions)
    if exts is None and not fragment.strip():
        print("Задайте хотя бы одно условие: группу расширений, свои расширения или часть имени. Иначе копировать нечего.")
        return 1
    dest_text = args.dest if args.dest is not None else (параметры.ask("Папка для копий") if interactive else "")
    dest = Path(параметры.clean_path(dest_text)) if dest_text else None
    if dest is None and not args.dry_run:
        print("Укажите папку для копий или включите режим «только список».")
        return 1

    result = run(source, dest, exts, fragment, args.recursive, args.one_per_name, args.skip_duplicates, args.dry_run)
    print("Исходная папка: %s" % source)
    print("Расширения: %s; фрагмент имени: %s; подпапки: %s" % (
        ", ".join("." + e for e in exts) if exts else "любые", fragment or "не задан", "да" if args.recursive else "нет"))
    print("Подходящих файлов: %d" % result["found"])
    for path, name in result["copied"]:
        print("  %s%s" % (path, (" -> " + name) if name else ""))
    print("Пропущено: %d" % len(result["skipped"]))
    for path, why in result["skipped"]:
        print("  %s — %s" % (path, why))
    if result["errors"]:
        print("Ошибок: %d" % len(result["errors"]))
        for path, why in result["errors"]:
            print("  %s — %s" % (path, why))
    verb = "Список составлен" if args.dry_run else "Скопировано"
    print("%s: %d файлов." % (verb, len(result["copied"])))
    if result["report"]:
        print("Отчёт: %s" % result["report"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
