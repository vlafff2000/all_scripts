"""Читалки EGRID, INIT, SMSPEC/UNSMRY, RSSPEC, UNRST поверх потокового ``ecl``."""
from __future__ import annotations

import datetime as dt
from typing import Dict, Iterator, List, NamedTuple, Optional, Sequence, Tuple

from .ecl import Block, iter_blocks, read_all


# ---------------------------------------------------------------- сетка

class Grid(NamedTuple):
    ni: int
    nj: int
    nk: int
    actnum: List[int]       # длиной ni*nj*nk, 0 — неактивна
    coord: object           # array('f'), 6 чисел на столбец-узел
    zcorn: object           # array('f'), 8*ni*nj*nk
    mapaxes: Optional[list]

    def cell_index(self, i: int, j: int, k: int) -> int:
        return i + self.ni * (j + self.nj * k)

    def cell_depth(self, i: int, j: int, k: int) -> float:
        """Глубина центра ячейки как среднее восьми углов ZCORN."""
        ni, nj = self.ni, self.nj
        s = 0.0
        for ck in (0, 1):
            for cj in (0, 1):
                base = (2 * k + ck) * 4 * ni * nj + (2 * j + cj) * 2 * ni + 2 * i
                s += self.zcorn[base] + self.zcorn[base + 1]
        return s / 8.0


def read_egrid(path: str) -> Grid:
    d = {b.keyword: v for b, v in read_all(path, ["GRIDHEAD", "COORD", "ZCORN", "ACTNUM", "MAPAXES"])}
    if "GRIDHEAD" not in d:
        raise ValueError("в EGRID нет GRIDHEAD: %s" % path)
    h = d["GRIDHEAD"]
    ni, nj, nk = h[1], h[2], h[3]
    act = list(d["ACTNUM"]) if "ACTNUM" in d else [1] * (ni * nj * nk)
    return Grid(ni, nj, nk, act, d.get("COORD"), d.get("ZCORN"), list(d["MAPAXES"]) if "MAPAXES" in d else None)


def read_init(path: str, keywords: Optional[Sequence[str]] = None) -> Dict[str, object]:
    """Массивы INIT по активным ячейкам (PORV, PORO, DEPTH ...); INTEHEAD и пр. — как есть."""
    return {b.keyword: v for b, v in read_all(path, keywords)}


# ---------------------------------------------------------------- сводка

class Summary(NamedTuple):
    start: dt.datetime
    columns: List[Tuple[str, str, int, str]]   # (ключ, имя/группа, NUMS, единицы)
    dates: List[dt.datetime]
    data: List[List[float]]                    # по шагам, по колонкам


def read_summary(smspec_path: str, unsmry_path: str) -> Summary:
    s = {b.keyword: v for b, v in read_all(smspec_path, ["KEYWORDS", "WGNAMES", "NAMES", "NUMS", "UNITS", "STARTDAT"])}
    names = s.get("WGNAMES") or s.get("NAMES") or []
    kws = s["KEYWORDS"]
    nums = s.get("NUMS") or [0] * len(kws)
    units = s.get("UNITS") or [""] * len(kws)
    sd = s["STARTDAT"]
    start = dt.datetime(sd[2], sd[1], sd[0], sd[3] if len(sd) > 3 else 0, sd[4] if len(sd) > 4 else 0)
    cols = [(kws[i], names[i] if i < len(names) else "", int(nums[i]), units[i] if i < len(units) else "")
            for i in range(len(kws))]
    data = []
    with open(unsmry_path, "rb") as f:
        for b, v in iter_blocks(f, lambda b: b.keyword == "PARAMS"):
            if v is not None:
                data.append(list(v))
    ti = next((i for i, c in enumerate(cols) if c[0] == "TIME"), None)
    if ti is None:
        raise ValueError("в SMSPEC нет вектора TIME")
    scale = 1.0 if cols[ti][3].upper().startswith("DAY") else 1.0 / 24.0
    dates = [start + dt.timedelta(days=r[ti] * scale) for r in data]
    return Summary(start, cols, dates, data)


# ---------------------------------------------------------------- рестарты

class RestartStep(NamedTuple):
    seqnum: int
    date: Optional[dt.datetime]
    blocks: List[Block]          # все блоки шага, включая SEQNUM и INTEHEAD

    def find(self, keyword: str) -> Optional[Block]:
        for b in self.blocks:
            if b.keyword == keyword:
                return b
        return None


def _date_from_intehead(ih) -> Optional[dt.datetime]:
    # ECLIPSE/tNav: ячейки 64..66 (с 1) — день, месяц, год; 207..209 — ч, мин, мкс-секунды
    try:
        day, month, year = ih[64], ih[65], ih[66]
        hh = ih[206] if len(ih) > 208 else 0
        mm = ih[207] if len(ih) > 208 else 0
        return dt.datetime(year, month, day, hh, mm)
    except (IndexError, ValueError):
        return None


def iter_restart_steps(path: str) -> Iterator[RestartStep]:
    """Потоково проходит рестарт-файл, читая только SEQNUM и INTEHEAD; остальное пропускает seek-ом."""
    cur: List[Block] = []
    seq, date = None, None
    with open(path, "rb") as f:
        for b, v in iter_blocks(f, lambda b: b.keyword in ("SEQNUM", "INTEHEAD")):
            if b.keyword == "SEQNUM" and cur:
                yield RestartStep(seq, date, cur)
                cur, seq, date = [], None, None
            cur.append(b)
            if b.keyword == "SEQNUM":
                seq = int(v[0])
            elif b.keyword == "INTEHEAD":
                date = _date_from_intehead(v)
        if cur:
            yield RestartStep(seq, date, cur)


def read_restart_keyword(path: str, step: RestartStep, keyword: str):
    """Прочитать один куб (например SGAS, PRESSURE) на одну дату."""
    blk = step.find(keyword)
    if blk is None:
        return None
    with open(path, "rb") as f:
        f.seek(blk.offset)
        for _b, v in iter_blocks(f, lambda b: True):
            return v
    return None


def read_rsspec(path: str) -> List[Tuple[Block, object]]:
    """RSSPEC: перечень ключевых слов рестарта (формат тот же блочный); возвращает блоки с данными."""
    return read_all(path)
