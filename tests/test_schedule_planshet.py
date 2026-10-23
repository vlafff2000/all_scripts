from __future__ import annotations

import json
import os

import pandas as pd
import pytest

from pxg_core import gis_export
from schedule_pxg import planshet
from schedule_pxg.project import Project


def _folder(tmp_path, alt=100.0):
    d = tmp_path / "gis"
    d.mkdir()
    day = pd.Timestamp("2025-04-10")
    pd.DataFrame([{"well": "101", "date": day, "season": "весна", "status": "ok", "packs": 1},
                  {"well": "101", "date": pd.Timestamp("2024-11-01"), "season": "осень", "status": "ok", "packs": 1}]
                 ).to_csv(d / "gis_observations.csv", sep=";", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"well": "101", "date": day, "pack": "верхняя", "top_m": 1000.0, "bottom_m": 1020.0, "gvk_label": "ГВК",
                   "gvk_depth_m": 1015.0, "gvk_abs_m": alt - 1015.0, "altitude_m": alt}]
                 ).to_csv(d / "gis_packs.csv", sep=";", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"well": "101", "date": day, "pack": "верхняя", "from_m": 1000.0, "to_m": 1010.0, "kg": 0.7, "kp": 0.2, "status": "ok"},
                  {"well": "101", "date": day, "pack": "верхняя", "from_m": 1010.0, "to_m": 1020.0, "kg": 0.1, "kp": 0.2, "status": "ok"}]
                 ).to_csv(d / "gis_intervals.csv", sep=";", index=False, encoding="utf-8-sig")
    (d / "gis_db_meta.json").write_text(json.dumps({"format": gis_export.FORMAT_NAME, "version": gis_export.FORMAT_VERSION}), encoding="utf8")
    return str(d)


def test_fact_in_absolute_marks(tmp_path):
    t = planshet.load_tables(_folder(tmp_path))
    f = planshet.fact(t, "101.0")                       # номер как число из Excel; последний замер
    assert f["date"] == "2025-04-10" and f["dates"] == ["2024-11-01", "2025-04-10"] and f["altitude"] == 100.0
    assert [(i["top"], i["bottom"]) for i in f["intervals"]] == [(-900.0, -910.0), (-910.0, -920.0)]
    assert f["packs"][0]["gvk"] == -915.0 and f["packs"][0]["label"] == "ГВК"
    old = planshet.fact(t, "101", "2024-11-01")
    assert old["date"] == "2024-11-01" and old["intervals"] == [] and old["packs"] == []     # по осеннему замеру в базе нет строк
    near = planshet.fact(t, "101", "2025-01-01")
    assert near["date"] == "2025-04-10" and near["notes"]                                    # нет замера на дату: заметка, не ошибка
    assert planshet.fact(t, "999")["notes"] and planshet.fact(t, "999")["intervals"] == []


def test_altitude_override_moves_marks(tmp_path):
    t = planshet.load_tables(_folder(tmp_path))
    f = planshet.fact(t, "101", alt_override=50.0)
    assert f["intervals"][0]["top"] == -950.0 and f["packs"][0]["gvk"] == -965.0


def test_view_needs_folder_and_checks_format(tmp_path):
    p = Project("x")
    with pytest.raises(ValueError):
        planshet.view(p, ["101"])
    folder = _folder(tmp_path)
    planshet.set_settings(p, folder, "")
    v = planshet.view(p, ["101"])
    assert v["rows"][0]["perforation"] is None and v["notes"]
    open(os.path.join(folder, "gis_db_meta.json"), "w").write('{"format": "x"}')
    with pytest.raises(ValueError):
        planshet.view(p, ["101"])


def test_perf_conversion():
    assert planshet.abs_depth_perf(-905.0, 100.0) == -905.0
    assert planshet.abs_depth_perf(1005.0, 100.0) == -905.0
    assert planshet.abs_depth_perf(1005.0, None) is None
    p = Project("x")
    planshet.set_settings(p, "a", "b")
    planshet.set_settings(p, "", "b")
    assert p.sources["gis"] == {"perf_file": "b"}


def test_view_manual_altitude_wins(tmp_path):
    p = Project("x")
    planshet.set_settings(p, _folder(tmp_path), "")
    v = planshet.view(p, ["101"], "", {"101": 50.0})["rows"][0]
    assert v["altitude"] == 50.0 and v["intervals"][0]["top"] == -950.0
    assert any("вручную" in n for n in v["notes"])
    assert planshet.view(p, ["101"])["rows"][0]["altitude"] == 100.0


def test_catalog_and_multi_dates(tmp_path):
    p = Project("x")
    planshet.set_settings(p, _folder(tmp_path), "")
    c = planshet.catalog(p)
    assert c["wells"] == ["101"]
    assert [(o["date"], o["season"]) for o in c["observations"]] == [("2024-11-01", "осень 2024"), ("2025-04-10", "весна 2025")]
    v = planshet.view(p, [], "", None, [("101", "2024-11-01"), ("101.0", "2025-04-10")])
    assert [r["date"] for r in v["rows"]] == ["2024-11-01", "2025-04-10"]
