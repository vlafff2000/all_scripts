"""R2: источники проекта, автосоздание скважин и групп, перенос старых настроек осреднения."""
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import avg_view, history as hist, sources as src  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402
from tests.test_schedule_scenarios import _lib  # noqa: E402

SAMPLES = "/mnt/project-files/schedule-tr-samples"


def _db(tmp_path, group_col=False):
    rows = []
    for y, sh in ((2022, (.5, .3, .2)), (2023, (.4, .4, .2))):
        for mo in (5, 6):
            for w, g, s in zip(("101", "102", "215"), ("ГСП 1", "ГСП 1", "СП 3"), sh):
                rows.append({"Скважина": w, "Дата": "10.%02d.%d" % (mo, y), "Суточный расход газа": 100.0 * s,
                             "Часовой расход газа": 1.0, "Время работы": 24.0, "Тип данных": "Закачка", "Группа": g})
    df = pd.DataFrame(rows)
    if not group_col:
        df = df.drop(columns="Группа")
    f = str(tmp_path / "БД.xlsx")
    df.to_excel(f, index=False)
    return f


def _split(tmp_path, rows):
    f = str(tmp_path / "разбивка.xlsx")
    pd.DataFrame(rows, columns=["Номер скважины", "ГСП/СП"]).to_excel(f, index=False)
    return f


def test_groups_from_separate_file_equal_level(tmp_path):
    p = Project()
    src.set_flows(p, [_db(tmp_path)])
    src.set_groups(p, "file", _split(tmp_path, [("101", "ГСП 1"), ("102", "ГСП 1"), ("215", "СП 3")]))
    rep = src.build_project_wells(p)
    assert set(p.wells) == {"101", "102", "215"}
    assert p.groups == {"ГСП 1": None, "СП 3": None}          # один уровень, имена ровно как в файле
    assert p.well_group == {"101": "ГСП 1", "102": "ГСП 1", "215": "СП 3"}
    assert not [i for i in rep.issues if i.level == "ошибка"]
    # повторный запуск ничего не дублирует
    src.build_project_wells(p)
    assert len(p.wells) == 3 and len(p.groups) == 2


def test_groups_from_column_in_flows(tmp_path):
    p = Project()
    src.set_flows(p, [_db(tmp_path, group_col=True)])
    src.set_groups(p, "column")
    src.build_project_wells(p)
    assert p.well_group == {"101": "ГСП 1", "102": "ГСП 1", "215": "СП 3"}


def test_conflicts_and_gaps_are_reported_not_raised(tmp_path):
    p = Project()
    src.set_flows(p, [_db(tmp_path)])
    src.set_groups(p, "file", _split(tmp_path, [("101", "ГСП 1"), ("101", "СП 3"), ("999", "ГСП 1")]))
    p.techmaps = _lib()                                         # группа «1» тех.карты → нет в проекте
    rep = src.build_project_wells(p)
    msgs = [(i.level, i.message) for i in rep.issues]
    assert any(l == "ошибка" and "нескольких группах" in m for l, m in msgs)
    assert any("не найдена в базе" in m for _, m in msgs)
    assert any("без группы" in m for _, m in msgs)
    assert any("тех.карты" in m for _, m in msgs)
    assert "101" not in p.well_group                            # спорная скважина не назначена


def test_source_overrides_old_assignment(tmp_path):
    p = Project()
    p.add_group("Старая")
    p.add_well("101", group="Старая")
    src.set_flows(p, [_db(tmp_path)])
    src.set_groups(p, "file", _split(tmp_path, [("101", "ГСП 1")]))
    rep = src.build_project_wells(p)
    assert p.well_group["101"] == "ГСП 1" and "изменено 1" in rep.checked[-1]


def test_no_sources_is_a_clear_error_in_report(tmp_path):
    p = Project()
    with pytest.raises(ValueError, match="истории"):
        src.load_project_history(p)
    rep = src.build_project_wells(p)                            # пустая выборка — не ошибка
    assert not p.wells and "создано 0" in rep.checked[-1]


def test_old_project_with_averaging_sources_opens(tmp_path):
    f = _db(tmp_path)
    folder = str(tmp_path / "old")
    Project("Старый").save(folder)
    os.remove(os.path.join(folder, "sources.json"))
    with open(os.path.join(folder, "averaging.json"), "w", encoding="utf-8") as fh:
        json.dump({"sources": [f], "params": {"max_years": 4}}, fh)
    p = Project.load(folder)
    assert src.flow_paths(p) == [f] and avg_view.sources(p) == [f] and "sources" not in p.averaging
    p.save(folder)
    assert Project.load(folder).sources["flows"]["paths"] == [f]


def test_history_cache_and_template_fallback(tmp_path):
    p = Project()
    f = _db(tmp_path)
    src.set_flows(p, [f])
    a = src.load_project_history(p, "закачка")
    assert len(a) == 12 and set(a["kind"]) == {"закачка"}
    assert len(src.load_project_history(p, "отбор")) == 0


def test_daily_total_unit(tmp_path):
    f = str(tmp_path / "эталон.xlsx")
    pd.DataFrame({"Дата": ["2026-05-01", "2026-05-02"], "Объем": [1.5, 2.0]}).to_excel(f, index=False)
    p = Project()
    assert src.load_daily_total(p).empty
    src.set_daily_total(p, f, "тыс.м3")
    assert src.load_daily_total(p)["Объем"].tolist() == [1500.0, 2000.0]


def test_api_flow_builds_wells_for_empty_project(tmp_path, monkeypatch):
    """R0: пустой проект + база + разбивка → скважины и группы есть, осреднение считается."""
    from starlette.testclient import TestClient
    from schedule_pxg import api
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    p = Project()
    p.techmaps = _lib()
    p.save(folder)
    c = TestClient(api.build_app())
    r = c.post("/api/sources/set", json={"flows": {"paths": [_db(tmp_path)]},
                                         "groups": {"mode": "file", "path": _split(tmp_path, [("101", "1"), ("102", "1"), ("215", "1")])}})
    assert r.status_code == 200
    r = c.post("/api/sources/build").json()
    assert r["wells"] == 3 and r["groups"] == 1 and r["withoutGroup"] == 0
    assert c.post("/api/sources/set", json={"flows": {"paths": ["/нет/файла.xlsx"]}}).status_code == 400
    assert r["techmaps"] == len(p.techmaps) and r["daily"] is None
    sample = c.get("/api/sources/sample")                 # образец формата разбивки читается тем же чтением
    assert sample.status_code == 200
    f = tmp_path / "образец.xlsx"
    f.write_bytes(sample.content)
    assert src.read_groups_file(str(f)) == {"101": ["ГСП 1"], "102": ["ГСП 1"], "103": ["ГСП 1"], "201": ["СП 2"], "202": ["СП 2"]}
    assert c.post("/api/check", json={}).status_code in (404, 405)   # проверочного Excel в импорте больше нет
    v = c.get("/api/averaging", params={"kind": "закачка"})
    assert v.status_code == 200 and {w["well"] for w in v.json()["wells"]} == {"101", "102", "215"}


@pytest.mark.skipif(not os.path.isdir(SAMPLES), reason="нет образцов")
def test_real_samples_load():
    p = Project()
    files = [os.path.join(SAMPLES, n) for n in ("ГСП_8_a.xlsx", "ГСП_9_a.xlsx")]
    src.set_flows(p, files)
    df = src.load_project_history(p)
    assert len(df) > 0 and (df["well"] != "").any()
    src.build_project_wells(p)
    assert len(p.wells) == df["well"].replace("", pd.NA).nunique()
