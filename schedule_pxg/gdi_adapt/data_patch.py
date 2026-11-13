"""Правка КОПИИ .data: вставка WPIMULT/WDFAC на даты ГДИ и предупреждения об управлении скважины.

Оригинал не меняется никогда: копия пишется в другую папку, совпадение путей - ошибка.
Вставка идёт по датам: после блока DATES нужной даты (или новым DATES перед первой более поздней датой).
Мульты накопительные: вставляется приращение (из журнала мультов, ручное значение инженера приоритетнее авто),
повторный COMPDAT мульт не сбрасывает. Блоки помечены комментарием MARK: копия всегда собирается заново из оригинала.
"""
from __future__ import annotations

import fnmatch
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .mults import _MONTHS
from .outputs import MONTHS

MARK = '-- GDM-ADAPT'


def _read(path: str) -> Tuple[str, str]:
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp1251'):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return raw.decode('latin-1'), 'latin-1'


def _date(toks: List[str]) -> Optional[datetime]:
    try:
        if len(toks) >= 3 and toks[1].strip("'\"").upper()[:3] in _MONTHS:
            return datetime(int(toks[2]), _MONTHS[toks[1].strip("'\"").upper()[:3]], int(toks[0]))
    except ValueError:
        pass
    return None


def _clean(line: str) -> str:
    return line.split('--')[0].strip()


def scan_dates(lines: List[str]) -> List[dict]:
    """Блоки DATES: [{start (строка DATES), end (строка '/'), items: [(индекс строки, дата)]}]."""
    out, cur = [], None
    for i, raw in enumerate(lines):
        s = _clean(raw)
        if cur is None:
            if s.upper() == 'DATES':
                cur = {'start': i, 'end': None, 'items': []}
        elif s == '/':
            cur['end'] = i
            out.append(cur)
            cur = None
        elif s:
            d = _date(s.replace('/', ' ').split())
            if d:
                cur['items'].append((i, d))
    return out


def _keywords(date: datetime, rows: List[Tuple[str, float, Optional[float]]], new_dates: bool) -> List[str]:
    out = [MARK + ' (начало)']
    if new_dates:
        out += ['DATES', f'{date.day:02d} {MONTHS[date.month - 1]} {date.year}\t/', '/']
    out += ['WPIMULT'] + [f'{w}\t{inc:.8g}\t/' for w, inc, _ in rows] + ['/']
    d_rows = [(w, d) for w, _, d in rows if d is not None]
    if d_rows:
        out += ['WDFAC'] + [f'{w}\t{d:.8e}\t/' for w, d in d_rows] + ['/']
    return out + [MARK + ' (конец)', '']


def strip_marked(lines: List[str]) -> List[str]:
    """Убирает ранее вставленные блоки (чтобы повторная правка не удваивала мульты)."""
    out, skip, tail = [], False, False
    for ln in lines:
        t = ln.rstrip('\r')
        if tail:                                    # пустая строка после блока тоже наша
            tail = False
            if not t.strip():
                continue
        if t.startswith(MARK + ' (начало)'):
            skip = True
        elif skip:
            skip = not t.startswith(MARK + ' (конец)')
            tail = not skip
        else:
            out.append(ln)
    return out


def patch_text(text: str, entries: Dict[datetime, List[Tuple[str, float, Optional[float]]]]) -> Tuple[str, dict]:
    """entries: {дата: [(скважина, приращение WPIMULT, D-фактор или None)]}. Возвращает (текст, отчёт)."""
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = strip_marked(text.split('\n'))
    lines = [ln.rstrip('\r') for ln in lines]
    blocks = scan_dates(lines)
    flat = [(i, d, b) for b in blocks for i, d in b['items']]
    ins: Dict[int, List[str]] = {}      # индекс строки -> строки, вставляемые ПЕРЕД ней
    rep = {'existing_dates': [], 'new_dates': [], 'wells': 0}

    def put(pos: int, chunk: List[str]) -> None:
        ins.setdefault(pos, []).extend(chunk)

    for date in sorted(entries):
        rows = entries[date]
        rep['wells'] += len(rows)
        hit = next(((i, b) for i, d, b in flat if d == date), None)
        if hit:
            i, b = hit
            last = b['items'][-1][0] == i
            rep['existing_dates'].append(date)
            if last:
                put(b['end'] + 1, _keywords(date, rows, False))
            else:                                   # дата в середине блока: закрываем блок, вставляем, открываем снова
                put(i + 1, ['/'] + _keywords(date, rows, False) + ['DATES'])
            continue
        rep['new_dates'].append(date)
        later = next(((i, b) for i, d, b in flat if d > date), None)
        if later is None:
            end = len(lines)
            while end > 0 and not _clean(lines[end - 1]):
                end -= 1
            if end > 0 and _clean(lines[end - 1]).upper() == 'END':
                end -= 1
            put(end, _keywords(date, rows, True))
        else:
            i, b = later
            if b['items'][0][0] == i:
                put(b['start'], _keywords(date, rows, True))
            else:                                   # перед i в середине блока
                put(i, ['/'] + _keywords(date, rows, True) + ['DATES'])
    out: List[str] = []
    for i, ln in enumerate(lines):
        out += ins.get(i, [])
        out.append(ln)
    out += ins.get(len(lines), [])
    return nl.join(out), rep


