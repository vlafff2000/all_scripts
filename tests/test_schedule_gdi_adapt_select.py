"""Адаптация по ГДИ: отбор исследований (качество, самое свежее, расчётные a и b), сопоставление с моделью, комплект, API."""
import pytest
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schedule_pxg.gdi_adapt import kit, selection  # noqa: E402
from schedule_pxg.gdi_adapt.config import Config  # noqa: E402

KG = 1 / 0.980665          # бар -> кгс/см2


def _study(well, date, p_res=90.0, a=0.5, b=0.002, qs=(100, 200, 300, 400), pconst=None, noisy=False):
    """Режимы ГДИ: Pпл² − Pз² = a·Q + b·Q² (Q в тыс. м3/сут, давления в барах), записаны в кгс/см2."""
    rows = []
    for i, q in enumerate(qs, 1):
        dp2 = a * q + b * q * q
        bhp = float(np.sqrt(p_res ** 2 - dp2))
        if noisy:
            bhp = p_res - 1.0 - (i % 2) * 8.0 + 0.1 * i        # Pзаб скачет без связи с дебитом
        rows.append({"№скв": well, "дата": date, "№ режима": i, "qгаза, тыс.м3/сут": q,
                     "Рзаб, кгс/см2": bhp * KG, "Рпл, кгс/см2": p_res * KG, "a": 99.0, "b": 99.0})
    return rows


def _db():
    rows = []
    rows += _study(33, "2019-03-01") + _study(33, "2022-04-01", a=0.7) + _study(33, "2024-05-01", noisy=True)   # свежее забраковано
    rows += _study(35, "2023-02-01", a=0.4)
    rows += _study(36, "2020-02-01")                                                                             # старое, в модели есть
    rows += _study(99, "2023-02-01")                                                                              # в модели нет
    rows += _study(40, "2024-01-01", qs=(100, 100.5))                                                             # один режим -> брак
    return pd.DataFrame(rows)


def _studies():
    df = _db()
    cols = selection.detect_columns(df.columns)
    return selection.build_studies(df, cols, selection.Settings())


def test_detect_columns():
    assert selection.detect_columns(_db().columns) == {"well": "№скв", "date": "дата", "wbp": "Рпл, кгс/см2", "bhp": "Рзаб, кгс/см2", "q": "qгаза, тыс.м3/сут"}


def test_ab_recomputed_not_taken_from_file():
    studies, _ = _studies()
    g = next(s for s in studies if s.wname == "35")
    assert abs(g.a - 0.4) < 0.02 and abs(g.b - 0.002) < 1e-4          # столбцы a=99, b=99 из файла проигнорированы
    assert len(g.q) == 4 and abs(g.q[0] - 100000) < 1                 # м3/сут


def test_latest_good_study_is_chosen_and_bad_latest_skipped():
    studies, _ = _studies()
    sel = selection.select(studies, Config.load(None), selection.Settings(), model=["33", "35", "36", "40", "41"])
    rows = {r.well: r for r in sel.rows}
    assert rows["33"].date.year == 2022 and rows["33"].include            # 2024 забраковано, берём 2022, не 2019
    assert "забракован" in rows["33"].note
    assert rows["35"].include and rows["36"].include
    assert not rows["99"].include and rows["99"].note == "нет в модели"
    assert not rows["40"].include and rows["40"].note.startswith("все ГДИ забракованы")
    assert sel.model_only == ["41"]


