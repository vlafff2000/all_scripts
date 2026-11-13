"""Единицы расходов проекта Газового Атласа для всех программ, что читают его `storage/` («Карты», «ГДМ»).

В снимке проекта (parquet) расходы по скважинам (`production.q`) хранятся в **м³/сут** — Атлас переводит их при импорте
(`RATE_TO_M3` в `atlas/engine/core/loader.py`), а «БД по учету газа» (`gas_db.gas`) — в **тыс. м³/сут**. Читать эти величины
«как есть» нельзя: расход скважины окажется в 1000 раз больше. Все пересчёты — только здесь, чтобы везде значения брались одинаково
и совпадали с «Производительностью скважин» и «Показателями за сезон» Атласа. Python 3.8+.
"""
from __future__ import annotations

import pandas as pd

PRODUCTION_M3 = 1.0        # production.q → м³/сут
GAS_DB_M3 = 1000.0         # gas_db.gas (тыс. м³/сут) → м³/сут


def production_m3(q) -> pd.Series:
    """Расход по скважинам (колонка `production.q`) в м³/сут; нечисловое — пропуск."""
    return pd.to_numeric(q, errors="coerce") * PRODUCTION_M3


def production_thousand_m3(q) -> pd.Series:
    """То же в тыс. м³/сут (единица таблиц «Карт»)."""
    return production_m3(q) / 1000.0


def gas_db_m3(gas) -> pd.Series:
    """«БД по учету газа» (`gas_db.gas`, тыс. м³/сут) в м³/сут; нечисловое — пропуск."""
    return pd.to_numeric(gas, errors="coerce") * GAS_DB_M3
