"""Перфорации скважин из входных файлов модели tNavigator (.data и INCLUDE): COMPDAT, COMPDATL, COMPDATMD, WELOPEN, WELSPECS.

Результаты расчёта (EGRID/UNRST) не содержат ни дат изменения вскрытия, ни глубин интервалов, поэтому читается входной текст
модели: смена состояния привязана к датам из DATES/TSTEP (старт — START). Читалка не округляет и не отбрасывает данные
молча: всё необычное попадает в ``PerfResult.notes``, источник каждой записи (файл, строка) сохраняется — решение за инженером.

Интерфейс:
- ``find_data_files(anchor)`` — главный .data рядом с файлами результатов (на 1–3 папки выше);
- ``read_perforations(path)`` — ``PerfResult`` по .data (или по любому файлу результатов модели);
- ``perforations_at(result, date=None)`` — интервалы на дату (``None`` — после последней записи), строки ``PerfRow``;
- ``change_dates(result)`` — даты, на которые меняется вскрытие;
- ``add_depths(rows, grid)`` — верх/низ интервала в абсолютных отметках (а.о., ниже моря со знаком минус) по сетке EGRID.

Только стандартная библиотека, Python 3.8+.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import os
import re
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "JLY": 7, "AUG": 8, "SEP": 9,
          "OCT": 10, "NOV": 11, "DEC": 12}

# ключевые слова, которые читаются, даже если стоят в одной строке с данными; число записей: 1 — одна, 0 — до пустой «/»
KNOWN = {"START": 1, "DATES": 0, "TSTEP": 1, "INCLUDE": 1, "IMPORT": 1, "WELSPECS": 0, "COMPDAT": 0, "COMPDATL": 0,
         "COMPDATMD": 0, "WELOPEN": 0, "WELLTRACK": 1}


class PermEvent(NamedTuple):
    """Одна запись входного файла, влияющая на вскрытие."""
    well: str                       # имя; у WELOPEN может быть маской с «*»
    date: Optional[dt.datetime]     # дата действия записи (None — до первой даты и без START)
    kind: str                       # COMPDAT | COMPDATL | COMPDATMD | WELOPEN
    i: Optional[int]
    j: Optional[int]
    k1: Optional[int]
    k2: Optional[int]
    status: Optional[str]           # OPEN | SHUT | STOP | AUTO; None — не задан (WELOPEN: только поменять i,j,k)
    md_top: Optional[float]
    md_bottom: Optional[float]
    file: str
    line: int


class WellSpec(NamedTuple):
    well: str
    group: Optional[str]
    i: Optional[int]
    j: Optional[int]
    ref_depth: Optional[float]
    date: Optional[dt.datetime]
    file: str
    line: int


class PerfRow(NamedTuple):
    well: str
    i: Optional[int]
    j: Optional[int]
    k1: Optional[int]               # None — интервал задан по MD (COMPDATMD)
    k2: Optional[int]
    status: str
    md_top: Optional[float] = None
    md_bottom: Optional[float] = None
    top_ao: Optional[float] = None  # заполняет add_depths
    bottom_ao: Optional[float] = None
    source: str = ""                # файл:строка последней записи, определившей строку


class PerfResult(NamedTuple):
    events: List[PermEvent]
    wells: List[WellSpec]
    start: Optional[dt.datetime]
    files: List[str]
    notes: List[str]
    tracks: Optional[Dict[str, List[Tuple[float, float, float, float]]]] = None   # WELLTRACK: скважина → точки (X, Y, Z, MD)


# ---------------------------------------------------------------- токены

_WORD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TOKEN = re.compile(r"""'[^']*'|"[^"]*"|/|[^\s/'"]+""")


def _strip_comment(line: str) -> str:
    out, quote = [], ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "-" and line[i:i + 2] == "--":
            break
        out.append(ch)
        i += 1
    return "".join(out)


class _Tok(NamedTuple):
    text: str
    line: int
    first: bool     # первый токен строки
    alone: bool     # единственный токен строки


