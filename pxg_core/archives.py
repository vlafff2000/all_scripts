"""Распаковка архивов (ZIP, TAR*, RAR, 7Z) и поиск файлов внутри них.

RAR читает пакет `rarfile`, но сам он только оболочка: для сжатых RAR нужна внешняя утилита (unrar, unar, bsdtar или 7z). На
компьютерах без неё (РЕД ОС 7.3) RAR без сжатия («store») всё равно читается самим пакетом, остальное даёт понятное сообщение
`ArchiveError` с тем, что установить; программа никогда не молчит про нечитаемый архив.
"""
from __future__ import annotations

import os
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

# Длинные окончания первыми: «.tar.gz» раньше «.gz»
ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".tar", ".zip", ".rar", ".7z")


class ArchiveError(RuntimeError):
    """Архив не распакован (текст причины — для пользователя)."""


def archive_suffix(name: str) -> Optional[str]:
    lower = name.lower()
    for suffix in ARCHIVE_SUFFIXES:
        if lower.endswith(suffix):
            return suffix
    return None


def rar_support() -> Tuple[bool, str]:
    """(можно ли читать сжатые RAR, пояснение). Пакет rarfile + внешняя утилита; без утилиты читаются только RAR без сжатия."""
    try:
        import rarfile
    except ImportError:
        return False, "не установлен пакет rarfile (pip install rarfile)"
    try:
        rarfile.tool_setup()
    except Exception as e:      # RarCannotExec и т. п. — утилиты нет
        return False, ("пакет rarfile есть, но нет программы для распаковки RAR (unrar, unar, bsdtar или 7z): %s. "
                       "Установите одну из них (РЕД ОС: unrar из репозитория) либо распакуйте архив вручную; "
                       "RAR без сжатия читается и без неё" % str(e).splitlines()[0])
    return True, "rarfile + " + str(getattr(rarfile, "UNRAR_TOOL", "") or "внешняя утилита")


def extract(archive: Path, target: Path) -> None:
    """Распаковывает архив в target. Бросает ArchiveError с понятным текстом, если формат или утилита недоступны."""
    suffix = archive_suffix(archive.name)
    if suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            _safe_zip(zf, target)
    elif suffix in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"):
        with tarfile.open(archive, "r:*") as tf:
            if hasattr(tarfile, "data_filter"):      # защита от путей вне папки и опасных прав (Python 3.12+)
                tf.extractall(target, filter="data")
            else:
                tf.extractall(target)
    elif suffix == ".rar":
        try:
            import rarfile
        except ImportError:
            raise ArchiveError("для RAR нужен пакет rarfile: pip install rarfile")
        try:
            with rarfile.RarFile(str(archive)) as rf:
                for info in rf.infolist():           # пути вне папки не пускаем
                    dest = (target / info.filename).resolve()
                    if target.resolve() not in dest.parents and dest != target.resolve():
                        raise ArchiveError("в архиве путь вне папки распаковки: %s" % info.filename)
                rf.extractall(str(target))
        except rarfile.RarCannotExec:
            raise ArchiveError(rar_support()[1])
        except rarfile.Error as e:
            raise ArchiveError("RAR не распакован: %s" % e)
    elif suffix == ".7z":
        try:
            import py7zr
        except ImportError:
            raise ArchiveError("для 7Z нужен пакет py7zr: pip install py7zr")
        with py7zr.SevenZipFile(str(archive), "r") as sz:
            sz.extractall(str(target))
    else:
        raise ArchiveError("неподдерживаемый формат архива: %s" % archive.name)


def _safe_zip(zf: zipfile.ZipFile, target: Path) -> None:
    root = target.resolve()
    for name in zf.namelist():
        dest = (target / name).resolve()
        if dest != root and root not in dest.parents:
            raise ArchiveError("в архиве путь вне папки распаковки: %s" % name)
    zf.extractall(target)


def expand(paths: List[str], suffixes: Tuple[str, ...] = (".doc", ".docx"), depth: int = 3) -> Tuple[List[str], List[str], Optional[tempfile.TemporaryDirectory]]:
    """Файлы, папки и архивы → (список файлов с нужными расширениями, сообщения, временная папка).

    Архивы (в том числе вложенные, до `depth` уровней) распаковываются во временную папку; вызывающий закрывает её
    (`tmp.cleanup()`), когда файлы уже прочитаны. Нечитаемый архив не останавливает остальные: причина — в сообщениях.
    """
    tmp = tempfile.TemporaryDirectory(prefix="pxg_arch_")
    notes: List[str] = []
    found: List[str] = []
    counter = [0]

    def visit(path: str, level: int) -> None:
        if os.path.isdir(path):
            for root, _d, files in os.walk(path):
                for f in sorted(files):
                    visit(os.path.join(root, f), level)
            return
        name = os.path.basename(path)
        if name.startswith("~$"):
            return
        if archive_suffix(name):
            if level >= depth:
                notes.append("архив «%s» не открыт: вложенность больше %d" % (name, depth))
                return
            counter[0] += 1
            out = Path(tmp.name) / ("a%d" % counter[0])
            out.mkdir()
            try:
                extract(Path(path), out)
            except Exception as e:
                notes.append("архив «%s»: %s" % (name, e))
                return
            visit(str(out), level + 1)
        elif name.lower().endswith(suffixes):
            found.append(path)

    for p in paths:
        if os.path.exists(p):
            visit(p, 0)
        else:
            notes.append("не найдено: %s" % p)
    return sorted(dict.fromkeys(found)), notes, tmp
