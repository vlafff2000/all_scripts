"""Одна база расходов — три читалки (аудит объединения, пункт 8): Карты ГСП, Скедул и Атлас дают одни суммы.

Файл tests/fixtures/db_rashody_mini.xlsx — тот же, что в gas_atlas/tests/fixtures (байты совпадают).
Ожидаемые суммы — в EXPECTED; менять только вместе с gas_atlas/tests/atlas/test_db_rashody_readers.py.
"""
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "db_rashody_mini.xlsx")

# (скважина, дата) → суточный расход газа, м³/сут; отбор и закачка
EXPECTED = {
    (101, date(2026, 10, 1)): 1000.0,
    (101, date(2026, 10, 2)): 1200.0,
    (102, date(2026, 10, 1)): 800.0,
    (102, date(2026, 10, 2)): 900.0,
    (201, date(2026, 10, 1)): 500.0,
}


def test_gsp_maps_reads_same_sums():
    pytest.importorskip("pandas")
    pytest.importorskip("numpy")
    from gsp_maps import store

    arrays = store._build(FIXTURE, None)
    got = {}
    for w, d, q in zip(arrays["well"], arrays["day"], arrays["flow"]):
        got[(int(w), date.fromordinal(int(d) + date(1970, 1, 1).toordinal()))] = float(q)
    assert got == EXPECTED


def test_schedule_reads_same_sums():
    pd = pytest.importorskip("pandas")
    from schedule_pxg import history

    tpl = history.Template(name="база расходов", sheet=None, rate="Суточный расход газа", kind="Тип данных", unit="м3/сут")
    df = history.read_by_template(FIXTURE, tpl)
    got = {(int(r.well), pd.Timestamp(r.date).date()): float(r.rate) for r in df.itertuples()}
    assert got == EXPECTED
