"""Единый лог программ: файл, обезличивание путей, ротация, пакет для отправки, запись запросов."""
import logging
import os
import sys
import zipfile

import pytest

pytest.importorskip("starlette")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.applications import Starlette  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from pxg_core import runlog  # noqa: E402


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_LOGS", str(tmp_path / "logs"))
    logger = logging.getLogger("pxg")
    old = list(logger.handlers)
    for h in old:
        logger.removeHandler(h)
    yield tmp_path / "logs"
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    for h in old:
        logger.addHandler(h)


def _flush():
    for h in logging.getLogger("pxg").handlers:
        h.flush()


def test_setup_writes_environment_and_actions(logs):
    runlog.setup("Тест")
    runlog.action("Тест: кнопка", папка=os.path.expanduser("~") + "/данные")
    with runlog.timed("чтение сетки", файл="a.EGRID") as t:
        t["кэш"] = "попал"
    runlog.summary("расчёт", скважин=5)
    _flush()
    text = (logs / "тест.log").read_text(encoding="utf8")
    for part in ("запуск «Тест»", "Версия сборки", "Ядер:", "PXG_WORKERS", "действие: Тест: кнопка", "~/данные",
                 "этап «чтение сетки»", "кэш=попал", "итог: расчёт; скважин=5"):
        assert part in text
    assert os.path.expanduser("~") + "/" not in text or os.path.expanduser("~") == "/"


def test_timed_logs_error_with_traceback(logs):
    runlog.setup("Тест", announce=False)
    with pytest.raises(ValueError):
        with runlog.timed("этап"):
            raise ValueError("плохо")
    _flush()
    text = (logs / "тест.log").read_text(encoding="utf8")
    assert "завершился ошибкой" in text and "ValueError: плохо" in text and "Traceback" in text


def test_rotation_is_bounded(logs, monkeypatch):
    monkeypatch.setattr(runlog, "MAX_BYTES", 2000)
    runlog.setup("Тест", announce=False)
    handler = next(h for h in logging.getLogger("pxg").handlers if getattr(h, "app", "") == "Тест")
    handler.maxBytes = 2000
    for i in range(200):
        runlog.action("строка %d" % i)
    _flush()
    names = sorted(p.name for p in logs.iterdir())
    assert "тест.log" in names and "тест.log.1" in names and len(names) <= runlog.BACKUPS + 1


def _app():
    async def ok(request):
        return PlainTextResponse("ok")

    async def boom(request):
        raise RuntimeError("сбой")

    return Starlette(routes=[Route("/api/ok", ok, methods=["GET", "POST"]), Route("/api/boom", boom), *runlog.routes()],
                     middleware=[Middleware(runlog.RequestLog)])


def test_requests_logged_and_bundle(logs):
    runlog.setup("Тест", announce=False)
    c = TestClient(_app(), raise_server_exceptions=False)
    c.get("/api/ok")                    # чтение без замечаний в лог не пишется
    c.post("/api/ok")
    assert c.get("/api/boom").status_code == 500
    r = c.post("/api/log/bundle").json()
    assert r["name"].endswith(".zip") and r["size"] > 0
    got = c.get(r["url"])
    assert got.status_code == 200 and got.content == (logs / "send" / r["name"]).read_bytes()
    z = zipfile.ZipFile(logs / "send" / r["name"])
    assert {"environment.txt", "тест.log"} <= set(z.namelist())
    text = z.read("тест.log").decode("utf8")
    assert "POST /api/ok -> 200" in text and "GET /api/ok" not in text
    assert "GET /api/boom: необработанная ошибка" in text and "RuntimeError: сбой" in text
    assert c.get("/api/log/download").status_code == 200
    assert c.get("/api/log").json()["files"]
    assert c.get("/api/log/bundle/..%2Fx.zip").status_code == 404


def test_log_dir_follows_project(tmp_path, monkeypatch):
    monkeypatch.delenv("PXG_LOGS", raising=False)
    proj = tmp_path / "Проект"
    proj.mkdir()
    monkeypatch.setenv("PXG_PROJECT", str(proj))
    assert runlog.log_dir() == proj / "logs"
