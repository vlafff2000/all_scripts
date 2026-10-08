"""Потоковая читалка бинарных файлов формата Eclipse (EGRID, INIT, SMSPEC, UNSMRY, RSSPEC, UNRST).

Чистый Python 3.8, без сторонних библиотек. Файл читается блок за блоком:
``iter_blocks`` отдаёт заголовки, а данные читаются только по запросу, поэтому
файл в несколько гигабайт целиком в память не попадает.
"""
from __future__ import annotations

import struct
import sys
from array import array
from typing import BinaryIO, Iterator, List, NamedTuple, Optional, Sequence, Tuple, Union

# тип -> (код array, размер элемента, максимум элементов в одной записи)
_NUM = {b"INTE": ("i", 4, 1000), b"REAL": ("f", 4, 1000), b"DOUB": ("d", 8, 1000),
        b"LOGI": ("i", 4, 1000)}
_CHAR = {b"CHAR": (8, 105), b"C0": (None, 105)}  # C0nn разбирается отдельно


class EclFormatError(ValueError):
    pass


class Block(NamedTuple):
    keyword: str
    count: int
    dtype: str      # 'INTE', 'REAL', 'DOUB', 'LOGI', 'CHAR', 'MESS', 'Cnnn'
    offset: int     # позиция заголовка в файле


def _char_size(dtype: bytes) -> Optional[int]:
    if dtype == b"CHAR":
        return 8
    if dtype[:1] == b"C" and dtype[1:].isdigit():
        return int(dtype[1:])
    return None


def _read_marker(f: BinaryIO) -> Optional[int]:
    raw = f.read(4)
    if not raw:
        return None
    if len(raw) < 4:
        raise EclFormatError("файл оборван внутри маркера записи")
    return struct.unpack(">i", raw)[0]


def _check_end(f: BinaryIO, size: int) -> None:
    end = _read_marker(f)
    if end != size:
        raise EclFormatError("не совпали маркеры записи: %r и %r" % (size, end))


def _data_layout(dtype: bytes, count: int) -> Tuple[int, int]:
    """(размер элемента, элементов в записи) -> раскладка данных после заголовка."""
    if dtype in _NUM:
        return _NUM[dtype][1], _NUM[dtype][2]
    cs = _char_size(dtype)
    if cs is not None:
        return cs, 105 if cs == 8 else max(1, 105 * 8 // cs)
    if dtype == b"MESS":
        return 0, 0
    raise EclFormatError("неизвестный тип данных %r" % dtype)


def iter_blocks(f: BinaryIO, want=None) -> Iterator[Tuple[Block, Optional[object]]]:
    """Идёт по блокам файла. Данные читаются, только если want(Block) истинно
    (want=None: не читать никогда), иначе пропускаются seek-ом."""
    while True:
        pos = f.tell()
        size = _read_marker(f)
        if size is None:
            return
        if size != 16:
            raise EclFormatError("ожидался заголовок блока (16 байт), найдено %r по смещению %d" % (size, pos))
        hdr = f.read(16)
        _check_end(f, 16)
        kw = hdr[:8].decode("ascii", "replace").strip()
        count = struct.unpack(">i", hdr[8:12])[0]
        dtype = hdr[12:16]
        blk = Block(kw, count, dtype.decode("ascii", "replace"), pos)
        esize, per = _data_layout(dtype, count)
        if want is not None and want(blk):
            yield blk, _read_data(f, dtype, count, esize, per)
        else:
            _skip(f, count, esize, per)
            yield blk, None


def _skip(f: BinaryIO, count: int, esize: int, per: int) -> None:
    left = count
    while left > 0:
        n = min(left, per)
        sz = n * esize
        f.seek(4 + sz + 4, 1)
        left -= n


def _read_data(f: BinaryIO, dtype: bytes, count: int, esize: int, per: int):
    left = count
    parts: List[bytes] = []
    while left > 0:
        n = min(left, per)
        sz = _read_marker(f)
        if sz != n * esize:
            raise EclFormatError("размер записи %r не равен ожидаемому %r" % (sz, n * esize))
        parts.append(f.read(sz))
        _check_end(f, sz)
        left -= n
    raw = b"".join(parts)
    if dtype in _NUM:
        code = _NUM[dtype][0]
        a = array(code)
        a.frombytes(raw)
        if sys.byteorder == "little":
            a.byteswap()
        return a if dtype != b"LOGI" else [bool(x) for x in a]
    cs = _char_size(dtype)
    if cs is not None:
        return [raw[i:i + cs].decode("ascii", "replace").rstrip() for i in range(0, len(raw), cs)]
    return None


def read_all(path: str, keywords: Optional[Sequence[str]] = None):
    """Список (Block, данные) для всех (или только нужных) ключевых слов файла."""
    want = set(keywords) if keywords is not None else None
    out = []
    with open(path, "rb") as f:
        for b, data in iter_blocks(f, lambda b: want is None or b.keyword in want):
            if data is not None or (want is None or b.keyword in want):
                out.append((b, data))
    return out
