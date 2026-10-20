"""
Снимок данных модели по одной скважине - всё, что нужно расчёту от тНавигатора.

Идея: чтение модели (медленно, только внутри тНавигатора) отделено от математики адаптации (чистый Python).
Снимки сохраняются в snapshots.pkl, и дальше адаптацию можно перезапускать с другими настройками
(стратегия, границы, цель, пороги) вне тНавигатора за секунды: python run_offline.py --snapshots ...
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np


@dataclass
class WellSnapshot:
    wname: str
    t_name: str                  # имя шага модели, по которому читались данные
    t_requested: str             # шаг на дату ГДИ (отличается, если скважина на нём стояла)
    substituted: bool            # True - использован ближайший работающий шаг
    # по открытым перфорациям (массивы одной длины)
    cbp: np.ndarray              # давление в блоке
    cdrd: np.ndarray             # депрессия на перфорации
    cgpr: np.ndarray             # дебит газа перфорации
    cdfac: np.ndarray            # D-фактор перфорации
    cekh: np.ndarray             # эффективный KH
    cdiam: np.ndarray            # диаметр скважины
    cefr: np.ndarray             # эквивалентный радиус
    ctfac: np.ndarray            # коэффициент проводимости (для расчёта старого D скважины)
    # по скважине
    wbp: float                   # модельное пластовое давление
    wgpr: float                  # модельный дебит газа
    wbhp: float                  # модельное забойное давление
    # необязательные (старые pickle их не содержат - читать через getattr с умолчанием)
    shift_days: float = 0.0      # сдвиг шага модели от даты ГДИ, дни со знаком (шаг - ГДИ); 0 - если даты шагов неизвестны
    t_date: str = ''             # дата использованного шага модели (ДД.ММ.ГГГГ), пусто - неизвестна

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
