"""Тех.карты «Скедул ПХГ»: импорт, паритет со старым read_approved_volumes, рабочие дни, библиотека, проверки."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pxg_core import qc  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from tests.golden import golden  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402

SAMPLES = os.environ.get("SCHEDULE_TR_SAMPLES") or "/mnt/project-files/schedule-tr-samples"
have = pytest.mark.skipif(not os.path.isdir(SAMPLES), reason="нет образцов schedule-tr-samples")
INJ = os.path.join(SAMPLES, "Утвержденные_объемы_закачка.xlsx")
PROD = os.path.join(SAMPLES, "Утвержденные_объемы_отбор.xlsx")


@have
@pytest.mark.parametrize("path", [INJ, PROD])
def test_parity_with_read_approved_volumes(path):
    """Эталон: результат старой `read_approved_volumes` на образцах (tests/golden)."""
    approved, days, gsp = golden("appr_inj" if path == INJ else "appr_prod")
    tm = tmod.read_techmap(path)
    assert tm.days == days and [int(g) for g in tm.volumes] == gsp
    for (g, m), v in approved.items():
        assert tm.volumes[str(g)][m] * 1e6 == pytest.approx(v)


@have
def test_kind_months_totals_and_clean_check():
    inj, prod = tmod.read_techmap(INJ), tmod.read_techmap(PROD)
    assert (inj.kind, prod.kind) == ("закачка", "отбор")
    assert inj.months[0] == "Апрель" and inj.months[-1] == "Октябрь" and prod.months[0] == "Ноябрь"
    assert inj.total("Июль") == pytest.approx(inj.totals["Июль"]) and inj.wells["1"] == 40
    assert not tmod.check_techmap(inj).issues and not tmod.check_techmap(prod).issues


def test_work_days_season_edges():
    # первый месяц сезона — последние дни, последний — первые
    assert tmod.work_days("Апрель", 2025, 4, "start") == [27, 28, 29, 30]
    assert tmod.work_days("Октябрь", 2025, 15, "end") == list(range(1, 16))
    assert tmod.work_days("Май", 2025, 31) == list(range(1, 32)) and tmod.work_days("Июнь", 2025, 0) == []


def _tm():
    t = tmod.TechMap("Карта", "закачка", ["Апрель", "Май"])
    t.days = {"Апрель": 4, "Май": 31}
    t.volumes = {"1": {"Апрель": 1.0, "Май": 2.0}, "2": {"Апрель": 3.0, "Май": 4.0}}
    t.totals = {"Апрель": 4.0, "Май": 6.5}
    return t


def test_checks_sum_days_groups():
    p = Project()
    p.add_group("ГСП 1")
    p.add_well("101", group="ГСП 1")
    p.add_group("ГСП 2")
    t = _tm()
    t.days["Май"] = 40
    t.volumes["3"] = {"Апрель": -1.0, "Май": 0.0}
    codes = {(i.level, i.code) for i in tmod.check_techmap(t, p).issues}
    assert {(qc.ERROR, "DAYS"), (qc.ERROR, "RANGE"), (qc.WARN, "SUM"), (qc.WARN, "GROUP")} <= codes
    t2 = _tm()
    t2.kind = ""
    assert (qc.ERROR, "KIND") in {(i.level, i.code) for i in tmod.check_techmap(t2).issues}
    t3 = _tm()
    t3.days["Апрель"] = 0
    assert (qc.WARN, "DAYS") in {(i.level, i.code) for i in tmod.check_techmap(t3).issues}


def test_match_group_and_library_roundtrip(tmp_path):
    p = Project()
    p.add_group("ГСП-1")
    assert tmod.match_group(p, "1") == "ГСП-1" and tmod.match_group(p, "7") is None
    tmod.add_to_library(p, _tm())
    with pytest.raises(ValueError):
        tmod.add_to_library(p, _tm())
    p.save(str(tmp_path))
    back = Project.load(str(tmp_path))
    t = tmod.TechMap.from_dict(back.techmaps["Карта"])
    assert t.volumes == _tm().volumes and t.totals == _tm().totals
    tmod.remove_from_library(back, "Карта")
    with pytest.raises(KeyError):
        tmod.remove_from_library(back, "Карта")


def test_not_a_techmap(tmp_path):
    import pandas as pd
    f = tmp_path / "x.xlsx"
    pd.DataFrame([["а", "б"], [1, 2]]).to_excel(f, header=False, index=False)
    with pytest.raises(ValueError):
        tmod.read_techmap(str(f))


@have
def test_api_import_save_delete(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    monkeypatch.setattr(api, "FOLDER", str(tmp_path / "proj"))
    c = TestClient(api.build_app())
    r = c.post("/api/techmap/read", json={"path": INJ, "name": "Закачка 2025"}).json()
    assert r["techmap"]["kind"] == "закачка" and r["techmap"]["name"] == "Закачка 2025"
    assert any("нет в проекте" in i["message"] for i in r["issues"])
    st = c.post("/api/techmap/save", json={"techmap": r["techmap"]}).json()
    assert st["techmaps"][0]["groups"] == 9
    assert c.post("/api/techmap/save", json={"techmap": r["techmap"]}).status_code == 400
    assert c.get("/api/techmap", params={"name": "Закачка 2025"}).json()["techmap"]["days"]["Октябрь"] == 15
    assert c.post("/api/techmap/delete", json={"name": "Закачка 2025"}).json()["techmaps"] == []
    assert c.post("/api/techmap/read", json={"path": "/нет"}).status_code == 404