def entries_from_results(results, journal=None, only_ok: bool = False, sequential: bool = True) -> dict:
    """Приращения на даты из результатов адаптации; журнал (с ручными значениями) приоритетнее авто-расчёта."""
    from .outputs import resolve_mults
    rows, inc, dval = resolve_mults(results, only_ok, sequential, journal)
    out: dict = {}
    for r in rows:
        out.setdefault(r.date, []).append((r.wname, inc[id(r)], dval[id(r)]))
    return out


def patch_data_copy(src: str, dest_dir: str, entries: dict) -> Tuple[str, dict]:
    """Копия .data с вставленными мультами в dest_dir. Оригинал не трогается. Возвращает (путь копии, отчёт)."""
    dest = os.path.join(dest_dir, os.path.basename(src))
    if os.path.realpath(dest) == os.path.realpath(src):
        raise ValueError('Копия должна лежать в другой папке: оригинал .data менять нельзя')
    text, enc = _read(src)
    new, rep = patch_text(text, entries)
    os.makedirs(dest_dir, exist_ok=True)
    with open(dest, 'w', encoding=enc if enc != 'utf-8-sig' else 'utf-8', newline='') as f:
        f.write(new)
    rep['dest'] = dest
    return dest, rep


# ---------- управление скважин: забойное давление и групповые цели ----------
def control_warnings(text: str, wells_dates: List[Tuple[str, datetime]]) -> Dict[Tuple[str, datetime], List[str]]:
    """Предупреждения по (скважина, дата ГДИ): скважина под контролем по забойному давлению (WCONPROD BHP) или
    её группа под групповой целью (GCONPROD). Тогда мульт меняет дебит, а не депрессию."""
    well_mode: Dict[str, str] = {}      # скважина (или маска) -> режим на текущую дату
    grp_mode: Dict[str, str] = {}
    well_grp: Dict[str, str] = {}
    events = []                         # (дата, снимок)
    date, block, in_dates = None, None, False
    snaps = []
    pending = sorted({d for _, d in wells_dates})
    k = 0

    def snap(upto):
        nonlocal k
        while k < len(pending) and (upto is None or pending[k] < upto):
            snaps.append((pending[k], dict(well_mode), dict(grp_mode), dict(well_grp)))
            k += 1

    for raw in text.splitlines():
        s = _clean(raw)
        if not s:
            continue
        up = s.upper()
        if up in ('DATES', 'WCONPROD', 'WCONHIST', 'GCONPROD', 'WELSPECS'):
            block = up
            continue
        if s == '/':
            block = None
            continue
        toks = s.replace('/', ' ').split()
        if block == 'DATES':
            d = _date(toks)
            if d:
                snap(d)
                date = d
        elif block in ('WCONPROD', 'WCONHIST') and len(toks) >= 3:
            well_mode[toks[0].strip("'\"")] = toks[2].strip("'\"").upper() if block == 'WCONPROD' else 'HIST'
        elif block == 'GCONPROD' and len(toks) >= 2:
            grp_mode[toks[0].strip("'\"")] = toks[1].strip("'\"").upper()
        elif block == 'WELSPECS' and len(toks) >= 2:
            well_grp[toks[0].strip("'\"")] = toks[1].strip("'\"")
    snap(None)
    by_date = {d: (wm, gm, wg) for d, wm, gm, wg in snaps}
    out: Dict[Tuple[str, datetime], List[str]] = {}
    for w, d in wells_dates:
        wm, gm, wg = by_date.get(d, ({}, {}, {}))
        msgs = []
        mode = wm.get(w) or next((m for k2, m in wm.items() if any(c in k2 for c in '*?') and fnmatch.fnmatch(w, k2)), None)
        if mode == 'BHP':
            msgs.append('скважина управляется забойным давлением (WCONPROD BHP): мульт изменит дебит, а не депрессию')
        g = wg.get(w)
        if g and gm.get(g) not in (None, 'NONE', ''):
            msgs.append(f'группа {g} задана групповой целью (GCONPROD {gm[g]}): мульт перераспределит дебит между скважинами группы')
        if msgs:
            out[(w, d)] = msgs
    return out
