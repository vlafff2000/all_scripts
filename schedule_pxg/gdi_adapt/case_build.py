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
from .outputs import MONTHS

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


def _include_name(line: str) -> str:
    """Имя файла из строки INCLUDE: в кавычках (внутри могут быть «/», например 'inc/sch.inc' /) или без кавычек до завершающего « /»."""
    m = re.match(r"""^\s*(['"])(.*?)\1""", line)
    if m:
        return m.group(2)
    return re.split(r'\s+/|/\s*$', line.strip(), maxsplit=1)[0].strip()


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
                out.append((i, j, _include_name(_clean(lines[j]))))
                i = j
        i += 1
    return out


def _find_ci(base: str, parts: List[str]) -> Optional[str]:
    """Путь base/parts, где каждая часть ищется без учёта регистра (РЕД ОС: файловая система чувствительна к регистру, а include в .data
    писали на Windows: «Schedule\\SCH.inc» при файле schedule/sch.inc)."""
    cur = base
    for part in parts:
        if part in ('', '.'):
            continue
        if part == '..':
            cur = os.path.dirname(cur)
            continue
        direct = os.path.join(cur, part)
        if os.path.exists(direct):
            cur = direct
            continue
        try:
            hit = [n for n in os.listdir(cur) if n.casefold() == part.casefold()]
        except OSError:
            return None
        if len(hit) != 1:
            return None
        cur = os.path.join(cur, hit[0])
    return cur


def _abs(name: str, src_dir: str) -> str:
    """Полный путь include из .data. Обратные косые (Windows) приводятся к прямым; если точного файла нет, имена сверяются с диском без учёта регистра."""
    norm = name.strip().strip("'\"").replace('\\', '/')
    if os.path.isabs(norm) or re.match(r'^[A-Za-z]:/', norm):
        return norm if re.match(r'^[A-Za-z]:/', norm) else os.path.abspath(norm).replace('\\', '/')
    p = os.path.abspath(os.path.join(src_dir, norm))
    if not os.path.exists(p):
        hit = _find_ci(os.path.abspath(src_dir), norm.split('/'))
        if hit:
            p = os.path.abspath(hit)
    return p.replace('\\', '/')


def abs_includes(lines: Sequence[str], orig_dir: str) -> List[str]:
    """Копия строк include-файла, где вложенные INCLUDE заменены абсолютными путями от папки ИСХОДНОГО файла. Рабочая копия лежит в другой
    папке, а tNavigator ищет относительные пути от папки файла, в котором они записаны: без этого вложенные файлы искались бы в рабочей папке
    (завершение с кодом 1). Сами вложенные файлы не копируются: читаются из оригинала."""
    out = list(lines)
    for _i, j, nm in include_records(out):
        out[j] = _rewrite_include(out[j], _abs(nm, orig_dir))
    return out


def _rewrite_include(line: str, new_name: str) -> str:
    return f"'{new_name}' /"


def _split_sections(lines: List[str]) -> Tuple[int, int]:
    """Индекс строки SCHEDULE и конца секции (строка END или конец файла)."""
    sched = next((i for i, ln in enumerate(lines) if _clean(ln).upper() == 'SCHEDULE'), None)
    if sched is None:
        raise CaseError('в .data нет секции SCHEDULE')
    end = next((i for i in range(len(lines) - 1, sched, -1) if _clean(lines[i]).upper() == 'END'), len(lines))
    return sched, end


