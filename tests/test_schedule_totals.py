"""Эталонный суточный объём и чтение тех.карт «Скедул ПХГ»: паритет со старыми `read_total_gas_volumes`, `generate_output_files`, `create_summary_file`."""
import contextlib
import io
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_pxg import totals as t  # noqa: E402
from tests.golden import golden  # noqa: E402

SAMPLES = os.environ.get("SCHEDULE_TR_SAMPLES") or "/mnt/project-files/schedule-tr-samples"
have = pytest.mark.skipif(not os.path.isdir(SAMPLES), reason="нет образцов schedule-tr-samples")
S = lambda n: os.path.join(SAMPLES, n)  # noqa: E731
CASES = [("закачка", "Посуточная_закачка.xlsx", "Утвержденные_объемы_закачка.xlsx", "ГСП_8_a.xlsx", 2024),
         ("отбор", "Посуточные_отборы.xlsx", "Утвержденные_объемы_отбор.xlsx", "ГСП_9_b.xlsx", 2025)]


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


@have
@pytest.mark.parametrize("mode,tot,app,gsp,year", CASES)
def test_total_volumes_parity(mode, tot, app, gsp, year):
    old = golden("tot_inj" if mode == "закачка" else "tot_prod")      # эталон: старая read_total_gas_volumes
    new = t.read_total_volumes(S(tot))
    pd.testing.assert_frame_equal(new, old, check_dtype=False)
    assert (new["Объем"] >= 0).all() and new["Дата"].is_monotonic_increasing


def test_total_volumes_bad_rows_reported(tmp_path):
    p = str(tmp_path / "v.xlsx")
    pd.DataFrame({"d": ["03.01.2025", "01.01.2025", "мусор", "02.01.2025"], "v": [5, -10, 7, "x"]}).to_excel(p, index=False)
    rep = t.qc.Report("t")
    df = t.read_total_volumes(p, rep)
    assert df["Объем"].tolist() == [10, 5] and df["Дата"].dt.day.tolist() == [1, 3]
    assert any(i.code == "ROW" for i in rep.issues)
    assert t.read_total_volumes(str(tmp_path / "нет.xlsx"), rep).empty


def test_work_days_parity():
    want = golden("work_days")          # эталон: старая get_work_days_for_month
    assert len(want) == 2 * 12 * 9
    for (mn, year, dw), days in want.items():
        assert t.work_days(mn, year, dw) == days


def _inputs(mode, tot, app, gsp):
    a, d, _ = golden("appr_inj" if mode == "закачка" else "appr_prod")
    p, w = golden("pct_" + gsp[:-5])
    return a, d, p, w, golden("tot_inj" if mode == "закачка" else "tot_prod")


@have
@pytest.mark.parametrize("mode,tot,app,gsp,year", CASES)
def test_read_approved_and_percents_parity(mode, tot, app, gsp, year):
    """Новые чтение тех.карты и долей по дням дают то же, что старые `read_approved_volumes` и `process_injection_file_for_percents`."""
    a, d, p, w, _ = _inputs(mode, tot, app, gsp)
    na, nd, ng = t.read_approved(S(app))
    assert nd == d and set(na) == set(a) and all(na[k] == pytest.approx(a[k]) for k in a)
    np_, nw = t.read_percents(S(gsp), mode)
    assert set(np_) == set(p) and nw == w
    for k in p:
        assert set(np_[k]) == set(p[k]), k
        for day in p[k]:
            assert np_[k][day] == pytest.approx(p[k][day], abs=0.011), (k, day)


def test_read_approved_unknown_file(tmp_path):
    p = str(tmp_path / "x.xlsx")
    pd.DataFrame({"a": [1]}).to_excel(p, index=False)
    assert t.read_approved(p) == (None, None, None) and t.read_percents(p) == (None, None)
