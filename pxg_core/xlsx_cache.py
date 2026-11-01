"""Быстрая копия больших книг Excel в Parquet.

Главный файл — всегда xlsx: инженер правит его руками. Копия — производная: ключ — сумма sha256 содержимого книги, листа и
параметров чтения. Поправили книгу — сумма другая, копия пересобирается; копию можно удалить в любой момент
(папка ``xlsx_cache`` в ``PXG_HOME``, по умолчанию ``~/.pxg``). Читается копия только если даёт ТОЧНО тот же результат, что xlsx:
таблица с нестроковыми именами столбцов или столбцами смешанных типов (числа и текст) в Parquet не ложится и читается из xlsx, как раньше.

PXG_XLSX_CACHE=0 — выключить; PXG_XLSX_CACHE_MIN_MB — порог размера книги (по умолчанию 5 МБ); хранится не больше 8 копий.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

_VERSION = 1
KEEP = 8


def enabled() -> bool:
    return os.environ.get("PXG_XLSX_CACHE", "1") != "0"


def min_bytes() -> int:
    try:
        return int(float(os.environ.get("PXG_XLSX_CACHE_MIN_MB", "5")) * 1024 * 1024)
    except ValueError:
        return 5 * 1024 * 1024


def cache_dir() -> Path:
    return Path(os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg")) / "xlsx_cache"


def _file_sha(path: str) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _key(path: str, kwargs: dict) -> str:
    # pandas подмешан в ключ: типы столбцов между мажорными версиями различаются
    text = "|".join([_file_sha(path), repr(sorted((k, repr(v)) for k, v in kwargs.items())),
                     "v%d" % _VERSION, pd.__version__.split(".")[0]])
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:24]


def _cacheable(df: pd.DataFrame) -> bool:
    return (isinstance(df, pd.DataFrame) and len(df.columns) > 0 and all(isinstance(c, str) for c in df.columns)
            and df.columns.is_unique and isinstance(df.index, pd.RangeIndex))


def _restore(df: pd.DataFrame) -> pd.DataFrame:
    """Parquet отдаёт пропуск в текстовом столбце как None, чтение xlsx — как NaN: возвращаем NaN."""
    for col in df.columns[df.dtypes.eq(object)]:
        df[col] = df[col].where(df[col].notna(), np.nan)
    return df


def _prune(folder: Path) -> None:
    try:
        files = sorted(folder.glob("*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[KEEP:]:
            old.unlink()
    except OSError:
        pass


def read_cached(path, read: Callable[..., pd.DataFrame], **kwargs) -> pd.DataFrame:
    """``read(path, **kwargs)`` с копией в Parquet; любые сбои копии молча сводятся к обычному чтению xlsx."""
    path = str(path)
    use = False
    try:
        use = (enabled() and path.lower().endswith((".xlsx", ".xlsm")) and os.path.getsize(path) >= min_bytes())
    except OSError:
        pass
    if not use:
        return read(path, **kwargs)
    target: Optional[Path] = None
    try:
        target = cache_dir() / (_key(path, kwargs) + ".parquet")
        if target.is_file():
            df = _restore(pd.read_parquet(target))
            target.touch()
            return df
    except Exception:
        pass
    df = read(path, **kwargs)
    try:
        if target is not None and _cacheable(df):
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".%d.tmp" % os.getpid())
            try:
                df.to_parquet(tmp, index=False, compression="zstd")
                os.replace(tmp, target)
            finally:
                if tmp.exists():
                    tmp.unlink()
            _prune(target.parent)
    except Exception:
        pass       # копия не обязательна (смешанные типы, нет места, нет pyarrow)
    return df
