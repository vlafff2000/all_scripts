"""Проверка данных: «ненормальные» строки находятся и исключаются из расчётов, исходные файлы не меняются."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import dataquality as dq, sources as src  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402


def _db(tmp_path):
    d = pd.date_range("2025-11-01", periods=12)
    rows = [("101", x, 100.0, 24.0, "Отбор") for x in d]
    rows[3] = ("101", d[3], 900.0, 24.0, "Отбор")        # скачок
    rows[5] = ("101", d[5], 0.0, 24.0, "Отбор")          # ноль посреди работы
    rows[7] = ("101", d[7], -5.0, 24.0, "Отбор")         # отрицательный
    rows.append(("101", d[0], 100.0, 24.0, "Отбор"))     # повтор даты
    rows += [("102", x, 50.0, 30.0, "Отбор") for x in d[:4]]   # часы вне 0–24
    df = pd.DataFrame(rows, columns=["Скважина", "Дата", "Суточный расход газа", "Время работы", "Тип данных"])
    df["Часовой расход газа"] = 1.0
    f = str(tmp_path / "БД.xlsx")
    df.to_excel(f, index=False)
    return f


def test_scan_finds_expected_checks(tmp_path):
    p = Project()
    src.set_flows(p, [_db(tmp_path)])
    found = dq.scan(src.load_project_history(p, raw=True), None)
    checks = set(found["check"])
    assert {"Отрицательный расход", "Повтор даты", "Скачок расхода", "Ноль посреди работы", "Часы работы вне 0–24"} <= checks
    assert found[found["check"] == "Часы работы вне 0–24"]["well"].eq("102").all()
    assert dq.summary(found)["count"].sum() == len(found)


def test_exclusion_removes_rows_from_history_and_restores(tmp_path):
    p = Project()
    src.set_flows(p, [_db(tmp_path)])
    raw = src.load_project_history(p, raw=True)
    found = dq.scan(raw, None)
    neg = found[found["check"] == "Отрицательный расход"]["id"].tolist()
    assert len(neg) == 1
    src.set_excluded(p, neg, True)
    cur = src.load_project_history(p)
    assert len(cur) == len(raw) - 1 and (cur["rate"] >= 0).all()
    assert len(src.load_project_history(p, raw=True)) == len(raw)       # исходные данные целы
    src.set_excluded(p, neg, False)
    assert len(src.load_project_history(p)) == len(raw)


def test_daily_total_checked_and_excluded(tmp_path):
    f = str(tmp_path / "эталон.xlsx")
    d = pd.date_range("2025-11-01", periods=8)
    pd.DataFrame({"Дата": d, "Объем": [10, 10, 10, 90, 10, 10, 10, 10]}).to_excel(f, index=False)
    p = Project()
    src.set_daily_total(p, f)
    found = dq.scan(None, src.load_daily_total(p, raw=True))
    jump = found[found["check"] == "Скачок расхода"]
    assert len(jump) == 1 and jump.iloc[0]["dataset"] == dq.DAILY
    src.set_excluded(p, jump["id"].tolist(), True)
    assert len(src.load_daily_total(p)) == 7


def test_api_quality_flow(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    Project().save(folder)
    c = TestClient(api.build_app())
    assert c.get("/api/quality").status_code == 404                      # нет источников — понятный ответ
    assert c.post("/api/sources/set", json={"flows": {"paths": [_db(tmp_path)]}}).status_code == 200
    v = c.get("/api/quality", params={"jump": 3}).json()
    assert v["total"] > 0 and v["errors"] > 0 and v["excluded"] == 0
    r = c.post("/api/quality/exclude", json={"level": "ошибка"}).json()
    assert r["changed"] > 0 and r["excluded"] > 0
    v2 = c.get("/api/quality").json()
    assert v2["excluded"] == r["excluded"] and any(x["excluded"] for x in v2["rows"]) and v2["excludedRows"]
    assert c.post("/api/quality/exclude", json={"all_restore": True}).json()["excluded"] == 0
