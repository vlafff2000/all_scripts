"""Сравнение двух папок по именам файлов и сборка различающихся файлов в третью папку.

Режимы: «только в A», «только в B», «различия в обеих» (файл есть в одной папке и нет в другой).
Сравнение — по имени файла (с расширением), по умолчанию без учёта регистра; относительный путь не учитывается.
Маски (`*.pdf`, `отчет*`, `~$*`) — списки включения и исключения: через запятую, точку с запятой или с новой строки;
совпадение — по имени файла, без учёта регистра (если не включён учёт регистра). Пустой список включения — любые файлы.

Копируются КОПИИ: оригиналы не трогаются, существующие файлы в папке назначения не перезаписываются
(при занятом имени добавляется имя папки-источника, затем счётчик _1, _2 …).
Режим «только список» (по умолчанию в форме) ничего не копирует: показывает, что будет скопировано.
Список можно поправить вручную: пути или имена в поле «Не копировать» исключаются из копирования.
Отчёт «сравнение_папок.xlsx» — листы «Копируются/Скопированы», «Пропущены», «Ошибки».
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from pxg_core import параметры

MODES = {"a": "Только в папке A", "b": "Только в папке B", "both": "Различия в обеих (есть в одной, нет в другой)"}
REPORT_NAME = "сравнение_папок.xlsx"


def parse_masks(text: str) -> List[str]:
    """Список масок из текста: разделители — запятая, точка с запятой, новая строка. «.pdf» понимается как «*.pdf»."""
    out: List[str] = []
    for chunk in re.split(r"[,;\n\r]+", text or ""):
        mask = chunk.strip().strip('"')
        if not mask:
            continue
        if mask.startswith(".") and not any(c in mask[1:] for c in "*?[."):
            mask = "*" + mask
        if mask not in out:
            out.append(mask)
    return out


def name_matches(name: str, masks: Sequence[str], case_sensitive: bool = False) -> bool:
    if case_sensitive:
        return any(fnmatch.fnmatchcase(name, m) for m in masks)
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, m.lower()) for m in masks)


def name_key(name: str, case_sensitive: bool = False) -> str:
    return name if case_sensitive else name.lower()


def scan(folder: Path, recursive: bool, include: Sequence[str], exclude: Sequence[str],
         case_sensitive: bool = False, skip_dirs: Sequence[Path] = ()) -> Dict[str, List[Path]]:
    """Файлы папки: ключ имени → пути (если одно имя встречается в нескольких подпапках, пути все). Папки skip_dirs пропускаются."""
    skip = [p.resolve() for p in skip_dirs]
    found: Dict[str, List[Path]] = {}
    for root, dirs, names in os.walk(str(folder)):
        root_path = Path(root)
        real = root_path.resolve()
        if any(real == s or s in real.parents for s in skip):
            dirs[:] = []
            continue
        if not recursive:
            dirs[:] = []
        for name in names:
            path = root_path / name
            if not path.is_file():
                continue
            if include and not name_matches(name, include, case_sensitive):
                continue
            if exclude and name_matches(name, exclude, case_sensitive):
                continue
            found.setdefault(name_key(name, case_sensitive), []).append(path)
    for paths in found.values():
        paths.sort(key=lambda p: str(p).lower())
    return found


def diff(a: Dict[str, List[Path]], b: Dict[str, List[Path]], mode: str) -> List[Tuple[str, Path]]:
    """Различия: список (сторона 'A'|'B', путь), по ключам имён, в порядке имени."""
    out: List[Tuple[str, Path]] = []
    if mode in ("a", "both"):
        out += [("A", p) for k in sorted(a) if k not in b for p in a[k]]
    if mode in ("b", "both"):
        out += [("B", p) for k in sorted(b) if k not in a for p in b[k]]
    return sorted(out, key=lambda t: (t[1].name.lower(), t[0], str(t[1]).lower()))


def apply_exclusions(items: List[Tuple[str, Path]], skip_lines: Sequence[str],
                     case_sensitive: bool = False) -> Tuple[List[Tuple[str, Path]], List[Tuple[str, Path, str]]]:
    """Ручное исключение: строка — полный путь файла или имя файла. Возвращает (оставшиеся, исключённые с причиной)."""
    full = {os.path.normcase(os.path.normpath(s)) for s in skip_lines if os.path.sep in s or "/" in s}
    names = {name_key(s, case_sensitive) for s in skip_lines if os.path.sep not in s and "/" not in s}
    kept: List[Tuple[str, Path]] = []
    dropped: List[Tuple[str, Path, str]] = []
    for side, path in items:
        if os.path.normcase(os.path.normpath(str(path))) in full or name_key(path.name, case_sensitive) in names:
            dropped.append((side, path, "исключён вручную"))
        else:
            kept.append((side, path))
    return kept, dropped


def free_name(dest: Path, path: Path, side: str, taken: set) -> str:
    """Имя в папке назначения без перезаписи: как есть → «<папка-источник>_<имя>» → «<сторона>_<папка>_<имя>» → счётчик."""
    def busy(n: str) -> bool:
        return n.lower() in taken or (dest / n).exists()

    name = path.name
    if not busy(name):
        return name
    prefix = path.parent.name or side
    candidates = ["%s_%s" % (prefix, name), "%s_%s_%s" % (side, prefix, name)]
    for c in candidates:
        if not busy(c):
            return c
    stem, suffix = os.path.splitext(candidates[-1])
    n = 1
    while busy("%s_%d%s" % (stem, n, suffix)):
        n += 1
    return "%s_%d%s" % (stem, n, suffix)


def run(a: Path, b: Path, dest: Optional[Path], mode: str = "both", recursive: bool = True,
        include: Sequence[str] = (), exclude: Sequence[str] = (), case_sensitive: bool = False,
        skip_lines: Sequence[str] = (), dry_run: bool = True) -> Dict:
    skip_dirs = [dest] if dest is not None else []
    map_a = scan(a, recursive, include, exclude, case_sensitive, skip_dirs)
    map_b = scan(b, recursive, include, exclude, case_sensitive, skip_dirs)
    items = diff(map_a, map_b, mode)
    items, skipped = apply_exclusions(items, skip_lines, case_sensitive)
    copied: List[Tuple[str, Path, str]] = []   # (сторона, источник, имя в папке назначения; пусто в режиме списка)
    errors: List[Tuple[str, Path, str]] = []
    taken: set = set()
    if dest is not None and not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
    for side, path in items:
        if dest is None:
            copied.append((side, path, ""))
            continue
        name = free_name(dest, path, side, taken)
        taken.add(name.lower())
        if dry_run:
            copied.append((side, path, name))
            continue
        try:
            shutil.copy2(str(path), str(dest / name))
            copied.append((side, path, name))
        except OSError as e:
            errors.append((side, path, str(e)))
    return {"total_a": sum(len(v) for v in map_a.values()), "total_b": sum(len(v) for v in map_b.values()),
            "copied": copied, "skipped": skipped, "errors": errors}


def write_report(result: Dict, a: Path, b: Path, dest: Optional[Path], mode: str, dry_run: bool,
                 report_dir: Optional[Path] = None) -> Optional[Path]:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "К копированию" if dry_run else "Скопированы"
    ws.append(["Папка", "Файл", "Откуда", "Имя в папке назначения"])
    for side, path, name in result["copied"]:
        ws.append([side, path.name, str(path), name])
    ws2 = wb.create_sheet("Пропущены")
    ws2.append(["Папка", "Файл", "Откуда", "Причина"])
    for side, path, why in result["skipped"]:
        ws2.append([side, path.name, str(path), why])
    ws3 = wb.create_sheet("Ошибки")
    ws3.append(["Папка", "Файл", "Откуда", "Ошибка"])
    for side, path, why in result["errors"]:
        ws3.append([side, path.name, str(path), why])
    ws4 = wb.create_sheet("Параметры")
    for row in (("Папка A", str(a)), ("Папка B", str(b)), ("Папка назначения", str(dest) if dest else "не задана"),
                ("Режим различий", MODES.get(mode, mode)), ("Только список", "да" if dry_run else "нет"),
                ("Файлов в A (после масок)", result["total_a"]), ("Файлов в B (после масок)", result["total_b"])):
        ws4.append(list(row))
    for sheet in wb.worksheets:
        for col, width in zip("ABCD", (10, 40, 70, 45)):
            sheet.column_dimensions[col].width = width
    target = (report_dir or Path.cwd())
    try:
        target.mkdir(parents=True, exist_ok=True)
        path = target / REPORT_NAME
        wb.save(str(path))
        return path
    except OSError:
        return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = параметры.parser(
        "Сравнение двух папок по именам файлов и копирование различающихся файлов в третью папку",
        folder_a="папка A", folder_b="папка B", dest="папка для копий", mode="a | b | both",
        include="маски включения", exclude="маски исключения", skip="не копировать: пути или имена, по одному в строке",
        recursive="искать в подпапках: да/нет", case_sensitive="учитывать регистр: да/нет", dry_run="только список: да/нет")
    args = parser.parse_args(argv)
    interactive = args.folder_a is None
    folder_a = параметры.clean_path(args.folder_a if not interactive else параметры.ask("Папка A"))
    folder_b = параметры.clean_path(args.folder_b if not interactive else параметры.ask("Папка B"))
    for label, f in (("A", folder_a), ("B", folder_b)):
        if not f or not os.path.isdir(f):
            print("Папка %s не найдена: %s" % (label, f or "(не задана)"))
            return 1
    mode = (args.mode or ("" if not interactive else параметры.ask("Режим: a — только в A, b — только в B, both — различия в обеих", "both"))).strip() or "both"
    if mode not in MODES:
        print("Неизвестный режим: %s (нужно a, b или both)" % mode)
        return 1
    include = parse_masks(args.include or (параметры.ask("Маски включения (пусто — любые файлы)", "") if interactive else ""))
    exclude = parse_masks(args.exclude or (параметры.ask("Маски исключения", "") if interactive else ""))
    recursive = параметры.yes(args.recursive) if args.recursive is not None else True
    case_sensitive = параметры.yes(args.case_sensitive) if args.case_sensitive is not None else False
    dry_run = параметры.yes(args.dry_run) if args.dry_run is not None else True
    skip_lines = [параметры.clean_path(x) for x in (args.skip or "").splitlines() if x.strip()]
    dest_text = параметры.clean_path(args.dest if args.dest is not None else (параметры.ask("Папка для копий") if interactive else ""))
    dest = Path(dest_text) if dest_text else None
    if dest is None and not dry_run:
        print("Укажите папку для копий или включите режим «только список».")
        return 1
    if dest is not None and dest.resolve() in (Path(folder_a).resolve(), Path(folder_b).resolve()):
        print("Папка для копий не может совпадать с папкой A или B.")
        return 1

    result = run(Path(folder_a), Path(folder_b), dest, mode, recursive, include, exclude, case_sensitive, skip_lines, dry_run)
    print("Папка A: %s (файлов: %d)" % (folder_a, result["total_a"]))
    print("Папка B: %s (файлов: %d)" % (folder_b, result["total_b"]))
    print("Режим: %s; подпапки: %s; регистр: %s" % (MODES[mode], "да" if recursive else "нет", "учитывается" if case_sensitive else "не учитывается"))
    print("Маски включения: %s; исключения: %s" % (", ".join(include) or "любые", ", ".join(exclude) or "нет"))
    print("%s: %d" % ("К копированию" if dry_run else "Скопировано", len(result["copied"])))
    for side, path, name in result["copied"]:
        print("  [%s] %s%s" % (side, path, (" -> " + name) if name and name != path.name else ""))
    if result["skipped"]:
        print("Исключено вручную: %d" % len(result["skipped"]))
        for side, path, why in result["skipped"]:
            print("  [%s] %s — %s" % (side, path, why))
    if result["errors"]:
        print("Ошибок: %d" % len(result["errors"]))
        for side, path, why in result["errors"]:
            print("  [%s] %s — %s" % (side, path, why))
    report = write_report(result, Path(folder_a), Path(folder_b), dest, mode, dry_run)
    if dry_run:
        print("Только список: ничего не скопировано. Проверьте список (лишнее впишите в «Не копировать») и запустите без режима «только список».")
    if report:
        print("Отчёт: %s" % report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