def test_negative_b_study_rejected_in_selection():
    """ГДИ с b < 0 - брак с причиной в таблице отбора: свежее отрицательное пропускается, все отрицательные - «забракованы»."""
    rows = _study(50, "2023-01-01", a=5.0, b=-0.001) + _study(50, "2021-01-01")          # свежее с b<0, старое нормальное
    rows += _study(51, "2023-01-01", a=5.0, b=-0.001)                                    # единственное ГДИ с b<0
    df = pd.DataFrame(rows)
    studies, _ = selection.build_studies(df, selection.detect_columns(df.columns), selection.Settings())
    sel = selection.select(studies, Config.load(None), selection.Settings(), model=["50", "51"])
    r = {x.well: x for x in sel.rows}
    assert r["50"].date.year == 2021 and r["50"].include
    assert "коэффициент b < 0 (физически невозможно)" in r["50"].note
    assert not r["51"].include and r["51"].note.startswith("все ГДИ забракованы")
    assert "коэффициент b < 0 (физически невозможно)" in r["51"].note


def test_age_limit_and_manual_overrides():
    studies, _ = _studies()
    st = selection.Settings(max_age_years=2.0)
    sel = selection.select(studies, Config.load(None), st, model=["33", "35", "36"], overrides={"35": False, "36": True})
    rows = {r.well: r for r in sel.rows}
    assert "старше" in rows["33"].note and not rows["33"].include
    assert not rows["35"].include                                         # выключено вручную
    assert rows["36"].include                                             # старое, но включено вручную
    assert [n for n, _ in selection.chosen_for_kit(sel)] == ["36"]


def test_resolve_synonyms():
    studies, _ = _studies()
    sel = selection.select(studies, Config.load(None), selection.Settings(), model=["W-35"], resolve=lambda n: "W-35" if n == "35" else None)
    r = next(x for x in sel.rows if x.well == "35")
    assert r.model == "W-35" and r.include


def test_kit_written_and_readable(tmp_path):
    studies, _ = _studies()
    sel = selection.select(studies, Config.load(None), selection.Settings(), model=["33", "35"])
    out = kit.write_kit(str(tmp_path / "k"), selection.chosen_for_kit(sel), {"strategy": "dp", "well_bounds": {"35": {"pi_mult_bounds": [0.2, 5]}}})
    for f in ("code.py", "config.json", "all_gdi.xlsx", "pvt_data.csv", "pi_dfac/adapt.py"):
        assert os.path.exists(os.path.join(out["folder"], f)), f
    assert not os.path.exists(os.path.join(out["folder"], "pi_dfac", "selection.py"))
    cfg = Config.load(os.path.join(out["folder"], "config.json"))
    assert cfg.strategy == "dp" and cfg.bounds_for("35")[0] == (0.2, 5.0) and cfg.bounds_for("33")[0] == (1e-4, 1000.0)
    df = pd.read_excel(os.path.join(out["folder"], "all_gdi.xlsx"))
    assert sorted(df["well"].astype(str).unique()) == ["33", "35"] and len(df) == 8
    from schedule_pxg.gdi_adapt.gdi import load_gdi
    g, skipped = load_gdi(cfg, os.path.join(out["folder"], "all_gdi.xlsx"))
    assert {x.wname for x in g} == {"33", "35"} and not skipped


