"""Кэш сетки EGRID на диске: ``~/.pxg/grid_cache/`` (каталог меняется PXG_HOME).

Структура сетки (ACTNUM, COARSEN, ZCORN, COORD) у всех расчётов одной модели одна, а разбор файла в десятки мегабайт долог.
Первый раз сетка читается из EGRID и сохраняется массивами numpy; дальше берётся из кэша, пока размер и дата файла не изменились.
Любая ошибка кэша (нет места, битый файл, чужая версия) молча ведёт к обычному чтению EGRID: расчёт от кэша не зависит.
"""
from __future__ import annotations

import hashlib
import os
from array import array
from typing import Optional, Tuple

import numpy as np

from .files import Grid, read_egrid

VERSION = 1
KEEP = 4          # сколько сеток держать на диске (остальные, самые старые, удаляются)


def cache_dir() -> str:
    home = os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg")
    return os.path.join(home, "grid_cache")


def file_key(path: str) -> Tuple[str, int, int]:
    st = os.stat(path)
    return os.path.abspath(path), st.st_size, st.st_mtime_ns


def _name(key: Tuple[str, int, int]) -> str:
    h = hashlib.sha1(("%d|%s|%d|%d" % (VERSION, key[0], key[1], key[2])).encode("utf-8")).hexdigest()
    return os.path.join(cache_dir(), h[:24] + ".npz")


def _save(path: str, g: Grid) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    opt = {}
    for name in ("coord", "zcorn", "corsnum", "actnumc"):
        v = getattr(g, name)
        if v is not None:
            opt[name] = np.asarray(v, dtype=np.float32 if name in ("coord", "zcorn") else np.int32)
    tmp = path + ".%d.tmp" % os.getpid()
    with open(tmp, "wb") as f:
        np.savez(f, dims=np.array([g.ni, g.nj, g.nk], dtype=np.int64), actnum=np.asarray(g.actnum, dtype=np.int32),
                 mapaxes=np.asarray(g.mapaxes if g.mapaxes is not None else [], dtype=np.float64),
                 has_mapaxes=np.array([g.mapaxes is not None]), lgr=np.array(list(g.lgr), dtype=str), **opt)
    os.replace(tmp, path)


def _load(path: str) -> Grid:
    with np.load(path, allow_pickle=False) as z:
        ni, nj, nk = (int(x) for x in z["dims"])

        def arr(name: str, code: str) -> Optional[array]:
            if name not in z.files:
                return None
            a = array(code)
            a.frombytes(memoryview(np.ascontiguousarray(z[name], dtype=np.float32 if code == "f" else np.int32)).cast("B"))
            return a

        return Grid(ni, nj, nk, z["actnum"].tolist(), arr("coord", "f"), arr("zcorn", "f"),
                    z["mapaxes"].tolist() if bool(z["has_mapaxes"][0]) else None,
                    arr("corsnum", "i"), arr("actnumc", "i"), tuple(str(x) for x in z["lgr"]))


def _prune() -> None:
    d = cache_dir()
    files = sorted((os.path.getmtime(os.path.join(d, n)), os.path.join(d, n)) for n in os.listdir(d) if n.endswith(".npz"))
    for _t, p in files[:-KEEP]:
        os.remove(p)


def read_egrid_cached(egrid_path: str) -> Grid:
    """Как ``read_egrid``, но с кэшем на диске по размеру и дате файла."""
    try:
        path = _name(file_key(egrid_path))
        if os.path.isfile(path):
            try:
                return _load(path)
            except Exception:       # битый или чужой кэш: читаем заново и перезаписываем
                pass
    except OSError:
        return read_egrid(egrid_path)
    g = read_egrid(egrid_path)
    try:
        _save(path, g)
        _prune()
    except Exception:
        pass
    return g
