"""Проверка веб-запуска «Базы ПХГ»: реестр, проверка формы, фоновый запуск модуля."""
import os
import sys
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("pandas")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient  # noqa: E402

from pxg_base.api import app  # noqa: E402


def test_modules_and_validation():
    c = TestClient(app)
    mods = c.get("/api/modules").json()["modules"]
    assert sum(1 for m in mods if m["web"]) == 24 and all(m["command"] for m in mods)
    r = c.post("/api/jobs", json={"module": "Нулевые_расходы_и_несоответствия_часов", "params": {}})
    assert r.status_code == 400 and "Корневая папка" in r.json()["error"]
    assert c.post("/api/jobs", json={"module": "нет_такого", "params": {}}).status_code == 404


def test_run_zero_flow_on_empty_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    (tmp_path / "data" / "Отбор").mkdir(parents=True)
    (tmp_path / "data" / "Закачка").mkdir()
    c = TestClient(app)
    job = c.post("/api/jobs", json={"module": "Нулевые_расходы_и_несоответствия_часов",
                                   "params": {"root": str(tmp_path / "data"), "mode": "2"}}).json()
    for _ in range(120):
        job = c.get("/api/jobs/" + job["id"]).json()
        if job["status"] != "running":
            break
        time.sleep(0.5)
    assert job["status"] == "done"
    assert any("Несоответствий не найдено" in line for line in job["log"])


SAMPLES = os.environ.get("SCHEDULE_TR_SAMPLES") or "/mnt/project-files/schedule-tr-samples"
SCHEDULE_MODULE = "Создание_schedule_файла_технологического_режима"


def _wait(c, job):
    for _ in range(240):
        job = c.get("/api/jobs/" + job["id"]).json()
        if job["status"] != "running":
            break
        time.sleep(0.5)
    return job


def test_schedule_tr_stops_with_message_when_files_missing(tmp_path, monkeypatch):
    """Пустая корневая папка: окон нет, форма получает понятную ошибку и статус «failed»."""
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    (tmp_path / "data").mkdir()
    c = TestClient(app)
    r = c.post("/api/jobs", json={"module": SCHEDULE_MODULE, "params": {"mode": "закачка", "root": str(tmp_path / "data"), "year": "2025"}})
    assert r.status_code == 200
    job = _wait(c, r.json())
    assert job["status"] == "failed"
    assert any("не найдены файлы" in line for line in job["log"])


def test_schedule_tr_variation_mode_is_console_only(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    (tmp_path / "data").mkdir()
    c = TestClient(app)
    job = c.post("/api/jobs", json={"module": SCHEDULE_MODULE, "params": {"mode": "прогноз_варьирование", "root": str(tmp_path / "data"), "year": "2025"}}).json()
    job = _wait(c, job)
    assert job["status"] == "failed" and any("редактора стратегий" in line for line in job["log"])


@pytest.mark.skipif(not os.path.isdir(SAMPLES), reason="образцы schedule-tr-samples недоступны")
def test_schedule_tr_on_samples(tmp_path, monkeypatch):
    """Все три режима на образцах: закачка и отбор дают schedule.inc с датами сезона, прогноз — варианты по процентам."""
    import shutil
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    root = tmp_path / "data"
    (root / "Закачка").mkdir(parents=True)
    (root / "Отбор").mkdir()
    for name in ("ГСП_8_a", "ГСП_9_a", "Утвержденные_объемы_закачка", "Посуточная_закачка"):
        shutil.copy(os.path.join(SAMPLES, name + ".xlsx"), str(root / "Закачка"))
    for name in ("ГСП_8_b", "ГСП_9_b", "Утвержденные_объемы_отбор", "Посуточные_отборы"):
        shutil.copy(os.path.join(SAMPLES, name + ".xlsx"), str(root / "Отбор"))
    (root / "period_of_work.txt").write_text("01.04.2027 inj\n16.10.2027 none\n", encoding="utf-8")
    prod_periods = tmp_path / "periods_prod.txt"
    prod_periods.write_text("01.11.2025 prod\n15.04.2026 none\n", encoding="utf-8")
    cycle_periods = tmp_path / "periods_cycle.txt"
    cycle_periods.write_text("01.04.2027 inj\n16.10.2027 none\n01.11.2027 prod\n01.05.2028 none\n", encoding="utf-8")
    c = TestClient(app)

    def run(params):
        job = c.post("/api/jobs", json={"module": SCHEDULE_MODULE, "params": dict(params, root=str(root))}).json()
        job = _wait(c, job)
        assert job["status"] == "done", "\n".join(job["log"][-15:])
        return job

    inj = run({"mode": "закачка", "year": "2027"})
    assert "04_Schedule_ЗАКАЧКИ/schedule.inc" in inj["files"] and "02_БД_расходов_ЗАКАЧКИ/Сводка_закачка.xlsx" in inj["files"]
    prod = run({"mode": "отбор", "year": "2025", "start": "01.11.2025", "end": "15.04.2026", "periods": str(prod_periods)})
    text = open(os.path.join(prod["out_dir"], "04_Schedule_ОТБОРА", "schedule.inc"), encoding="utf-8").read()
    assert "1\tNOV\t2025" in text and "30\tMAR\t2026" in text and "WCONHIST" in text  # сезон отбора, а не закачки 2027
    fc = run({"mode": "прогноз", "year": "2027", "forecast_years": "1", "percents": "80, 100", "periods": str(cycle_periods)})
    short = c.post("/api/jobs", json={"module": SCHEDULE_MODULE, "params": {"mode": "прогноз", "root": str(root), "year": "2027"}}).json()
    short = _wait(c, short)
    assert short["status"] == "failed" and any("полный цикл" in line for line in short["log"])
    assert {"04_Schedule_ПРОГНОЗ/Сценарий_80процентов/schedule_80proc.inc", "04_Schedule_ПРОГНОЗ/Сценарий_100процентов/schedule_100proc.inc"} <= set(fc["files"])