_RU_MONTHS = {'ЯНВ': 1, 'ФЕВ': 2, 'МАР': 3, 'АПР': 4, 'МАЙ': 5, 'ИЮН': 6, 'ИЮЛ': 7, 'АВГ': 8, 'СЕН': 9, 'ОКТ': 10, 'НОЯ': 11, 'ДЕК': 12,
              'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6, 'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
_REPORT_DATE = re.compile(r'(?:ОТЧ[ЕЁ]Т N|FINISH REPORT N)\s+\d+\s+(?:ДЕНЬ|FOR DAY)\s+[0-9.]+\s+(?:ДАТА|ON)\s+(\d{1,2})\s+([A-Za-zА-Яа-я]{3})\w*\s+(\d{4})')


def report_dates(path: str) -> List[datetime]:
    """Даты всех отчётных шагов расчёта модели (result.log): tNavigator сам вставляет шаги между DATES, и номера шагов рестарта
    считаются вместе с ними."""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError:
        return []
    text = raw.decode('utf-8', 'replace')
    out: List[datetime] = []
    for m in _REPORT_DATE.finditer(text):
        mon = _RU_MONTHS.get(m.group(2).upper())
        if mon:
            try:
                out.append(datetime(int(m.group(3)), mon, int(m.group(1))))
            except ValueError:
                pass
    return out


def add_report_dates(files: Sequence[List[str]], extra: Sequence[datetime]) -> Tuple[List[List[str]], int]:
    """Вставляет в расписание (список файлов по порядку, строки) записи DATES на даты отчётных шагов, которых там нет, перед первой
    более поздней датой. Файлы без вставок возвращаются тем же объектом. Возвращает (файлы, число вставок)."""
    files = [list(f) for f in files]
    items = []
    for fi, lines in enumerate(files):
        for b in scan_dates(lines):
            items += [(fi, i, d) for i, d in b['items']]
    have = {d for _, _, d in items}
    todo = sorted(d for d in set(extra) if d not in have)
    ins: Dict[Tuple[int, int], List[datetime]] = {}
    n = 0
    for d in todo:
        nxt = next(((fi, i) for fi, i, x in items if x > d), None)
        if nxt is None or not any(x < d for _, _, x in items):
            continue                                                  # до первой или после последней даты расписания - не трогаем
        ins.setdefault(nxt, []).append(d)
        n += 1
    for (fi, i), ds in sorted(ins.items(), key=lambda kv: (kv[0][0], -kv[0][1])):
        files[fi][i:i] = [f'{d.day:02d} {MONTHS[d.month - 1]} {d.year}\t/' for d in ds]
    return files, n


def build_case(src_data: str, workdir: str, start: datetime, regimes: Dict[str, Sequence[float]], mults: Optional[list] = None,
               wells: Optional[Sequence[str]] = None, name: str = 'T', step_days: int = 1, extra_lines: Sequence[str] = (), work_min: float = 0.0,
               rest_min: float = 30.0) -> dict:
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
    kept_files: List[Tuple[List[str], str]] = []
    cut = None
    for i, j, nm in recs:
        path = _abs(nm, src_dir)
        if not os.path.isfile(path):
            raise CaseError(f'нет файла расписания «{path}» (в .data записано «{nm}», папка модели «{src_dir}»): проверьте, что файл лежит рядом с моделью по этому пути, '
                            'а .data и include скопированы вместе; на РЕД ОС регистр букв в именах важен')
        t, e = _read(path)
        lns = [ln.rstrip('\r') for ln in t.split('\n')]
        if any(d >= start for b in scan_dates(lns) for _, d in b['items']):
            cut = (i, j, nm, t, e)
            break
        kept.append((i, j, nm))
        kept_files.append((lns, e))
        prior += lns
    if cut is None:
        raise CaseError(f'в расписании нет дат не раньше {start:%d.%m.%Y}: на дату ГДИ модель не считана')
    i, j, nm, t, e = cut
    # отчётные шаги, которые tNavigator добавил при расчёте оригинала: в рабочем расписании они нужны, иначе номера шагов расходятся
    # с картами рестарта оригинала («рестарт с шага N невозможен»)
    kept_names = {k: _abs(n, src_dir) for k, (_, _, n) in enumerate(kept)}
    base = os.path.splitext(os.path.basename(src_data))[0]
    extra = [d for d in report_dates(os.path.join(src_dir, 'RESULTS', base, 'result.log')) if d < start]
    if extra:
        cut_lines = [ln.rstrip('\r') for ln in t.split('\n')]
        patched, n_extra = add_report_dates([f for f, _ in kept_files] + [cut_lines], extra)
        if n_extra:
            os.makedirs(workdir, exist_ok=True)
            for k, (lns, enc_k) in enumerate(kept_files):
                if patched[k] != lns:
                    name_k = f'sch_k{k}.inc'
                    with open(os.path.join(workdir, name_k), 'w', encoding=enc_k if enc_k != 'utf-8-sig' else 'utf-8', newline='') as f:
                        f.write(nl.join(abs_includes(patched[k], os.path.dirname(_abs(kept[k][2], src_dir)))))
                    kept_names[k] = name_k
            t = nl.join(patched[-1])
            notes.append(f'в расписание добавлено отчётных шагов оригинала: {n_extra} (номера шагов рестарта совпадут с картами модели)')
    t = nl.join(abs_includes([ln.rstrip('\r') for ln in t.split('\n')], os.path.dirname(_abs(nm, src_dir))))   # вложенные include - абсолютными путями на оригинал
    inc_name = f'sch_{name}.inc'
    prior_text = nl.join(prior)
    sched_text, steps, rep = rr.build_test_schedule(t, start, regimes, mults, step_days, extra_lines, prior_text=prior_text,
                                                       work_min=work_min, rest_min=rest_min)
    os.makedirs(workdir, exist_ok=True)
    with open(os.path.join(workdir, inc_name), 'w', encoding=e if e != 'utf-8-sig' else 'utf-8', newline='') as f:
        f.write(sched_text)
    new_body = body[:j + 1]
    for k, (ii, jj, nn) in enumerate(kept):
        new_body[jj] = _rewrite_include(new_body[jj], kept_names[k])
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


def _link_dir(src: str, dst: str) -> str:
    """Ссылка dst -> src на папку: символическая (Linux, РЕД ОС), на Windows junction (mklink /J, права администратора не нужны).
    Возвращает 'ссылка' или 'копия' (копируется только если ссылку создать нельзя, например junction на сетевой диск)."""
    try:
        if os.name == 'nt':
            import subprocess
            r = subprocess.run(['cmd', '/c', 'mklink', '/J', dst, src], capture_output=True)
            if r.returncode != 0 or not os.path.isdir(dst):
                raise OSError(r.stderr.decode('cp866', 'replace') or 'mklink не удался')
        else:
            os.symlink(src, dst, target_is_directory=True)
        return 'ссылка'
    except OSError:
        shutil.copytree(src, dst)
        return 'копия'


def link_model_folders(src_dir: str, workdir: str, data_name: str = '') -> List[str]:
    """Папки модели (INCLUDE, GRID, PVT и т.п.) подключаются в рабочую папку ссылками на оригинал, а не копируются: tNavigator ищет
    относительные файлы рядом с рабочим .data, а читать их можно прямо из оригинала. RESULTS здесь не трогаем (ensure_results копирует
    только нужную модель). Уже существующие в workdir имена не перезаписываются. Возвращает записи о сделанном."""
    src_dir, workdir = os.path.abspath(src_dir), os.path.abspath(workdir)
    notes: List[str] = []
    os.makedirs(workdir, exist_ok=True)
    for name in sorted(os.listdir(src_dir)):
        full = os.path.join(src_dir, name)
        dst = os.path.join(workdir, name)
        if name.casefold() == 'results' or os.path.normcase(os.path.abspath(full)) == os.path.normcase(workdir):
            continue
        if os.path.lexists(dst) or not os.path.isdir(full):
            continue
        notes.append(f'{name}: {_link_dir(full, dst)}')
    return notes


def results_files(src_dir: str, base: str) -> List[str]:
    """Файлы результатов ТОЛЬКО модели base (имя .data без расширения): подпапка RESULTS/<base> и файлы RESULTS/<base>.* (журнал запуска).
    В RESULTS могут лежать результаты многих моделей, остальные не копируются. Имя подпапки сверяется без учёта регистра; если подпапки
    нет или подходит несколько - ошибка с перечнем найденного (какую брать, решает инженер: молча копировать всё нельзя)."""
    res = os.path.join(src_dir, 'RESULTS')
    subs = sorted(n for n in os.listdir(res) if os.path.isdir(os.path.join(res, n)))
    hit = [n for n in subs if n == base] or [n for n in subs if n.casefold() == base.casefold()]
    if not hit:
        raise CaseError(f'в RESULTS нет подпапки «{base}» (имя .data без расширения): рестарт невозможен. Найдены подпапки: '
                        f'{", ".join(subs) or "нет"}. Укажите .data, для которого модель была посчитана, или переименуйте подпапку.')
    if len(hit) > 1:
        raise CaseError(f'в RESULTS несколько подпапок, подходящих под «{base}» по имени: {", ".join(hit)}. Оставьте одну.')
    sub = os.path.join(res, hit[0])
    files = [os.path.join(r, f) for r, _, fs in os.walk(sub) for f in fs]
    pre = hit[0].casefold() + '.'
    files += [os.path.join(res, n) for n in sorted(os.listdir(res)) if os.path.isfile(os.path.join(res, n)) and n.casefold().startswith(pre)]
    return files


def ensure_results(src_dir: str, workdir: str, progress: Optional[Callable[[int, int], None]] = None, min_free_gb: float = 20.0,
                   data_name: str = '') -> str:
    """Копия результатов модели (restart-файлы) в workdir/RESULTS; уже есть - не копируется. Нужен запас свободного места.
    data_name - имя .data (с расширением или без): копируются только результаты этой модели, а не вся папка RESULTS."""
    src = os.path.join(src_dir, 'RESULTS')
    dst = os.path.join(workdir, 'RESULTS')
    if not os.path.isdir(src):
        if os.path.isdir(dst):
            return dst
        raise CaseError(f'нет папки результатов модели «{src}»: рестарт невозможен')
    base = os.path.splitext(os.path.basename(data_name))[0] if data_name else ''
    # копия уже есть - сверяем с оригиналом: её могли сделать, пока модель ещё считалась, тогда в ней нет поздних шагов рестарта
    files = results_files(src_dir, base) if base else [os.path.join(r, f) for r, _, fs in os.walk(src) for f in fs]
    todo = []
    for f in files:
        d = os.path.join(dst, os.path.relpath(f, src))
        if not os.path.exists(d) or os.path.getsize(d) != os.path.getsize(f):
            todo.append(f)
    if not todo:
        return dst
    total = sum(os.path.getsize(f) for f in todo)
    os.makedirs(workdir, exist_ok=True)
    free = shutil.disk_usage(workdir).free
    if free < total + min_free_gb * 2 ** 30:
        raise CaseError(f'мало места: для копии RESULTS нужно {total / 2**30:.0f} ГБ и запас {min_free_gb:g} ГБ, свободно {free / 2**30:.0f} ГБ')
    done = 0
    for f in todo:
        d = os.path.join(dst, os.path.relpath(f, src))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        part = d + '.part'                                  # под своим именем файл появляется только целым: обрыв не оставит «готовую» обрезанную копию
        try:
            shutil.copyfile(f, part)
            shutil.copystat(f, part)
            if os.path.getsize(part) != os.path.getsize(f):
                raise OSError(f'копия «{os.path.basename(f)}» неполная')
            os.replace(part, d)
        except BaseException:
            if os.path.exists(part):
                os.remove(part)
            raise
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


_META_DATE = re.compile(r'(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})[./](\d{1,2})[./](\d{4})')


def restart_steps_from_meta(path: str) -> List[Tuple[int, datetime]]:
    """Шаги, на которых tNavigator сохранил карты рестарта: секция [timesteps] файла RESULTS/<имя>/outsol_ts_maps.meta,
    записи «дата = номер шага» (в 21.3-22.3 карты пишутся не на каждом отчётном шаге, рестарт возможен только с них)."""
    with open(path, 'rb') as f:
        raw = f.read()
    text = ''
    for enc in ('utf-8', 'cp1251'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out: List[Tuple[int, datetime]] = []
    inside = False
    for ln in text.splitlines():
        t = ln.strip()
        if t.startswith('['):
            inside = t.lower().startswith('[timesteps')
            continue
        if not inside or '=' not in t:
            continue
        left, right = (x.strip() for x in t.split('=', 1))
        for date_s, step_s in ((left, right), (right, left)):
            m = _META_DATE.search(date_s)
            if m and step_s.split()[:1] and step_s.split()[0].isdigit():
                g = m.groups()
                try:
                    d = datetime(int(g[0]), int(g[1]), int(g[2])) if g[0] else datetime(int(g[5]), int(g[4]), int(g[3]))
                except ValueError:
                    break
                out.append((int(step_s.split()[0]), d))
                break
    return out


def restart_step_from_meta(steps: Sequence[Tuple[int, datetime]], when: datetime) -> int:
    """Наибольший сохранённый шаг рестарта, дата которого не позже начала даты ГДИ."""
    before = [n for n, d in steps if d <= when]
    if not before:
        raise CaseError('среди сохранённых карт рестарта нет шага не позже даты ГДИ')
    return max(before)


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
