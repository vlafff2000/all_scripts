"""Общие объёмы и проверочный Excel «Скедул ПХГ»: паритет со старыми `read_total_gas_volumes`, `generate_output_files`, `create_summary_file`."""
import contextlib
import io
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_pxg import totals as t  # noqa: E402

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
    old = quiet(t.legacy().read_total_gas_volumes, S(tot))
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
    old = t.legacy().get_work_days_for_month
    for year in (2024, 2025):
        for mn in range(1, 13):
            for dw in (0, 5, 14, 15, 20, 28, 30, 31, 40):
                assert t.work_days(mn, year, dw) == old("м", mn, year, dw)


def _inputs(mode, tot, app, gsp):
    old = t.legacy()
    a, d, _ = quiet(old.read_approved_volumes, S(app))
    p, w = quiet(old.process_injection_file_for_percents, S(gsp), mode)
    return old, a, d, p, w, quiet(old.read_total_gas_volumes, S(tot))


@have
@pytest.mark.parametrize("mode,tot,app,gsp,year", CASES)
def test_gsp_files_and_summary_parity(mode, tot, app, gsp, year, tmp_path):
    old, a, d, p, w, total = _inputs(mode, tot, app, gsp)
    assert p
    o, n = str(tmp_path / "old"), str(tmp_path / "new")
    os.makedirs(o)
    of = quiet(old.generate_output_files, p, w, a, d, total, o, year, None)
    quiet(old.create_summary_file, p, a, d, total, year, o, mode)
    nf = t.write_gsp_files(p, a, d, total, n, year)
    t.write_summary(t.summary_frame(p, a, d, total, year, mode), n)
    assert sorted(map(os.path.basename, nf)) == sorted(map(os.path.basename, of)) and nf
    for f in of:
        x, y = pd.read_excel(f, sheet_name=None, header=None), pd.read_excel(os.path.join(n, os.path.basename(f)), sheet_name=None, header=None)
        assert list(x) == list(y)
        for sh in x:
            pd.testing.assert_frame_equal(y[sh], x[sh])
    so = os.path.join(o, t.SUMMARY_NAME)
    if os.path.isfile(so):
        pd.testing.assert_frame_equal(pd.read_excel(os.path.join(n, t.SUMMARY_NAME)), pd.read_excel(so))


@have
def test_build_check_end_to_end(tmp_path):
    r = t.build_check(S("Посуточные_отборы.xlsx"), S("Утвержденные_объемы_отбор.xlsx"), [S("ГСП_9_b.xlsx")], "отбор", 2025, str(tmp_path))
    assert r["files"] and r["summary"] and os.path.isfile(r["summary"]) and r["days"] > 0


def test_build_check_missing_inputs_reports(tmp_path):
    r = t.build_check(str(tmp_path / "a.xlsx"), str(tmp_path / "b.xlsx"), [], "закачка", 2025, str(tmp_path))
    assert r["files"] == [] and r["summary"] is None and r["issues"].issues


@have
def test_api_check_button(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    monkeypatch.setattr(api, "FOLDER", str(tmp_path / "proj"))
    c = TestClient(api.build_app())
    body = {"totals": S("Посуточные_отборы.xlsx"), "approved": S("Утвержденные_объемы_отбор.xlsx"), "gsp": [S("ГСП_9_b.xlsx")],
            "mode": "отбор", "year": 2025}
    r = c.post("/api/check", json=body)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["days"] > 0 and os.path.isfile(r.json()["summary"])
    assert c.post("/api/check", json=dict(body, totals=str(tmp_path / "нет.xlsx"))).status_code == 404
    assert c.post("/api/check", json=dict(body, gsp=[])).status_code == 400
