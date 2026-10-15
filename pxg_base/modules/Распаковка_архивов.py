"""Распаковка архивов: каждый архив — в папку с его именем рядом с архивом.

Форматы: ZIP, TAR (и TAR.GZ, TAR.BZ2, TAR.XZ, TGZ, TBZ2, TXZ), RAR (нужен пакет rarfile), 7Z (нужен пакет py7zr).
Структура архива сохраняется. Архив можно удалить после успешной распаковки. Ошибочная распаковка не оставляет пустую папку.
"""
from __future__ import annotations

import argparse
import os
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from pxg_core import параметры

# Длинные окончания первыми: «.tar.gz» раньше «.gz»
ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".tar", ".zip", ".rar", ".7z")


def archive_suffix(name: str) -> Optional[str]:
    lower = name.lower()
    for suffix in ARCHIVE_SUFFIXES:
        if lower.endswith(suffix):
            return suffix
    return None


def folder_name(name: str) -> str:
    """Имя папки для распаковки: имя архива без всех расширений архива («отчёт.tar.gz» → «отчёт»)."""
    suffix = archive_suffix(name)
    return name[: -len(suffix)] if suffix else name


def find_archives(folder: Path, fragment: str = "", recursive: bool = False) -> List[Path]:
    needle = fragment.strip().lower()
    walker = os.walk(str(folder)) if recursive else [(str(folder), [], os.listdir(str(folder)))]
    found: List[Path] = []
    for root, _dirs, names in walker:
        for name in names:
            path = Path(root) / name
            if not path.is_file() or archive_suffix(name) is None:
                continue
            if needle and needle not in name.lower():
                continue
            found.append(path)
    return sorted(found, key=lambda p: str(p).lower())


def extract(archive: Path, target: Path) -> None:
    """Распаковывает архив в target. Бросает исключение с понятным текстом, если формат не поддерживается."""
    suffix = archive_suffix(archive.name)
    if suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
    elif suffix in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"):
        with tarfile.open(archive, "r:*") as tf:
            if hasattr(tarfile, "data_filter"):  # защита от путей вне папки и опасных прав (Python 3.12+)
                tf.extractall(target, filter="data")
            else:
                tf.extractall(target)
    elif suffix == ".rar":
        try:
            import rarfile
        except ImportError:
            raise RuntimeError("для RAR нужен пакет rarfile: pip install rarfile")
        with rarfile.RarFile(str(archive)) as rf:
            rf.extractall(str(target))
    elif suffix == ".7z":
        try:
            import py7zr
        except ImportError:
            raise RuntimeError("для 7Z нужен пакет py7zr: pip install py7zr")
        with py7zr.SevenZipFile(str(archive), "r") as sz:
            sz.extractall(str(target))
    else:
        raise RuntimeError("неподдерживаемый формат архива: %s" % archive.name)


def unpack(archive: Path, delete: bool = False) -> Tuple[bool, str, Optional[Path]]:
    """Распаковка одного архива в папку рядом с ним. Возвращает (успех, сообщение, папка)."""
    target = archive.parent / folder_name(archive.name)
    created = not target.exists()
    try:
        target.mkdir(exist_ok=True)
        extract(archive, target)
    except Exception as e:  # любая ошибка архива не должна останавливать остальные
        if created and target.exists() and not any(target.iterdir()):
            target.rmdir()
        return False, "ошибка: %s" % e, None
    if delete:
        try:
            archive.unlink()
        except OSError as e:
            return True, "распакован в «%s», но архив не удалось удалить: %s" % (target.name, e), target
        return True, "распакован в «%s», архив удалён" % target.name, target
    return True, "распакован в «%s»" % target.name, target


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Распаковка архивов в папки")
    parser.add_argument("--folder", help="папка с архивами")
    parser.add_argument("--fragment", default="", help="часть имени архива, без учёта регистра")
    parser.add_argument("--recursive", type=параметры.yes, default=False, help="искать в подпапках: да/нет")
    parser.add_argument("--delete", type=параметры.yes, default=False, help="удалить архив после распаковки: да/нет")
    args = parser.parse_args(argv)

    folder_text = args.folder if args.folder is not None else параметры.ask("Папка с архивами")
    folder = Path(параметры.clean_path(folder_text)) if folder_text else None
    if folder is None or not folder.is_dir():
        print("Папка не найдена: %s" % (folder_text or "(не задана)"))
        return 1
    if args.folder is None:
        args.fragment = параметры.ask("Часть имени архива (пусто — все)", "")
        args.recursive = параметры.yes(параметры.ask("Искать в подпапках (да/нет)", "нет"))
        args.delete = параметры.yes(параметры.ask("Удалить архивы после распаковки (да/нет)", "нет"))

    archives = find_archives(folder, args.fragment, args.recursive)
    if not archives:
        print("Архивы не найдены.")
        return 0
    print("Найдено архивов: %d" % len(archives))
    if args.delete:
        print("ВНИМАНИЕ: архивы будут удалены после успешной распаковки.")
    ok = 0
    for i, archive in enumerate(archives, 1):
        success, message, _ = unpack(archive, args.delete)
        ok += success
        print("%d/%d %s: %s" % (i, len(archives), archive, message))
    print("Итого: распаковано %d, ошибок %d" % (ok, len(archives) - ok))
    return 0 if ok == len(archives) else 2


if __name__ == "__main__":
    sys.exit(main())
