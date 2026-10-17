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

    @property
    def n_perf(self) -> int:
        return len(self.cbp)


def save_snapshots(snaps: Dict[str, WellSnapshot], path: str) -> None:
    with open(path, 'wb') as f:
        pickle.dump(snaps, f)


class _Unpickler(pickle.Unpickler):
    """Снимки пишет код в тНавигаторе (пакет pi_dfac из комплекта); в Скедуле тот же класс лежит в этом пакете."""

    def find_class(self, module, name):
        if module == 'pi_dfac.snapshot' and name == 'WellSnapshot':
            return WellSnapshot
        return super().find_class(module, name)


def load_snapshots(path: str) -> Dict[str, WellSnapshot]:
    with open(path, 'rb') as f:
        return _Unpickler(f).load()
