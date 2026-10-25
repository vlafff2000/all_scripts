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
    from gsp_maps.inputs import perforation_abs
    assert perforation_abs({"plain": (-905.0, -915.0)}, 100.0) == ((-905.0, -915.0), "plain_ao")
    # без подписи и без режима положительные значения — а.о. без знака: получают минус; режим «md» — глубина от стола
    assert perforation_abs({"plain": (1005.0, 1015.0)}, 100.0) == ((-1005.0, -1015.0), "plain_flip")
    assert perforation_abs({"plain": (1005.0, 1015.0)}, 100.0, "md") == ((-905.0, -915.0), "plain_md")
    assert perforation_abs({"plain": (1005.0, 1015.0)}, None, "md")[0] is None
    assert perforation_abs({"ao": (1500.0, 1520.0)}, 85.0) == ((-1500.0, -1520.0), "ao_flip")
    # явные а.о. главнее MD и не зависят от знака и альтитуды
    both = {"ao": (-1500.0, -1520.0), "md": (1700.0, 1730.0)}
    assert perforation_abs(both, 85.0) == ((-1500.0, -1520.0), "ao")
    assert perforation_abs({"md": (1700.0, 1730.0)}, 85.0) == ((-1615.0, -1645.0), "md")
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


def _perf_book(path, header, rows, alt=None):
    import pandas as pd
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame(header + rows).to_excel(w, sheet_name="перфорации", header=False, index=False)
        if alt:
            pd.DataFrame([["Скв", "Z"]] + alt).to_excel(w, sheet_name="альтитуды", header=False, index=False)


def test_perf_file_explicit_md_and_ao_columns(tmp_path):
    from gsp_maps.inputs import load_perforations, read_perforations
    f = str(tmp_path / "p.xlsx")
    # MD стоят в тех самых столбцах 5 и 6, где раньше ждали а.о. — наклонная скважина: MD заметно больше глубины
    _perf_book(f, [["Скв", "Пласт", "Куст", "Верх MD, м", "Низ MD, м", "Верх а.о., м", "Низ а.о., м"]],
               [[31, "A", 1, 1700.0, 1730.0, -1500.0, -1525.0], [32, "A", 1, 1700.0, 1730.0, None, None]],
               [[31, 85.0], [32, 85.0]])
    rows, _ = read_perforations(f)
    assert rows[31]["md"] == (1700.0, 1730.0) and rows[31]["ao"] == (-1500.0, -1525.0) and rows[32]["ao"] is None
    depths, alt = load_perforations(f)
    assert depths[31] == (-1500.0, -1525.0)          # а.о. напрямую
    assert depths[32] == (85.0 - 1700.0, 85.0 - 1730.0)   # нет а.о. — из MD через альтитуду


def test_perf_file_two_row_header_and_legacy(tmp_path):
    from gsp_maps.inputs import read_perforations
    f = str(tmp_path / "p2.xlsx")
    _perf_book(f, [["Скв", "", "Верх перфорации", "", "Низ перфорации", ""], ["", "", "MD", "а.о.", "MD", "а.о."]],
               [[5, 0, 1700.0, -1600.0, 1730.0, -1620.0]])
    rows, _ = read_perforations(f)
    assert rows[5]["ao"] == (-1600.0, -1620.0) and rows[5]["md"] == (1700.0, 1730.0)
    g = str(tmp_path / "old.xlsx")
    _perf_book(g, [["Скв", "a", "b", "c", "Верх", "Низ"]], [[7, 0, 0, 0, -1500.5, -1520.0]])
    rows, _ = read_perforations(g)
    assert rows[7] == {"ao": None, "md": None, "plain": (-1500.5, -1520.0)}


def test_view_shows_perforation_source(tmp_path):
    f = str(tmp_path / "p.xlsx")
    _perf_book(f, [["Скв", "Верх MD", "Низ MD", "Верх а.о.", "Низ а.о."]], [[101, 1700.0, 1730.0, -1500.0, -1525.0]], [[101, 85.0]])
    p = Project("x")
    planshet.set_settings(p, _folder(tmp_path), f)
    r = planshet.view(p, ["101"])["rows"][0]
    assert r["perforation"] == {"top": -1500.0, "bottom": -1525.0}
    assert any(n.startswith("Перфорация: а.о.") for n in r["notes"])


def test_perf_mode_setting_survives_source_save():
    p = Project("x")
    planshet.set_settings(p, "a", "b", "md")
    planshet.set_settings(p, "a", "c")
    assert p.sources["gis"] == {"folder": "a", "perf_file": "c", "perf_mode": "md"}
    planshet.set_settings(p, "a", "c", "")
    assert "perf_mode" not in p.sources["gis"]


def test_perforations_from_model(tmp_path, monkeypatch):
    from array import array
    from tnav_results import Grid, perforations as tp
    data = tmp_path / "M.data"
    data.write_text("START\n 1 JAN 2024 /\nWELSPECS\n '101' 'G' 1 1 1* GAS /\n/\nCOMPDAT\n '101' 1* 1* 2 3 OPEN /\n/\n"
                    "DATES\n 1 FEB 2025 /\n/\nWELOPEN\n '101' SHUT /\n/\n", encoding="utf-8")
    z = array("f")
    for k in range(3):
        z.extend([1000.0 + 10 * k] * 4)
        z.extend([1010.0 + 10 * k] * 4)
    grid = Grid(1, 1, 3, [1] * 3, array("f"), z, None)
    monkeypatch.setattr(planshet, "_model_perf_source", lambda path: (tp.read_perforations(str(data)), grid))
    got = planshet.model_perforations("M.EGRID", ["101.0", "555"], "2024-11-01")
    assert list(got) == ["101"] and [(i["top"], i["bottom"]) for i in got["101"]["intervals"]] == [(-1010.0, -1030.0)]
    assert planshet.model_perforations("M.EGRID", ["101"], "2025-04-10")["101"]["intervals"] == []     # после WELOPEN SHUT
    p = Project()
    planshet.set_settings(p, _folder(tmp_path), "", None, "M.EGRID")
    v = planshet.view(p, ["101"], "2024-11-01")
    assert v["rows"][0]["perforation"]["source"] == "model"
    assert any("из модели" in n for n in v["rows"][0]["notes"])
    assert planshet.settings(p)["perf_model"] == "M.EGRID"
    planshet.set_settings(p, planshet.settings(p)["folder"], "", None, "")
    assert "perf_model" not in planshet.settings(p)
