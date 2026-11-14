"""Рабочая папка тестового прогона: копия .data с расписанием, обрезанным на дату ГДИ, режимами ГДИ и мультами.

Оригинал модели не меняется никогда. Большие файлы сетки и свойств не копируются: пути INCLUDE в копии абсолютные
(указывают на оригинал, только чтение). Копируется только то, что tNavigator перезаписывает при рестарте: папка RESULTS
(десятки ГБ, копируется один раз и переиспользуется всеми итерациями).
Расписание: INCLUDE секции SCHEDULE до файла с датой ГДИ остаются прежними, файл с датой ГДИ заменяется своей обрезанной
копией с тестовым блоком, все INCLUDE после него убираются. Расписание прямо в .data (не в include) и вложенные include
после даты ГДИ не поддерживаются: понятная ошибка, а не молчаливо неверный прогон.
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import regime_run as rr
from .data_patch import _clean, _date, _read, scan_dates

_START_RE = re.compile(r'^\s*START\b', re.I)
_SECTIONS = ('RUNSPEC', 'GRID', 'EDIT', 'PROPS', 'REGIONS', 'SOLUTION', 'SUMMARY', 'SCHEDULE')


class CaseError(ValueError):
    pass


def model_start(text: str) -> datetime:
    """Дата START модели (нужна для дней от начала расчёта в RSM)."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if _START_RE.match(_clean(ln) or ''):
            for nxt in lines[i + 1:i + 4]:
                toks = _clean(nxt).replace('/', ' ').split()
                d = _date(toks)
                if d:
                    return d
    raise CaseError('в .data не найдена дата START')


def include_records(lines: Sequence[str]) -> List[Tuple[int, int, str]]:
    """INCLUDE-записи: (строка слова INCLUDE, строка с именем файла, имя). Имя в кавычках или без, до ' /'."""
    out = []
    i = 0
    while i < len(lines):
        if _clean(lines[i]).upper() == 'INCLUDE':
            j = i + 1
            while j < len(lines) and not _clean(lines[j]):
                j += 1
            if j < len(lines):
                tok = _clean(lines[j]).split('/')[0].strip()
                m = re.match(r"""^(['"])(.*)\1$""", tok)
                out.append((i, j, m.group(2) if m else tok))
                i = j
        i += 1
    return out


def _abs(name: str, src_dir: str) -> str:
    p = name if os.path.isabs(name) else os.path.join(src_dir, name)
    return os.path.abspath(p).replace('\\', '/')


def _rewrite_include(line: str, new_name: str) -> str:
    return f"'{new_name}' /"


def _split_sections(lines: List[str]) -> Tuple[int, int]:
    """Индекс строки SCHEDULE и конца секции (строка END или конец файла)."""
    sched = next((i for i, ln in enumerate(lines) if _clean(ln).upper() == 'SCHEDULE'), None)
    if sched is None:
        raise CaseError('в .data нет секции SCHEDULE')
    end = next((i for i in range(len(lines) - 1, sched, -1) if _clean(lines[i]).upper() == 'END'), len(lines))
    return sched, end


def build_case(src_data: str, workdir: str, start: datetime, regimes: Dict[str, Sequence[float]], mults: Optional[list] = None,
               wells: Optional[Sequence[str]] = None, name: str = 'T', step_days: int = 1, extra_lines: Sequence[str] = ()) -> dict:
    """Пишет в workdir копию модели под тестовый прогон. Возвращает {data, include, steps, model_start, hist_rates, notes}."""
    src_data = os.path.abspath(src_data)
    src_dir = os.path.dirname(src_data)
    workdir = os.path.abspath(workdir)
    if os.path.normcase(workdir) == os.path.normcase(src_dir):
        raise CaseError('рабочая папка не может совпадать с папкой модели: оригинал менять нельзя')
    text, enc = _read(src_data)
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = [ln.rstrip('\r') for ln in text.split('\n')]
    m_start = model_start(text)
    sched, end = _split_sections(lines)
    head, body, tail = lines[:sched + 1], lines[sched + 1:end], lines[end:]
    notes: List[str] = []

    # --- до SCHEDULE: пути include абсолютные, SUMMARY - свой ---
    wells = list(wells) if wells else list(regimes)
    for i, j, nm in include_records(head):
        head[j] = _rewrite_include(head[j], _abs(nm, src_dir))
    head_text = rr.set_summary(nl.join(head), rr.summary_block(wells))

    # --- SCHEDULE: include по порядку до файла с датой ГДИ ---
    recs = include_records(body)
    inline_dates = [k for k, ln in enumerate(body) if _clean(ln).upper() == 'DATES']
    if inline_dates:
        raise CaseError('в секции SCHEDULE файла .data есть DATES вне include: такое расписание пока не поддерживается')
    if not recs:
        raise CaseError('в секции SCHEDULE нет INCLUDE: расписание прямо в .data пока не поддерживается')
    prior: List[str] = []
    kept: List[Tuple[int, int, str]] = []
    cut = None
    for i, j, nm in recs:
        path = _abs(nm, src_dir)
        if not os.path.isfile(path):
            raise CaseError(f'нет файла расписания «{path}»')
        t, e = _read(path)
        lns = [ln.rstrip('\r') for ln in t.split('\n')]
        if any(d >= start for b in scan_dates(lns) for _, d in b['items']):
            cut = (i, j, nm, t, e)
            break
        kept.append((i, j, nm))
        prior += lns
    if cut is None:
        raise CaseError(f'в расписании нет дат не раньше {start:%d.%m.%Y}: на дату ГДИ модель не считана')
    i, j, nm, t, e = cut
    inc_name = f'sch_{name}.inc'
    prior_text = nl.join(prior)
    sched_text, steps, rep = rr.build_test_schedule(t, start, regimes, mults, step_days, extra_lines, prior_text=prior_text)
    os.makedirs(workdir, exist_ok=True)
    with open(os.path.join(workdir, inc_name), 'w', encoding=e if e != 'utf-8-sig' else 'utf-8', newline='') as f:
        f.write(sched_text)
    new_body = body[:j + 1]
    for ii, jj, nn in kept:
        new_body[jj] = _rewrite_include(new_body[jj], _abs(nn, src_dir))
    new_body[j] = _rewrite_include(new_body[j], inc_name)
    data_name = os.path.basename(src_data)
    data_text = head_text + nl + nl.join(new_body + ['', 'END', ''])
    dest = os.path.join(workdir, data_name)
    with open(dest, 'w', encoding=enc if enc != 'utf-8-sig' else 'utf-8', newline='') as f:
        f.write(data_text)
    if len(recs) > len(kept) + 1:
        notes.append(f'include после даты ГДИ ({len(recs) - len(kept) - 1} шт.) в копию не включены')
    return {'data': dest, 'include': os.path.join(workdir, inc_name), 'steps': steps, 'model_start': m_start,
            'hist_rates': rep['hist_rates'], 'notes': notes}


