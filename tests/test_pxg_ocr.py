from __future__ import annotations

import sys
import time
import zipfile

import pytest
from starlette.testclient import TestClient

from pxg_ocr import api, engine

FAKE = r'''
import sys, zipfile
out = sys.argv[1]
with zipfile.ZipFile(out, "w") as z:
    z.writestr("doc/doc.md", "# Заголовок\n\nТекст")
    z.writestr("doc/doc_middle.json", "{\"pdf_info\": []}")
    z.writestr("doc/images/a.jpg", "x")
'''


@pytest.fixture()
def env(tmp_path, monkeypatch):
    home = tmp_path / "ocr"
    (home / "mineru-home").mkdir(parents=True)
    (home / "python").mkdir()
    exe = home / "python" / "python.exe"
    exe.write_text("")
    monkeypatch.setenv("PXG_OCR_HOME", str(home))
    monkeypatch.setenv("PXG_OCR_OUT", str(tmp_path / "out"))
    monkeypatch.setattr(engine, "python_exe", lambda h: exe)
    monkeypatch.setattr(engine, "hardware", lambda: {"cores": 16, "gpu": None})
    return tmp_path


def _fake_cmd(code):
    def build(py, src, out_zip, tier, ocr_mode, pages):
        return [sys.executable, "-c", code, out_zip]
    return build


def _wait(job_id, timeout=15):
    t = time.time()
    while time.time() - t < timeout:
        j = engine.get(job_id)
        if j.state in ("done", "error", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("не дождались")


def test_plan_gpu_limits_vram():
    hw = {"cores": 16, "gpu": {"name": "RTX 4060 Ti", "total_gb": 8.0, "free_gb": 7.0}}
    p = engine.plan("auto", hw)
    assert p["mode"] == "gpu" and p["vram_gb"] == 5.0 and p["threads"] == 8
    env = engine.build_env(__import__("pathlib").Path("C:/OCR"), p)
    assert env["MINERU_VIRTUAL_VRAM_SIZE"] == "5" and "MINERU_DEVICE_MODE" not in env


def test_plan_weak_gpu_goes_to_cpu():
    hw = {"cores": 4, "gpu": {"name": "GTX 1650", "total_gb": 4.0, "free_gb": 3.6}}
    p = engine.plan("auto", hw)
    assert p["mode"] == "cpu" and p["threads"] == 2
    env = engine.build_env(__import__("pathlib").Path("C:/OCR"), p)
    assert env["MINERU_DEVICE_MODE"] == "cpu" and "MINERU_VIRTUAL_VRAM_SIZE" not in env
    assert engine.plan("cpu", {"cores": 8, "gpu": None})["mode"] == "cpu"


def test_job_done_and_files(env, monkeypatch):
    monkeypatch.setattr(engine, "build_cmd", _fake_cmd(FAKE))
    src = env / "scan.pdf"
    src.write_bytes(b"%PDF")
    c = TestClient(api.build_app())
    r = c.post("/api/ocr/start", json={"path": str(src)})
    job = _wait(r.json()["jobs"][0])
    assert job.state == "done", job.error
    snap = c.get("/api/ocr/job", params={"id": job.id}).json()
    assert snap["result"]["md"].endswith(".md") and snap["result"]["json"].endswith("middle.json")
    f = c.get("/api/ocr/file", params={"dir": snap["dir"], "name": snap["result"]["md"]})
    assert "Заголовок" in f.text
    assert c.get("/api/ocr/file", params={"dir": snap["dir"], "name": "../../etc/passwd"}).status_code == 404
    assert c.get("/api/ocr/history").json()["items"][0]["state"] == "done"
    assert c.post("/api/ocr/delete", json={"dir": snap["dir"]}).json()["ok"]
    assert not c.get("/api/ocr/history").json()["items"]


def test_job_error_explained(env, monkeypatch):
    monkeypatch.setattr(engine, "build_cmd", _fake_cmd("import sys; print('CUDA out of memory'); sys.exit(1)"))
    src = env / "a.png"
    src.write_bytes(b"x")
    job = _wait(engine.start(str(src)).id)
    assert job.state == "error" and "видеопамяти" in job.error


def test_bad_input(env):
    c = TestClient(api.build_app())
    assert c.post("/api/ocr/start", json={}).status_code == 400
    assert c.post("/api/ocr/start", json={"path": str(env / "nope.pdf")}).status_code == 400
    bad = env / "x.exe"
    bad.write_bytes(b"x")
    assert "не читается" in c.post("/api/ocr/start", json={"path": str(bad)}).json()["error"]
    ok = env / "x.pdf"
    ok.write_bytes(b"x")
    assert c.post("/api/ocr/start", json={"path": str(ok), "pages": "1; rm"}).status_code == 400


def test_zip_slip_blocked(tmp_path):
    z = tmp_path / "r.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        engine._safe_extract(z, tmp_path / "d")
