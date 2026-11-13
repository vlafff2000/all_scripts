"""База отсчёта мультов (WPIMULT, D-фактор) и журнал итераций адаптации по ГДИ.

В модели WPIMULT накопительный (×2 затем ×2 = ×4). Результат адаптации pi_mult зависит от того, что было в снимке:
  state='base'    снимок снят с модели без наших мультов -> pi_mult = итог от базовой модели, в include идёт приращение;
  state='current' снимок уже содержит стоящие мульты      -> pi_mult = поправка к текущему состоянию = приращение.
Журнал хранит приращения по скважине и датам; итог = произведение действующих записей. Откат не стирает историю.
Авто-значение - подсказка: override() заменяет его ручным, причина остаётся в журнале.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

_MONTHS = {m: i + 1 for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'])}


def parse_mults(text: str) -> List[dict]:
    """Читает WPIMULT/WDFAC из текста .data/.inc: [{wname, date, pimult, dfac}] в порядке файла.
    Маски имён (со *) пропускаются: журнал ведётся по конкретным скважинам."""
    out, date, block = [], None, None
    for raw in text.splitlines():
        line = raw.split('--')[0].strip()
        if not line:
            continue
        up = line.upper()
        if up in ('DATES', 'WPIMULT', 'WDFAC'):
            block = up
            continue
        if line == '/':
            if block in ('WPIMULT', 'WDFAC', 'DATES'):
                block = None
            continue
        toks = line.replace('/', ' ').split()
        if block == 'DATES' and len(toks) >= 3 and toks[1].upper()[:3] in _MONTHS:
            date = datetime(int(toks[2]), _MONTHS[toks[1].upper()[:3]], int(toks[0]))   # в блоке может быть несколько дат: до '/' берём последнюю
        elif block in ('WPIMULT', 'WDFAC') and len(toks) >= 2 and '*' not in toks[0] and '?' not in toks[0]:
            try:
                v = float(toks[1].replace('D', 'E'))
            except ValueError:
                continue
            out.append({'wname': toks[0].strip("'\""), 'date': date, 'pimult': v if block == 'WPIMULT' else None,
                        'dfac': v if block == 'WDFAC' else None})
    return out


def _iso(d) -> str:
    return d.strftime('%Y-%m-%d') if d is not None else ''


class MultJournal:
    def __init__(self, path: str = ''):
        self.path = path
        self.data: Dict[str, List[dict]] = {}
        if path and os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                self.data = json.load(f)

    def _save(self):
        if self.path:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)

    def entries(self, wname: str) -> List[dict]:
        return self.data.get(wname, [])

    def active(self, wname: str, before: Optional[str] = None) -> List[dict]:
        return [e for e in self.entries(wname) if e['active'] and (before is None or e['date'] < before)]

    def total(self, wname: str) -> float:
        t = 1.0
        for e in self.active(wname):
            t *= e['increment']
        return t

    def _append(self, wname, date, increment, dfac, source, state, note) -> dict:
        lst = self.data.setdefault(wname, [])
        e = {'iter': len(lst) + 1, 'date': _iso(date), 'increment': float(increment), 'dfac': dfac, 'source': source,
             'state': state, 'note': note, 'active': True, 'at': datetime.now().isoformat(timespec='seconds')}
        lst.append(e)
        e['total'] = self.total(wname)
        return e

    def add(self, r, state: str = 'current', note: str = '') -> float:
        """Записывает итерацию по результату адаптации r (wname, date, pi_mult, d). Возвращает приращение для include."""
        if state not in ('base', 'current'):
            raise ValueError(f'state={state!r}')
        w, iso = r.wname, _iso(r.date)
        if state == 'base':
            for e in self.entries(w):               # новый итог от базовой заменяет записи этой даты и позже
                if e['active'] and e['date'] >= iso:
                    e['active'] = False
            prev = 1.0
            for e in self.active(w, before=iso):
                prev *= e['increment']
            inc = r.pi_mult / prev if prev else r.pi_mult
        else:
            inc = r.pi_mult
        self._append(w, r.date, inc, r.d, 'auto', state, note)
        self._save()
        return inc

    def override(self, wname: str, date, increment: float, dfac: Optional[float] = None, note: str = '') -> None:
        """Ручное значение инженера заменяет действующую авто-запись на эту дату."""
        iso = _iso(date)
        for e in self.entries(wname):
            if e['active'] and e['date'] == iso:
                e['active'] = False
                if dfac is None:
                    dfac = e['dfac']
        self._append(wname, date, increment, dfac, 'manual', 'current', note)
        self._save()

    def rollback(self, wname: str, keep: int) -> None:
        """Оставляет действующими первые keep записей скважины (историю не стирает)."""
        n = 0
        for e in self.entries(wname):
            if e['active']:
                n += 1
                if n > keep:
                    e['active'] = False
        self._save()

    def load_model_mults(self, recs: List[dict]) -> None:
        """Мульты, уже стоящие в .data/.inc: начальная база отсчёта."""
        for r in recs:
            lst = self.data.setdefault(r['wname'], [])
            if r['pimult'] is not None:
                self._append(r['wname'], r['date'], r['pimult'], None, 'model', 'current', 'из файла модели')
            elif r['dfac'] is not None:
                for e in reversed(lst):
                    if e['source'] == 'model' and e['date'] == _iso(r['date']):
                        e['dfac'] = r['dfac']
                        break
                else:
                    self._append(r['wname'], r['date'], 1.0, r['dfac'], 'model', 'current', 'из файла модели')
        self._save()

    def for_result(self, r) -> Optional[dict]:
        """Последняя действующая запись на (скважина, дата) или None."""
        for e in reversed(self.active(r.wname)):
            if e['date'] == _iso(r.date):
                return e
        return None
