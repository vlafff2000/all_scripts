"""Модули расходов на сгенерированных исходниках (pxg_base.testdata.flows): запуск как в веб-интерфейсе, сверка с манифестом."""
import os
import sys
import time

import pytest

pytest.importorskip("starlette")
pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
pytest.importorskip("xlsxwriter")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient  # noqa: E402

from pxg_base.api import app  # noqa: E402
from pxg_base.testdata.flows import make_flow_tree  # noqa: E402

SUMMARY = "Сводка_закачка_отбор_обновленный_скрипт.xlsx"
MISMATCH = "Часы_ненулевые_расход_нулевой.xlsx"


def run_module(client, module, params, timeout=180):
    job = client.post("/api/jobs", json={"module": module, "params": params}).json()
    assert "error" not in job, job
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get("/api/jobs/" + job["id"]).json()
        if job["status"] != "running":
            return job
        time.sleep(0.5)
    raise AssertionError("модуль не завершился за %d с" % timeout)


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    base = tmp_path_factory.mktemp("flows")
    return make_flow_tree(base / "data")


def real_rows(df):
    """Строки «Итого» под таблицами расходов в базу попадать не должны."""
    assert not (df["Скважина"].astype(str).str.lower().str.startswith("итого")).any()
    return df


def test_generator_is_deterministic(tmp_path):
    a = make_flow_tree(tmp_path / "a")
    b = make_flow_tree(tmp_path / "b")
    assert a.planted == b.planted and a.rows == b.rows
    assert [p.relative_to(a.root).as_posix() for p in a.files] == [
        "Отбор/2023-2024/Результаты работы скважин отбор 2023-2024гг/Отбор_2023-2024.xlsx",
        "Закачка/2024/Результаты работы скважин в закачку 2024гг/Закачка_2024.xlsx"]


def test_zero_flow_finds_exactly_planted_cases(tree, tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    job = run_module(TestClient(app), "нулевой_расход", {"root": str(tree.root), "mode": "1"})
    assert job["status"] == "done", "\n".join(job["log"][-15:])
    assert {SUMMARY, MISMATCH} <= set(job["files"])
    out = job["out_dir"]
    book = pd.read_excel(os.path.join(out, SUMMARY), sheet_name=None)
    assert len(real_rows(book["Отборы"])) == tree.rows["отбор"]
    assert len(real_rows(book["Закачка"])) == tree.rows["закачка"]
    found = real_rows(pd.read_excel(os.path.join(out, MISMATCH)))
    got = sorted((r["Тип данных"], pd.Timestamp(r["Дата"]).date(), str(r["Скважина"]), r["Тип_несоответствия"])
                 for _, r in found.iterrows())
    assert got == sorted(tree.planted)


def test_zero_flow_only_mismatch_mode(tree, tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    job = run_module(TestClient(app), "нулевой_расход", {"root": str(tree.root), "mode": "2"})
    assert job["status"] == "done"
    assert MISMATCH in job["files"] and SUMMARY not in job["files"]


def test_create_db_applies_periods(tree, tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    job = run_module(TestClient(app), "создание_БД_расходов",
                     {"root": str(tree.root), "periods": str(tree.periods_file)})
    assert job["status"] == "done", "\n".join(job["log"][-15:])
    book = pd.read_excel(os.path.join(job["out_dir"], SUMMARY), sheet_name=None)
    prod, inj = real_rows(book["Отборы"]), real_rows(book["Закачка"])
    assert len(prod) == tree.rows_after_periods["отбор"] < tree.rows["отбор"]
    assert len(inj) == tree.rows_after_periods["закачка"] < tree.rows["закачка"]
    assert int((prod["Тип данных"] == "нейтральный период").sum()) == tree.neutral_rows
    assert set(prod["Скважина"].astype(str)) == set(tree.wells)
    # несоответствия по уже отфильтрованным данным: ровно те, что попали в нужные периоды
    found = [(r["Тип данных"], pd.Timestamp(r["Дата"]).date(), str(r["Скважина"]), r["Тип_несоответствия"])
             for _, r in real_rows(pd.read_excel(os.path.join(job["out_dir"], MISMATCH))).iterrows()]
    assert sorted(found) == sorted((k, d, w, v)
                                   for k, d, w, v in tree.planted_after_periods)
