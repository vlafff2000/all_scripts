"""
Снимок данных модели по одной скважине - всё, что нужно расчёту от тНавигатора.

Идея: чтение модели (медленно, только внутри тНавигатора) отделено от математики адаптации (чистый Python).
Снимки сохраняются в snapshots.pkl, и дальше адаптацию можно перезапускать с другими настройками
(стратегия, границы, цель, пороги) вне тНавигатора за секунды: python run_offline.py --snapshots ...
"""
import pickle
from typing import Dict, List

import numpy as np


class WellSnapshot(object):
    """Обычный класс, не dataclass: код снимков исполняется внутри tNavigator 21.3, где Python 3.6 (нет dataclasses и
    `from __future__ import annotations`). Поля те же; новые необязательные - со значениями по умолчанию."""

    shift_days = 0.0         # значения по умолчанию на уровне класса: старые pickle без этих полей читаются как раньше
    t_date = ''

    def __init__(self, wname, t_name, t_requested, substituted, cbp, cdrd, cgpr, cdfac, cekh, cdiam, cefr, ctfac,
                 wbp, wgpr, wbhp, shift_days=0.0, t_date=''):
        self.wname = wname                  # имя скважины
        self.t_name = t_name                # имя шага модели, по которому читались данные
        self.t_requested = t_requested      # шаг на дату ГДИ (отличается, если скважина на нём стояла)
        self.substituted = substituted      # True - использован ближайший работающий шаг
        # по открытым перфорациям (массивы одной длины)
        self.cbp = cbp                      # давление в блоке
        self.cdrd = cdrd                    # депрессия на перфорации
        self.cgpr = cgpr                    # дебит газа перфорации
        self.cdfac = cdfac                  # D-фактор перфорации
        self.cekh = cekh                    # эффективный KH
        self.cdiam = cdiam                  # диаметр скважины
        self.cefr = cefr                    # эквивалентный радиус
        self.ctfac = ctfac                  # коэффициент проводимости (для расчёта старого D скважины)
        # по скважине
        self.wbp = wbp                      # модельное пластовое давление
        self.wgpr = wgpr                    # модельный дебит газа
        self.wbhp = wbhp                    # модельное забойное давление
        # необязательные (старые pickle их не содержат - читать через getattr с умолчанием)
        self.shift_days = shift_days        # сдвиг шага модели от даты ГДИ, дни со знаком (шаг - ГДИ); 0 - даты шагов неизвестны
        self.t_date = t_date                # дата использованного шага модели (ДД.ММ.ГГГГ), пусто - неизвестна

    def __repr__(self):
        return 'WellSnapshot(%r, %s, %d перф.)' % (self.wname, self.t_name, self.n_perf)

    @property
    def n_perf(self) -> int:
        return len(self.cbp)


def save_snapshots(snaps: Dict[str, WellSnapshot], path: str) -> None:
    with open(path, 'wb') as f:
        pickle.dump(snaps, f)


class _Unpickler(pickle.Unpickler):
    """Снимки пишет код в тНавигаторе (пакет pi_dfac из комплекта); в Скедуле тот же класс лежит в этом пакете."""

    def find_class(self, module, name):
        if name == 'WellSnapshot':      # любой путь модуля: pi_dfac.snapshot, snapshot, __main__
            return WellSnapshot
        try:
            return super().find_class(module, name)
        except ModuleNotFoundError:     # массивы, записанные numpy 2 (numpy._core), читаются numpy 1 и наоборот
            if module.startswith('numpy._core'):
                return super().find_class('numpy.core' + module[len('numpy._core'):], name)
            if module.startswith('numpy.core'):
                return super().find_class('numpy._core' + module[len('numpy.core'):], name)
            raise


def load_snapshots(path: str) -> Dict[str, WellSnapshot]:
    try:
        with open(path, 'rb') as f:
            snaps = _Unpickler(f).load()
    except Exception as e:
        raise ValueError('Не удалось прочитать снимки «%s»: %s: %s' % (path, type(e).__name__, e))
    if not isinstance(snaps, dict) or not snaps:
        raise ValueError('В «%s» нет снимков скважин (файл пуст или другого формата).' % path)
    return snaps