def available_wells(src_data: str, start: datetime, wells: Sequence[str]) -> Dict[str, float]:
    """Скважины, у которых к дате ГДИ в расписании модели есть дебит истории (WCONHIST GRAT): {скважина: дебит}. Остальных
    (ещё не пробурены или задаются иначе) тестовый прогон на эту дату собрать не может."""
    src_data = os.path.abspath(src_data)
    src_dir = os.path.dirname(src_data)
    text, _ = _read(src_data)
    lines = text.replace(chr(13), '').split(chr(10))
    sched, end = _split_sections(lines)
    prior: List[str] = []
    for _i, _j, nm in include_records(lines[sched + 1:end]):
        path = _abs(nm, src_dir)
        if not os.path.isfile(path):
            raise CaseError('нет файла расписания «%s»' % path)
        t, _e = _read(path)
        lns = t.replace(chr(13), '').split(chr(10))
        if any(d >= start for b in scan_dates(lns) for _, d in b['items']):
            prior += rr.cut_schedule(t, start)
            break
        prior += lns
    return rr.last_hist_gas_rates(prior, list(wells))


def ensure_results(src_dir: str, workdir: str, progress: Optional[Callable[[int, int], None]] = None, min_free_gb: float = 20.0) -> str:
    """Копия папки RESULTS (restart-файлы модели) в workdir; уже есть - не копируется. Нужен запас свободного места."""
    src = os.path.join(src_dir, 'RESULTS')
    dst = os.path.join(workdir, 'RESULTS')
    if os.path.isdir(dst):
        return dst
    if not os.path.isdir(src):
        raise CaseError(f'нет папки результатов модели «{src}»: рестарт невозможен')
    files = [os.path.join(r, f) for r, _, fs in os.walk(src) for f in fs]
    total = sum(os.path.getsize(f) for f in files)
    os.makedirs(workdir, exist_ok=True)
    free = shutil.disk_usage(workdir).free
    if free < total + min_free_gb * 2 ** 30:
        raise CaseError(f'мало места: для копии RESULTS нужно {total / 2**30:.0f} ГБ и запас {min_free_gb:g} ГБ, свободно {free / 2**30:.0f} ГБ')
    done = 0
    for f in files:
        d = os.path.join(dst, os.path.relpath(f, src))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(f, d)
        done += os.path.getsize(f)
        if progress:
            progress(done, total)
    return dst


def restart_step_from_times(times: Sequence[float], t: float) -> int:
    """Номер шага рестарта для отчётного времени t (дни от START): индекс t в списке времён отчёта (с нуля, строка t=0 - шаг 0)."""
    ts = list(times)
    if t in ts:
        return ts.index(t)
    before = [k for k, x in enumerate(ts) if x <= t]
    if not before:
        raise CaseError('время расчёта раньше первого шага')
    return before[-1]


_LOG_STEP = re.compile(r'(?:ОТЧ[ЕЁ]Т N|FINISH REPORT N)\s+(\d+)\s+(?:ДЕНЬ|FOR DAY)\s+([0-9.]+)')


def steps_from_job_log(path: str) -> List[Tuple[int, float]]:
    """Шаги отчёта и время (дни от START) из журнала расчёта модели (<имя>.job.log в RESULTS; русская и английская версии tNavigator)."""
    out: List[Tuple[int, float]] = []
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8', 'cp1251'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            text = ''
    for m in _LOG_STEP.finditer(text or raw.decode('latin-1')):
        out.append((int(m.group(1)), float(m.group(2))))
    return out


def restart_step_from_log(steps: Sequence[Tuple[int, float]], t: float) -> int:
    """Наибольший номер шага отчёта, время которого не позже t (состояние модели на начало даты ГДИ); tNavigator сам откатится
    к ближайшему шагу, с которого возможен рестарт."""
    before = [n for n, d in steps if d <= t]
    if not before:
        raise CaseError('в журнале расчёта нет шага не позже даты ГДИ')
    return max(before)
