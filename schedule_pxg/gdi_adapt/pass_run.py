"""Один прогон на много дат ГДИ: расписание с тестовыми блоками на каждой дате.

Зачем. Результаты модели посчитаны только до некоторой даты (у вас до 28.10.2022), а ГДИ есть и позже. Рестарт с шагов, созданных
уже самим прогоном-продолжением, tNavigator 21.3 не читает (падает с access violation), поэтому для дат после последнего шага
каждый раз считать «рестарт на дату» нельзя. Вместо этого модель один раз проходит от последнего шага до самой поздней даты, а на каждой
дате ГДИ в расписание вставляются свои мульты и дебиты режимов исследования. Скважины независимы (одно исследование на скважину),
поэтому режимы разных дат не мешают друг другу. После режимов дебит скважины возвращается к тому, что стоит в расписании на эту дату.

Расписание разбирается на секции «дата - строки до следующей даты»; наши строки добавляются в КОНЕЦ секции даты (после исходных ключевых
слов), поэтому режим ГДИ перекрывает исходный WCONHIST той же даты, а возврат истории учитывает все исходные изменения до него.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from .data_patch import MARK, _clean, _keywords, scan_dates, strip_marked
from .regime_run import RegimeStep, _fmt, last_hist_gas_rates


def split_sections(lines: Sequence[str]) -> Tuple[List[str], List[List]]:
    """(строки до первой даты, [[дата, строки секции]]). Блок DATES с несколькими датами превращается в отдельные секции."""
    blocks = scan_dates(list(lines))
    if not blocks:
        return list(lines), []
    pre = list(lines[:blocks[0]['start']])
    sections: List[List] = []
    for bi, b in enumerate(blocks):
        nxt_start = blocks[bi + 1]['start'] if bi + 1 < len(blocks) else len(lines)
        for idx, (_i, d) in enumerate(b['items']):
            last = idx == len(b['items']) - 1
            sections.append([d, list(lines[b['end'] + 1:nxt_start]) if last else []])
    return pre, sections


def join_sections(pre: Sequence[str], sections: Sequence[List]) -> List[str]:
    out = list(pre)
    for d, body in sections:
        out += ['DATES', '%s\t/' % _fmt(d), '/'] + list(body)
    return out


def build_pass_schedule(text: str, prior_text: str, studies: Sequence[dict], mults: Optional[Dict[Tuple[str, str], tuple]] = None,
                        step_days: int = 1, final: bool = True) -> Tuple[str, List[RegimeStep], dict]:
    """studies: [{'well', 'date' (datetime), 'q': [дебиты режимов, ст. м³/сут]}]; mults: {(скважина, 'ГГГГ-ММ-ДД'): (приращение, D|None)}.
    Возвращает (текст расписания, шаги режимов, отчёт {'skipped': {скважина: причина}, 'last': последняя дата})."""
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = [ln.rstrip('\r') for ln in strip_marked(text.split('\n'))]
    pre, sections = split_sections(lines)
    if not studies:
        raise ValueError('нет исследований для сквозного прогона')
    last = max(s['date'] + timedelta(days=(len(s['q']) + 1) * step_days) for s in studies)
    if final:
        sections = [sec for sec in sections if sec[0] <= last]             # всё после последней нужной даты отбрасывается

    # дебит истории, действующий на каждую дату (по исходным секциям до неё включительно)
    wells = sorted({s['well'] for s in studies})
    rates = last_hist_gas_rates(prior_text.splitlines() + pre, wells)
    rate_at: Dict[datetime, Dict[str, float]] = {}
    for d, body in sections:
        rates = dict(rates, **last_hist_gas_rates(body, wells))
        rate_at[d] = dict(rates)

    def rates_at(date: datetime) -> Dict[str, float]:
        cur = {}
        for d in sorted(rate_at):
            if d <= date:
                cur = rate_at[d]
            else:
                break
        return cur or last_hist_gas_rates(prior_text.splitlines() + pre, wells)

    add: Dict[datetime, List[str]] = {}
    steps: List[RegimeStep] = []
    skipped: Dict[str, str] = {}
    mults = mults or {}
    for s in sorted(studies, key=lambda x: (x['date'], x['well'])):
        w, d, qs = s['well'], s['date'], s['q']
        end = d + timedelta(days=len(qs) * step_days)
        hist = rates_at(end).get(w)
        if hist is None:
            skipped[w] = 'нет дебита истории (WCONHIST GRAT) в расписании до даты ГДИ'
            continue
        m = mults.get((w, d.strftime('%Y-%m-%d')))
        if m:
            add.setdefault(d, []).extend(_keywords(d, [(w, m[0], m[1])], False)[1:-2])        # без маркеров: свои ниже
        for k, q in enumerate(qs):
            day = d + timedelta(days=k * step_days)
            add.setdefault(day, []).extend(['WCONHIST', '%s\tOPEN\tGRAT\t1*\t1*\t%.1f\t1*\t/' % (w, q), '/'])
            steps.append(RegimeStep(w, k, float(q), day + timedelta(days=step_days)))
        add.setdefault(end, []).extend(['WCONHIST', '%s\tOPEN\tGRAT\t1*\t1*\t%.1f\t1*\t/' % (w, hist), '/'])
    # вставка в конец секции своей даты; новые даты создаются в нужном порядке
    by_date = {sec[0]: sec for sec in sections}
    for day, extra in sorted(add.items()):
        if day in by_date:
            by_date[day][1] = by_date[day][1] + [MARK + ' (начало) сквозной прогон по режимам ГДИ'] + extra + [MARK + ' (конец) сквозной прогон по режимам ГДИ']
        else:
            sec = [day, [MARK + ' (начало) сквозной прогон по режимам ГДИ'] + extra + [MARK + ' (конец) сквозной прогон по режимам ГДИ']]
            sections.append(sec)
            by_date[day] = sec
    sections.sort(key=lambda sec: sec[0])
    # конец расчёта: последняя дата должна быть в расписании, чтобы записался последний режим
    if final and last not in by_date:
        sections.append([last, []])
        sections.sort(key=lambda sec: sec[0])
    return nl.join(join_sections(pre, sections)) + nl, steps, {'skipped': skipped, 'last': last}
