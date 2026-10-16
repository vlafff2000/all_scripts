"""Адаптация по ГДИ: отбор исследований (качество, самое свежее, расчётные a и b), сопоставление с моделью, комплект, API."""
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
