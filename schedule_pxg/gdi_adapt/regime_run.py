"""Тестовый прогон модели под режимы ГДИ (этап 4 плана «Адаптация по ГДИ»).

Идея: в КОПИИ модели на дату ГДИ скважины по очереди задаются дебитами режимов исследования (WCONHIST GRAT, каждый режим -
отдельный шаг), после последнего режима возвращается дебит истории. Из BASE.RSM читаются забойное и пластовое давления на
конце каждого режима: депрессия модели Pпл - Pзаб сравнивается с депрессией ГДИ режим за режимом (в рабочей точке истории
модель с ГДИ сравнивать нельзя - дебиты разные). Оригинал модели не меняется: тут только текст расписания и разбор результатов.
Мульты (WPIMULT/WDFAC) вставляются на дату первого режима теми же блоками, что и в data_patch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import depression as dpm
from .data_patch import MARK, _clean, _keywords, scan_dates, strip_marked
from .gdi import fit_ab_dp2
from .outputs import MONTHS
from .physics import BETA
from .rsm import value_at
from .snapshot import WellSnapshot


def _fmt(d: datetime) -> str:
    return f'{d.day:02d} {MONTHS[d.month - 1]} {d.year}'


def cut_schedule(text: str, start: datetime) -> List[str]:
    """Строки расписания до первой даты >= start (сама дата и всё после отбрасываются). Блоки DATES целиком сохраняются."""
    lines = [ln.rstrip('\r') for ln in strip_marked(text.split('\n'))]
    for b in scan_dates(lines):
        for idx, (i, d) in enumerate(b['items']):
            if d >= start:
                if idx == 0:
                    return lines[:b['start']]
                return lines[:i] + ['/']               # дата в середине блока: закрываем блок перед ней
    return lines


_BLOCKS = ('WCONHIST', 'WCONPROD', 'DATES', 'WELSPECS', 'COMPDAT', 'COMPDATMD', 'WPIMULT', 'WDFAC', 'WEFAC', 'GCONPROD')


def last_hist_gas_rates(lines: Sequence[str], wells: Sequence[str]) -> Dict[str, float]:
    """Последний дебит газа истории скважины в расписании (WCONHIST ... GRAT, 6-е поле), ст. м³/сут."""
    out: Dict[str, float] = {}
    block = None
    for raw in lines:
        s = _clean(raw)
        if not s:
            continue
        if s.upper() in _BLOCKS:
            block = s.upper()
            continue
        if s == '/':
            block = None
            continue
        if block == 'WCONHIST':
            toks = s.replace('/', ' ').split()
            w = toks[0].strip("'\"")
            if w in wells and len(toks) >= 6 and toks[2].strip("'\"").upper() == 'GRAT':
                try:
                    out[w] = float(toks[5])
                except ValueError:
                    pass
    return out


@dataclass
class RegimeStep:
    well: str
    k: int                       # номер режима, с 0
    q: float                     # дебит газа, ст. м³/сут
    end: datetime                # конец режима (на этой дате читаются давления)


def build_test_schedule(text: str, start: datetime, regimes: Dict[str, Sequence[float]], mults: Optional[list] = None,
                        step_days: int = 1, extra_lines: Sequence[str] = (), prior_text: str = '', work_min: float = 0.0,
                        rest_min: float = 30.0, nextstep: float = 0.005) -> Tuple[str, List[RegimeStep], dict]:
    """Расписание тестового прогона. regimes: {скважина: [дебиты режимов, ст. м³/сут]}; mults: [(скважина, приращение WPIMULT, D|None)]
    на дату start; extra_lines - дополнительные ключевые слова на дату start (например COMPDAT для проверки смены интервала).
    Возвращает (текст, шаги режимов, отчёт). Режим k скважины идёт с start+k*step_days по start+(k+1)*step_days;
    после последнего режима скважины ставится её дебит истории.
    work_min > 0 - режимы как при реальном ГДИ: work_min минут работы на дебите режима (WCONHIST), затем rest_min минут остановки
    (WELOPEN SHUT), следующий режим; интервалы задаются TSTEP (дни, дробные), давления читаются на конце работы режима.
    После последнего режима у всех скважин возвращается история."""
    nl = '\r\n' if '\r\n' in text else '\n'
    base = cut_schedule(text, start)
    wells = list(regimes)
    hist = last_hist_gas_rates(prior_text.splitlines() + base, wells)       # prior_text - расписание из предыдущих include
    miss = [w for w in wells if w not in hist]
    if miss:
        raise ValueError('нет дебита истории (WCONHIST GRAT) в расписании до даты ГДИ у скважин: ' + ', '.join(miss))
    kmax = max(len(q) for q in regimes.values())
    out = list(base) + [MARK + ' (начало) тестовый прогон по режимам ГДИ', 'DATES', f'{_fmt(start)}\t/', '/']
    if mults:
        out += _keywords(start, mults, False)
    out += list(extra_lines)
    steps: List[RegimeStep] = []
    if work_min > 0:
        work_d, rest_d = f'{work_min / 1440.0:.7f}', f'{rest_min / 1440.0:.7f}'
        for k in range(kmax):
            t_end = start + timedelta(minutes=k * (work_min + rest_min) + work_min)
            rows = []
            for w in wells:
                if k < len(regimes[w]):
                    rows.append(f'{w}\tOPEN\tGRAT\t1*\t1*\t{regimes[w][k]:.1f}\t1*\t/')
                    steps.append(RegimeStep(w, k, float(regimes[w][k]), t_end))
            out += ['WCONHIST'] + rows + ['/']
            if nextstep:
                out += ['NEXTSTEP', f'{nextstep:g} /']
            out += ['TSTEP', f'{work_d} /']
            shut = [w for w in wells if k < len(regimes[w])]
            if k < kmax - 1:
                out += ['WELOPEN'] + [f'{w}\tSHUT\t/' for w in shut] + ['/', 'TSTEP', f'{rest_d} /']
            else:
                out += ['WELOPEN'] + [f'{w}\tSHUT\t/' for w in shut] + ['/']
        out += ['WCONHIST'] + [f'{w}\tOPEN\tGRAT\t1*\t1*\t{hist[w]:.1f}\t1*\t/' for w in wells] + ['/']
        total_d = ((kmax - 1) * (work_min + rest_min) + work_min) / 1440.0
        out += ['DATES', f'{_fmt(start + timedelta(days=int(total_d) + 1))}\t/', '/', MARK + ' (конец) тестовый прогон по режимам ГДИ', '']
        return nl.join(out), steps, {'hist_rates': hist, 'n_steps': len(steps), 'start': start}
    for k in range(kmax + 1):
        d = start + timedelta(days=k * step_days)
        if k > 0:
            out += ['DATES', f'{_fmt(d)}\t/', '/']
        rows = []
        for w in wells:
            qs = regimes[w]
            if k < len(qs):
                rows.append(f'{w}\tOPEN\tGRAT\t1*\t1*\t{qs[k]:.1f}\t1*\t/')
                steps.append(RegimeStep(w, k, float(qs[k]), d + timedelta(days=step_days)))
            elif k == len(qs):                          # режимы кончились: возвращаем историю
                rows.append(f'{w}\tOPEN\tGRAT\t1*\t1*\t{hist[w]:.1f}\t1*\t/')
        if rows:
            out += ['WCONHIST'] + rows + ['/']
    out += ['DATES', f'{_fmt(start + timedelta(days=(kmax + 1) * step_days))}\t/', '/',
            MARK + ' (конец) тестовый прогон по режимам ГДИ', '']
    return nl.join(out), steps, {'hist_rates': hist, 'n_steps': len(steps), 'start': start}


def replace_include(data_text: str, old_name: str, new_name: str) -> str:
    """В тексте .data заменяет имя INCLUDE-файла (без учёта регистра); не найдено - ошибка (копия не должна молча остаться прежней)."""
    new, n = re.subn(re.escape(old_name), lambda m: new_name, data_text, flags=re.I)
    if not n:
        raise ValueError(f'в .data нет include «{old_name}»')
    return new


def set_summary(data_text: str, summary_text: str) -> str:
    """Заменяет все секции SUMMARY (между первой SUMMARY и SCHEDULE) одной своей: тестовому прогону нужны только давления и
    параметры притока. Меньше векторов - меньше RSM и быстрее прогон."""
    m = re.search(r'^\s*SUMMARY\b', data_text, re.M)
    e = re.search(r'^\s*SCHEDULE\b', data_text, re.M)
    if not (m and e and m.start() < e.start()):
        raise ValueError('в .data не найдены секции SUMMARY и SCHEDULE')
    return data_text[:m.start()] + summary_text.rstrip('\n') + '\n\n' + data_text[e.start():]


def summary_block(wells: Sequence[str], well_vectors: Sequence[str] = ('WBHP', 'WBP', 'WBP9', 'WGPR'),
                  conn_vectors: Sequence[str] = ('CTFAC', 'CEKH', 'CDFAC', 'CDRD', 'CGPR', 'CPR')) -> str:
    """SUMMARY: скважинные векторы списком имён, соединения - по записи на скважину («'W' /»: все соединения скважины).
    Список имён в одной записи tNavigator читает как «скважина i j k» и выдаёт соединения только первой скважины
    (так в диагностике этапа 0 пропали соединения скв. 2-3)."""
    names = ' '.join(f"'{w}'" for w in wells)
    out = ['SUMMARY']
    for v in well_vectors:
        out += [v, f'{names} /']
    for v in conn_vectors:
        out += [v] + [f"'{w}' /" for w in wells] + ['/']
    return '\n'.join(out)


# ---------- результаты ----------
def snapshot_from_rsm(series: dict, well: str, t: float, t_name: str = '') -> WellSnapshot:
    """Снимок скважины на отчётном шаге t из рядов RSM (как данные калькулятора графиков в комплекте).
    cbp - CPR (или CDRD + WBHP, если CPR нет); cdiam = 1 и cefr = exp(ln(re/rw)+skin)/2, где ln(re/rw)+skin = 2πβ·CEKH/CTFAC
    (так проводимость и знаменатель притока восстанавливаются точно)."""
    conns = sorted({k[2] for k in series if k[0] == 'CEKH' and k[1] == well and len(k) == 3})
    if not conns:
        raise ValueError(f'в RSM нет соединений скважины {well} (CEKH): добавьте векторы соединений в SUMMARY')

    def val(key):
        # дробные сутки (шаги ГДИ): RSM округляет время вниз, нужно окно (см. _value_near)
        return value_at(series[key], t) if t == int(t) else _value_near(series[key], t, 0.0125)

    def get(v, c):
        return val((v, well, c))
    wbhp = val(('WBHP', well))
    rows = []
    for c in conns:
        cgpr, cdrd, cekh, ctfac, cdfac = get('CGPR', c), get('CDRD', c), get('CEKH', c), get('CTFAC', c), get('CDFAC', c)
        cbp = get('CPR', c) if ('CPR', well, c) in series else cdrd + wbhp
        if cgpr > 0 and cekh > 0 and ctfac > 0:
            rows.append((cbp, cdrd, cgpr, cdfac, cekh, ctfac))
    if not rows:
        raise ValueError(f'скважина {well}: на шаге {t:g} нет работающих соединений')
    a = np.array(rows, float)
    denum = 2.0 * BETA * np.pi * a[:, 4] / a[:, 5]
    name = t_name or f'{t:g}'
    return WellSnapshot(wname=well, t_name=name, t_requested=name, substituted=False,
                        cbp=a[:, 0], cdrd=a[:, 1], cgpr=a[:, 2], cdfac=a[:, 3], cekh=a[:, 4],
                        cdiam=np.ones(len(a)), cefr=np.exp(denum) / 2.0, ctfac=a[:, 5],
                        wbp=val(('WBP', well)), wgpr=val(('WGPR', well)), wbhp=wbhp)


def snapshot_with_fallback(series: dict, well: str, t0: float, later: Sequence[float]) -> WellSnapshot:
    """Снимок на старте даты ГДИ; если на t0 скважина не добывает (закачка/остановка до записи даты ГДИ), - на концах режимов
    (скважина уже работает на дебите режима). Бросает ValueError, если нигде нет работающих соединений."""
    err = None
    for t in [t0] + [x for x in later if x == x]:
        try:
            snap = snapshot_from_rsm(series, well, float(t))
            if t != t0:
                snap.substituted = True
            return snap
        except ValueError as e:
            err = err or e
    raise err


def _value_near(series, t: float, tol: float) -> float:
    """Значение на отчётном шаге, ближайшем к t (дни от START), если он не дальше tol; иначе NaN.
    Дробное время RSM печатает с двумя знаками и ОКРУГЛЯЕТ ВНИЗ (17488.2292 -> 17488.22), поэтому для дробных суток окно
    несимметрично: строка может быть ниже ожидаемого времени до 0.0125 сут и выше не более чем на 0.0025 сут."""
    ts, vs = series
    ts = np.asarray(ts, float)
    if len(ts) == 0:
        return float('nan')
    if tol <= 1e-6:
        j = int(np.argmin(np.abs(ts - t)))
        return float(vs[j]) if abs(ts[j] - t) <= tol else float('nan')
    d = t - ts                                            # > 0: строка раньше ожидаемого времени
    ok = np.where((d >= -0.0025) & (d <= 0.0125))[0]
    if not len(ok):
        return float('nan')
    j = int(ok[np.argmin(np.abs(d[ok]))])
    return float(vs[j])


def model_regimes(series: dict, steps: Sequence[RegimeStep], model_start: datetime) -> Dict[str, List[dict]]:
    """По режимам: {скважина: [{k, q, t, wbhp, wbp, dep}]}; dep = Pпл - Pзаб модели на конце режима, бар (давления абсолютные)."""
    out: Dict[str, List[dict]] = {}
    for st in steps:
        t = (st.end - model_start).total_seconds() / 86400.0
        # дробные сутки (TSTEP): RSM пишет время с двумя знаками, округляя вниз; шаги 1 ч и 30 мин отстоят не менее чем на 0.02 сут
        tol = 1e-6 if t == int(t) else 0.0125
        bhp = _value_near(series[('WBHP', st.well)], t, tol)
        bp = _value_near(series[('WBP', st.well)], t, tol)
        out.setdefault(st.well, []).append({'k': st.k, 'q': st.q, 't': t, 'wbhp': bhp, 'wbp': bp, 'dep': bp - bhp})
    return out


def compare_with_gdi(model_rows: List[dict], p_res_gdi, bhp_gdi, ab_q_units: str = '10^3 m3/day') -> dict:
    """Депрессия модели против ГДИ по режимам (порядок режимов тот же): ошибки мер regimes и dp2, разрыв Pпл, A и B модели
    по её собственной кривой dP²(Q)."""
    dep_m = np.array([r['dep'] for r in model_rows], float)
    dep_g = np.asarray(p_res_gdi, float) - np.asarray(bhp_gdi, float)
    wbp = np.array([r['wbp'] for r in model_rows], float)
    wbhp = np.array([r['wbhp'] for r in model_rows], float)
    dp2_m = wbp ** 2 - wbhp ** 2
    dp2_g = np.asarray(p_res_gdi, float) ** 2 - np.asarray(bhp_gdi, float) ** 2
    q_m = np.array([r['q'] for r in model_rows], float)
    a_m, b_m = fit_ab_dp2(q_m, dp2_m, ab_q_units, nonneg_b=True) if len(q_m) >= 2 else (float('nan'), float('nan'))
    return {'dep_model': dep_m, 'dep_gdi': dep_g, 'dp2_model': dp2_m, 'dp2_gdi': dp2_g,
            'err_dep_pct': dpm.rel_err_pct(dep_m, dep_g), 'err_dp2_pct': dpm.rel_err_pct(dp2_m, dp2_g),
            'p_res_gap': dpm.p_res_gap(float(np.nanmean(wbp)) if np.isfinite(wbp).any() else float('nan'), p_res_gdi), 'a_model': a_m, 'b_model': b_m}