def test_empty_selection_is_error(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        kit.write_kit(str(tmp_path / "k"), [])


def test_api_flow(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    from schedule_pxg.project import Project
    folder = str(tmp_path / "proj")
    p = Project()
    p.add_well("33")
    p.add_well("35")
    p.save(folder)
    monkeypatch.setattr(api, "FOLDER", folder)
    db = str(tmp_path / "gdi.xlsx")
    _db().to_excel(db, index=False)
    c = TestClient(api.build_app())
    r = c.get("/api/adapt/columns", params={"path": db}).json()
    assert r["detected"]["wbp"] == "Рпл, кгс/см2"
    body = {"db": db, "settings": {}, "config": {}, "overrides": {}}
    r = c.post("/api/adapt/select", json=body).json()
    assert r["counts"]["included"] == 2 and r["counts"]["no_model"] >= 2, r["counts"]
    body["overrides"] = {"35": False}
    r = c.post("/api/adapt/select", json=body).json()
    assert r["counts"]["included"] == 1
    st = c.get("/api/adapt").json()
    assert st["db"] == db and st["overrides"] == {"35": False} and "pi_mult_bounds" in st["config"]
    out = str(tmp_path / "kit")
    r = c.post("/api/adapt/kit", json=dict(body, out=out, config={"strategy": "dp"}))
    assert r.status_code == 200 and r.json()["wells"] == ["33"]
    assert c.post("/api/adapt/kit", json=dict(body, out="")).status_code == 400
    assert c.post("/api/adapt/select", json=dict(body, db=str(tmp_path / "nope.xlsx"))).status_code == 400


def test_string_dates_iso_and_dayfirst():
    df = _db()
    df["дата"] = df["дата"].astype(str)
    df.loc[df["дата"] == "2023-02-01", "дата"] = "01.02.2023"        # дд.мм.гггг
    studies, _ = selection.build_studies(df, selection.detect_columns(df.columns), selection.Settings())
    dates = {(s.wname, s.date.strftime("%Y-%m-%d")) for s in studies}
    assert ("35", "2023-02-01") in dates and ("33", "2022-04-01") in dates


def test_recompute_flow_and_api(tmp_path, monkeypatch):
    """Комплект -> снимки модели (заглушка тНавигатора) -> пересчёт без тНавигатора -> результаты, запуски, файлы."""
    import glob
    from starlette.testclient import TestClient
    from schedule_pxg import api
    from schedule_pxg.project import Project
    sys.path.insert(0, os.path.dirname(__file__))
    import gdi_adapt_mock_tnav as mock
    from schedule_pxg.gdi_adapt import tnav_api
    from schedule_pxg.gdi_adapt.snapshot import save_snapshots

    folder = str(tmp_path / "proj")
    p = Project()
    p.add_group("ГСП-1")
    p.add_well("33", group="ГСП-1")
    p.add_well("35", group="ГСП-1")
    p.save(folder)
    monkeypatch.setattr(api, "FOLDER", folder)
    db = str(tmp_path / "gdi.xlsx")
    _db().to_excel(db, index=False)
    c = TestClient(api.build_app())
    kitdir = str(tmp_path / "kit")
    body = {"db": db, "settings": {}, "config": {"strategy": "andrey"}, "overrides": {}, "scenario": "", "out": kitdir}
    assert c.post("/api/adapt/kit", json=body).status_code == 200
    assert c.get("/api/adapt").json()["kit"] == kitdir

    # «тНавигатор»: заглушка читает модель, снимки сохраняются как это делает code.py
    cfg = kit.kit_config({})
    tnav_api.bind(mock.make_tnav({"33": 91.0, "35": 91.0}), 0)
    snaps = {}
    for g in selection.chosen_for_kit(selection.select(_studies()[0], Config.load(None), selection.Settings(), model=["33", "35"])):
        snaps[g[0]] = tnav_api.extract_snapshot(g[0], g[1].date)
    os.makedirs(os.path.join(kitdir, "runs", "2026-01-01_00-00-00"))
    pkl = os.path.join(kitdir, "runs", "2026-01-01_00-00-00", "snapshots.pkl")
    save_snapshots(snaps, pkl)

    r = c.post("/api/adapt/recompute", json={"kit": kitdir, "snapshots": kitdir, "config": {"strategy": "dp", "make_png": True, "save_snapshots": True}})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["summary"]["wells"] + v["summary"]["skipped"] == 2
    assert all(x["well"] in ("33", "35") for x in v["rows"])
    assert v["summary"]["wells"] == 2
    row = v["rows"][0]
    assert row["curve_q"] and len(row["curve_before"]) == len(row["curve_q"]) and row["pi_mult"] > 0
    assert row["dep_qmax"] is None or row["dep_qmax"] > 0
    assert {g["group"] for g in v["groups"]} == {"ГСП-1"}
    runs_ = c.get("/api/adapt/runs", params={"kit": kitdir}).json()["runs"]
    assert any(x["has_results"] for x in runs_)
    again = c.get("/api/adapt/run", params={"dir": v["run_dir"]}).json()
    assert again["summary"] == v["summary"]
    assert c.get("/api/adapt/file", params={"dir": v["run_dir"], "kind": "inc"}).status_code == 200
    assert c.get("/api/adapt/file", params={"dir": v["run_dir"], "kind": "exe"}).status_code == 404
    assert c.post("/api/adapt/recompute", json={"kit": str(tmp_path), "snapshots": kitdir}).status_code == 400


def test_all_dates_sequential_include(tmp_path):
    """Все прошедшие контроль исследования скважины -> снимки по ключу скважина@дата -> include с приращением WPIMULT."""
    import re
    sys.path.insert(0, os.path.dirname(__file__))
    import gdi_adapt_mock_tnav as mock
    from schedule_pxg.gdi_adapt import runs, tnav_api
    from schedule_pxg.gdi_adapt.gdi import load_gdi
    from schedule_pxg.gdi_adapt.snapshot import save_snapshots
    sel = selection.select(_studies()[0], Config.load(None), selection.Settings(), model=["33", "35"])
    last = selection.chosen_for_kit(sel)
    allp = selection.chosen_for_kit(sel, all_dates=True)
    assert [n for n, _ in last] == ["33", "35"]
    assert [(n, g.date.year) for n, g in allp] == [("33", 2019), ("33", 2022), ("35", 2023)]     # 2024 забраковано
    kitdir = str(tmp_path / "k")
    kit.write_kit(kitdir, allp, {"all_dates": True, "ci_jackknife": False})
    cfg = Config.load(os.path.join(kitdir, "config.json"))
    gs, _ = load_gdi(cfg, os.path.join(kitdir, "all_gdi.xlsx"))
    assert sorted(g.key for g in gs) == ["33@2019-03-01", "33@2022-04-01", "35@2023-02-01"]
    with open(os.path.join(kitdir, "studies.json"), encoding="utf-8") as f:      # код в тНавигаторе пишет снимки по этим ключам
        assert sorted(x["key"] for x in json.load(f)) == sorted(g.key for g in gs)
    tnav_api.bind(mock.make_tnav({"33": 91.0, "35": 91.0}), 0)
    snaps = {g.key: tnav_api.extract_snapshot(g.wname, g.date) for g in gs}
    os.makedirs(os.path.join(kitdir, "runs", "x"))
    save_snapshots(snaps, os.path.join(kitdir, "runs", "x", "snapshots.pkl"))
    v = runs.recompute(kitdir, kitdir, {"strategy": "dp", "ci_jackknife": False})
    assert v["summary"]["wells"] == 3
    w33 = sorted((r for r in v["rows"] if r["well"] == "33"), key=lambda r: r["date"])
    inc = open(os.path.join(v["run_dir"], "wpimult_wdfac.inc"), encoding="utf-8").read()
    mult = [float(m) for m in re.findall(r"^33\t(\S+)\t/$", inc, re.M) if "e" not in m][:2]      # WPIMULT первой и второй даты (WDFAC в экспоненте)
    assert len(w33) == 2 and abs(mult[0] - w33[0]["pi_mult"]) < 1e-6 * w33[0]["pi_mult"] + 1e-9
    assert abs(mult[1] - w33[1]["pi_mult"] / w33[0]["pi_mult"]) < 1e-5 * mult[1] + 1e-9
    assert [x["group"] for x in v["groups"]] == ["без группы"] and v["groups"][0]["wells"] == 2   # 33 считается один раз (свежее ГДИ)


def test_code_runs_as_pasted_and_results_load(tmp_path, monkeypatch):
    """Код из кнопки «Копировать код» выполняется без правок (путь вписан), снимки читает Скедул (класс из pi_dfac)."""
    sys.path.insert(0, os.path.dirname(__file__))
    import gdi_adapt_mock_tnav as mock
    from schedule_pxg.gdi_adapt import runs
    sel = selection.select(_studies()[0], Config.load(None), selection.Settings(), model=["33", "35"])
    kitdir = str(tmp_path / "комплект")
    res = kit.write_kit(kitdir, selection.chosen_for_kit(sel), {"strategy": "dp", "ci_jackknife": False})
    assert os.path.abspath(kitdir) in res["code"] and "__PROJECT_DIR__" not in res["code"]
    from schedule_pxg import adapt_view
    assert adapt_view.kit_code(kitdir)["code"] == res["code"]
    for m in [m for m in sys.modules if m == "pi_dfac" or m.startswith("pi_dfac.")]:
        del sys.modules[m]
    g = dict(mock.make_tnav({"33": 91.0, "35": 91.0}), __name__="__main__")
    monkeypatch.chdir(tmp_path)
    exec(compile(res["code"], "code.py", "exec"), g)
    sys.path[:] = [p for p in sys.path if p != os.path.abspath(kitdir)]
    out = [d for d in os.listdir(os.path.join(kitdir, "runs"))]
    assert len(out) == 1 and os.path.isfile(os.path.join(kitdir, "runs", out[0], "snapshots.pkl"))
    for m in [m for m in sys.modules if m == "pi_dfac" or m.startswith("pi_dfac.")]:
        del sys.modules[m]
    v = runs.recompute(kitdir, kitdir, {"strategy": "dp", "ci_jackknife": False})
    assert v["summary"]["wells"] == 2


def test_check_columns_manual_and_comma_decimals(tmp_path):
    from schedule_pxg import adapt_view
    df = pd.DataFrame({"№скв": [33, 33], "дата": ["2022-04-01"] * 2, "Qгаза, тыс.м3/сут": ["100,5", "200"],
                       "Рзаб": ["80,0", "70"], "Пластовое, кгс/см2": ["90,0", "90"]})
    f = str(tmp_path / "db.xlsx")
    df.to_excel(f, index=False)
    det = selection.detect_columns(df.columns)
    assert "wbp" not in det
    cols = dict(det, wbp="Пластовое, кгс/см2")
    r = adapt_view.check_columns(f, "", cols)
    assert r["ok"] and not r["problems"], r
    assert any("Не выбран" in x for x in adapt_view.check_columns(f, "", dict(cols, wbp=""))["problems"])
    studies, _ = selection.build_studies(pd.read_excel(f), cols, selection.Settings())
    assert len(studies) == 1 and len(studies[0].q) == 2 and abs(studies[0].q[0] - 100500.0) < 1e-6


def test_snapshots_foreign_class_path_and_garbage(tmp_path, monkeypatch):
    import dataclasses
    import pickle
    import sys
    import types
    import numpy as np
    from schedule_pxg.gdi_adapt.snapshot import WellSnapshot, load_snapshots
    mod = types.ModuleType("foreign_snapshot")      # класс в другом модуле, как в комплекте тНавигатора
    # старый формат без полей shift_days/t_date (старые снимки); новые поля с умолчанием читаются как значения по умолчанию
    foreign = dataclasses.make_dataclass("WellSnapshot", [(f.name, object) for f in dataclasses.fields(WellSnapshot)
                                                          if f.name not in ("shift_days", "t_date")])
    foreign.__module__ = "foreign_snapshot"
    mod.WellSnapshot = foreign
    monkeypatch.setitem(sys.modules, "foreign_snapshot", mod)
    a = np.zeros(1)
    p = tmp_path / "snapshots.pkl"
    p.write_bytes(pickle.dumps({"W": foreign("W", "t", "t", False, a, a, a, a, a, a, a, a, 1.0, 1.0, 1.0)}))
    monkeypatch.delitem(sys.modules, "foreign_snapshot")
    got = load_snapshots(str(p))
    assert isinstance(got["W"], WellSnapshot) and got["W"].n_perf == 1
    p.write_bytes(b"not a pickle")
    with pytest.raises(ValueError):
        load_snapshots(str(p))