def _tokenize(text: str) -> List[_Tok]:
    out: List[_Tok] = []
    for n, raw in enumerate(text.splitlines(), 1):
        toks = _TOKEN.findall(_strip_comment(raw))
        for idx, t in enumerate(toks):
            out.append(_Tok(t, n, idx == 0, len(toks) == 1))
    return out


def _unquote(t: str) -> str:
    return t[1:-1] if len(t) >= 2 and t[0] in "'\"" and t[-1] == t[0] else t


def _values(tokens: Sequence[str]) -> List[Optional[str]]:
    """Значения записи; «n*» — n значений по умолчанию (None), «n*x» — n копий x."""
    out: List[Optional[str]] = []
    for t in tokens:
        m = re.match(r"^(\d+)\*(.*)$", t)
        if m:
            v = _unquote(m.group(2)) if m.group(2) else None
            out.extend([v] * int(m.group(1)))
        else:
            out.append(_unquote(t))
    return out


def _int(v: Optional[str]) -> Optional[int]:
    try:
        return int(float(v)) if v not in (None, "") else None
    except ValueError:
        return None


def _float(v: Optional[str]) -> Optional[float]:
    try:
        return float(v.replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def _status(v: Optional[str], default: Optional[str] = "OPEN") -> Optional[str]:
    if v is None:
        return default
    s = v.strip().upper()
    return {"OPEN": "OPEN", "SHUT": "SHUT", "STOP": "STOP", "AUTO": "AUTO"}.get(s, default)


def _item(v: Sequence[Optional[str]], n: int) -> Optional[str]:
    return v[n] if n < len(v) else None


# ---------------------------------------------------------------- разбор

class _State:
    def __init__(self):
        self.date: Optional[dt.datetime] = None
        self.start: Optional[dt.datetime] = None
        self.events: List[PermEvent] = []
        self.wells: List[WellSpec] = []
        self.files: List[str] = []
        self.notes: List[str] = []
        self.heads: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
        self.tracks: Dict[str, List[Tuple[float, float, float, float]]] = {}


def _read_records(toks: List[_Tok], pos: int, single: bool) -> Tuple[List[Tuple[List[str], int]], int]:
    """Записи ключевого слова с позиции pos: (токены записи, строка). Конец — пустая «/» или (single) первая запись."""
    recs: List[Tuple[List[str], int]] = []
    cur: List[str] = []
    line0 = toks[pos].line if pos < len(toks) else 0
    while pos < len(toks):
        t = toks[pos]
        pos += 1
        if t.text == "/":
            if not cur:
                if single:
                    continue
                break
            recs.append((cur, line0))
            cur = []
            line0 = toks[pos].line if pos < len(toks) else 0
            if single:
                break
        else:
            if not cur:
                line0 = t.line
            cur.append(t.text)
    else:
        if cur:
            recs.append((cur, line0))
    return recs, pos


def _parse_date(vals: Sequence[Optional[str]]) -> Optional[dt.datetime]:
    try:
        day, mon, year = int(float(vals[0])), str(vals[1]).strip().upper()[:3], int(float(vals[2]))
        month = MONTHS["JLY" if mon == "JLY" else mon]
        hh = mm = ss = 0
        if len(vals) > 3 and vals[3]:
            parts = (str(vals[3]) + ":0:0").split(":")
            hh, mm, ss = int(parts[0]), int(parts[1]), int(float(parts[2]))
        return dt.datetime(year, month, day, hh, mm, ss)
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _parse_file(path: str, st: _State, seen: Tuple[str, ...], depth: int = 0) -> None:
    if depth > 12 or os.path.abspath(path) in seen:
        st.notes.append("INCLUDE зациклен или слишком вложен: %s" % path)
        return
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        st.notes.append("файл не открыт: %s (%s)" % (path, e))
        return
    st.files.append(path)
    seen = seen + (os.path.abspath(path),)
    toks = _tokenize(text)
    pos, base = 0, os.path.dirname(os.path.abspath(path))
    fname = os.path.basename(path)
    while pos < len(toks):
        t = toks[pos]
        key = t.text.upper()
        is_kw = _WORD.match(t.text) and t.first and (key in KNOWN or (t.alone and t.text.isupper()))
        if not is_kw:
            pos += 1
            continue
        pos += 1
        if key not in KNOWN:
            continue                      # чужое ключевое слово: его записи пропускаются как не-ключевые токены
        recs, pos = _read_records(toks, pos, KNOWN[key] == 1)
        if key == "START" and recs:
            d = _parse_date(_values(recs[0][0]))
            if d:
                st.start = st.start or d
                st.date = st.date or d
        elif key == "DATES":
            for r, _ in recs:
                d = _parse_date(_values(r))
                if d:
                    st.date = d
                else:
                    st.notes.append("%s: не разобрана дата DATES: %s" % (fname, " ".join(r)))
        elif key == "TSTEP" and recs:
            if st.date is None:
                st.notes.append("%s: TSTEP без START — даты после него неизвестны" % fname)
            else:
                days = 0.0
                for v in _values(recs[0][0]):
                    days += (_float(v) or 0.0)
                st.date = st.date + dt.timedelta(days=days)
        elif key in ("INCLUDE", "IMPORT") and recs:
            name = _unquote(recs[0][0][0])
            cand = [os.path.join(base, name), os.path.join(os.path.dirname(os.path.abspath(st.files[0])), name)]
            real = next((c for c in cand if os.path.isfile(c)), None)
            if real is None:
                st.notes.append("%s: INCLUDE-файл не найден: %s" % (fname, name))
            else:
                _parse_file(real, st, seen, depth + 1)
        elif key == "WELLTRACK" and recs:
            v = _values(recs[0][0])
            nums = [_float(x) for x in v[1:]]
            pts = [tuple(nums[n:n + 4]) for n in range(0, len(nums) - 3, 4)]
            if v and v[0] and pts and all(None not in q for q in pts):
                st.tracks[v[0]] = pts
            else:
                st.notes.append("%s: WELLTRACK %s не разобран (ожидаются четвёрки X Y Z MD)" % (fname, v[0] if v else "?"))
        elif key == "WELSPECS":
            for r, ln in recs:
                v = _values(r)
                well = _item(v, 0)
                if not well:
                    continue
                i, j = _int(_item(v, 2)), _int(_item(v, 3))
                st.heads[well] = (i, j)
                st.wells.append(WellSpec(well, _item(v, 1), i, j, _float(_item(v, 4)), st.date, fname, ln))
        elif key in ("COMPDAT", "COMPDATL", "COMPDATMD"):
            for r, ln in recs:
                _compdat(key, _values(r), ln, fname, st)
        elif key == "WELOPEN":
            for r, ln in recs:
                v = _values(r)
                well = _item(v, 0)
                if well:
                    st.events.append(PermEvent(well, st.date, "WELOPEN", _int(_item(v, 2)), _int(_item(v, 3)),
                                               _int(_item(v, 4)), _int(_item(v, 4)), _status(_item(v, 1), None),
                                               None, None, fname, ln))


def _compdat(key: str, v: List[Optional[str]], ln: int, fname: str, st: _State) -> None:
    well = _item(v, 0)
    if not well:
        return
    off = 0
    if key in ("COMPDATL", "COMPDATMD"):
        off = 1                           # второй столбец — имя локальной сетки (LGR); мелкая сетка не читается
        if _item(v, 1) not in (None, "", "GLOBAL"):
            st.notes.append("%s:%d %s: скважина %s в локальной сетке %s — индексы относятся к ней" % (fname, ln, key, well, _item(v, 1)))
    i, j = _int(_item(v, 1 + off)), _int(_item(v, 2 + off))
    head = st.heads.get(well, (None, None))
    i = i if i is not None else head[0]
    j = j if j is not None else head[1]
    if key == "COMPDATMD":
        # tNavigator/Eclipse: скважина, сетка, I, J, MD верха, MD низа, состояние; K определяется по траектории, раскладка не проверена на файле Егора
        md1, md2 = _float(_item(v, 3 + off)), _float(_item(v, 4 + off))
        st.events.append(PermEvent(well, st.date, key, i, j, None, None, _status(_item(v, 5 + off)), md1, md2, fname, ln))
        return
    k1, k2 = _int(_item(v, 3 + off)), _int(_item(v, 4 + off))
    k2 = k2 if k2 is not None else k1
    k1 = k1 if k1 is not None else k2
    if None in (i, j, k1):
        st.notes.append("%s:%d %s: у скважины %s нет I, J или K (и нет WELSPECS) — запись пропущена" % (fname, ln, key, well))
        return
    st.events.append(PermEvent(well, st.date, key, i, j, k1, k2, _status(_item(v, 5 + off)), None, None, fname, ln))


# ---------------------------------------------------------------- поиск файлов

def find_data_files(anchor: str) -> List[str]:
    """Файлы .data модели: рядом с anchor (любой файл результатов) и на 1–3 папки выше. Сначала совпавшие по имени с моделью
    или папкой, затем остальные; пусто — входного файла рядом нет."""
    folder = os.path.dirname(os.path.abspath(anchor)) if not os.path.isdir(anchor) else os.path.abspath(anchor)
    stem = os.path.splitext(os.path.basename(anchor))[0].lower() if not os.path.isdir(anchor) else ""
    probe = {stem, os.path.basename(folder).lower()}
    cur = folder
    for _ in range(4):
        try:
            names = sorted(n for n in os.listdir(cur) if n.lower().endswith(".data"))
        except OSError:
            names = []
        if names:
            hit = [n for n in names if os.path.splitext(n)[0].lower() in probe]
            return [os.path.join(cur, n) for n in (hit or names)]
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        probe.add(os.path.basename(cur).lower())
        cur = nxt
    return []


def read_perforations(path: str) -> PerfResult:
    """Перфорации по входному файлу модели. path — .data (или include-файл с COMPDAT) либо файл результатов: тогда .data ищется
    через ``find_data_files`` и, если их несколько, читается первый (остальные — в notes)."""
    st = _State()
    if path.lower().endswith((".data", ".inc", ".include", ".sch", ".schedule", ".txt")):
        files = [path]                    # входной файл назван прямо: не подменять его соседним .data
        if not os.path.isfile(path):
            st.notes.append("файл не найден: %s" % path)
            files = []
    else:
        files = find_data_files(path)
        if not files:
            st.notes.append("рядом с моделью нет файла .data: %s" % path)
        elif len(files) > 1:
            st.notes.append("найдено несколько файлов .data, прочитан первый: %s" % ", ".join(os.path.basename(f) for f in files))
            files = files[:1]
    for f in files:
        _parse_file(f, st, ())
    if not st.events and files:
        st.notes.append("в файлах модели нет COMPDAT/COMPDATL/COMPDATMD")
    return PerfResult(st.events, st.wells, st.start, st.files, st.notes, st.tracks)


# ---------------------------------------------------------------- состояние на дату

def change_dates(res: PerfResult) -> List[dt.datetime]:
    """Даты, на которые есть записи о вскрытии (без повторов, по возрастанию); запись без даты не включается."""
    return sorted({e.date for e in res.events if e.date is not None})


def perforations_at(res: PerfResult, date: Optional[dt.datetime] = None, only_open: bool = True,
                    wells: Optional[Sequence[str]] = None) -> List[PerfRow]:
    """Интервалы скважин на дату (записи с датой ≤ date; ``None`` — все записи). Ячейки одного столбца с одинаковым состоянием
    склеиваются в интервал K1–K2. Позже заданное главнее раннего; WELOPEN меняет состояние уже вскрытых ячеек.
    Состояние AUTO считается открытым (решение откроет расчёт), SHUT и STOP — закрытыми."""
    cells: Dict[str, Dict[tuple, Tuple[str, str]]] = {}
    for e in res.events:
        if date is not None and e.date is not None and e.date > date:
            continue
        src = "%s:%d" % (e.file, e.line)
        if e.kind == "WELOPEN":
            for w in [w for w in cells if fnmatch.fnmatchcase(w, e.well)]:
                for key, (st, _s) in list(cells[w].items()):
                    if key[0] == "md":
                        if e.i is None and e.j is None and e.k1 is None and e.status:
                            cells[w][key] = (e.status, src)
                        continue
                    i, j, k = key
                    if (e.i is None or e.i == i) and (e.j is None or e.j == j) and (e.k1 is None or e.k1 == k) and e.status:
                        cells[w][key] = (e.status, src)
            continue
        c = cells.setdefault(e.well, {})
        if e.kind == "COMPDATMD":
            c[("md", e.i, e.j, e.md_top, e.md_bottom)] = (e.status or "OPEN", src)
        else:
            for k in range(min(e.k1, e.k2), max(e.k1, e.k2) + 1):
                c[(e.i, e.j, k)] = (e.status or "OPEN", src)
    rows: List[PerfRow] = []
    for w in sorted(cells):
        if wells is not None and w not in wells:
            continue
        cols: Dict[tuple, list] = {}
        for key, (status, src) in sorted(cells[w].items(), key=lambda x: str(x[0])):
            if key[0] == "md":
                _m, i, j, a, b = key
                rows.append(PerfRow(w, i, j, None, None, status, a, b, None, None, src))
            else:
                cols.setdefault((key[0], key[1]), []).append((key[2], status, src))
        for (i, j), ks in sorted(cols.items()):
            ks.sort()
            run = [ks[0]]
            for item in ks[1:] + [None]:
                if item is not None and item[0] == run[-1][0] + 1 and item[1] == run[-1][1]:
                    run.append(item)
                    continue
                rows.append(PerfRow(w, i, j, run[0][0], run[-1][0], run[0][1], None, None, None, None, run[-1][2]))
                run = [item] if item is not None else []
    if only_open:
        rows = [r for r in rows if r.status in ("OPEN", "AUTO")]
    return rows


# ---------------------------------------------------------------- глубины

def _cell_top_bottom(grid, i: int, j: int, k: int) -> Tuple[float, float]:
    """Средние глубины верхней и нижней граней ячейки по ZCORN (м, вниз положительно)."""
    ni, nj = grid.ni, grid.nj
    z = grid.zcorn
    out = []
    for ck in (0, 1):
        base = (2 * k + ck) * 4 * ni * nj + (2 * j) * 2 * ni + 2 * i
        s = z[base] + z[base + 1] + z[base + 2 * ni] + z[base + 2 * ni + 1]
        out.append(s / 4.0)
    return out[0], out[1]


def add_depths(rows: Sequence[PerfRow], grid) -> List[PerfRow]:
    """Добавляет top_ao/bottom_ao (а.о., ниже моря со знаком минус): верх ячейки K1 и низ ячейки K2. Номера I, J, K в модели —
    с единицы. Интервалы по MD и ячейки вне сетки остаются без отметок. Единицы глубины — как в EGRID (метрическая модель)."""
    out: List[PerfRow] = []
    for r in rows:
        if r.k1 is None or r.i is None or r.j is None or grid is None or getattr(grid, "zcorn", None) is None:
            out.append(r)
            continue
        i, j, k1, k2 = r.i - 1, r.j - 1, r.k1 - 1, r.k2 - 1
        if not (0 <= i < grid.ni and 0 <= j < grid.nj and 0 <= k1 <= k2 < grid.nk):
            out.append(r)
            continue
        top = _cell_top_bottom(grid, i, j, k1)[0]
        bottom = _cell_top_bottom(grid, i, j, k2)[1]
        out.append(r._replace(top_ao=-top, bottom_ao=-bottom))
    return out
