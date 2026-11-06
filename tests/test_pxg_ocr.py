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


def test_plan_gpu_limits_vram(monkeypatch):
    monkeypatch.setattr(engine, "GPU_SUPPORTED", True)
    hw = {"cores": 16, "gpu": {"name": "RTX 4060 Ti", "total_gb": 8.0, "free_gb": 7.0}}
    p = engine.plan("auto", hw)
    assert p["mode"] == "gpu" and p["vram_gb"] == 5.0 and p["threads"] == 8
    env = engine.build_env(__import__("pathlib").Path("C:/OCR"), p)
    assert env["MINERU_VIRTUAL_VRAM_SIZE"] == "5" and "MINERU_DEVICE_MODE" not in env


def test_plan_linux_auto_does_not_use_gpu(monkeypatch):
    monkeypatch.setattr(engine, "GPU_SUPPORTED", False)
    p = engine.plan("auto", {"cores": 16, "gpu": {"name": "RTX 4060 Ti", "total_gb": 8.0, "free_gb": 7.0}})
    assert p["mode"] == "cpu" and "процессоре" in p["why"]


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


def test_make_db(env, monkeypatch):
    monkeypatch.setattr(engine, "build_cmd", _fake_cmd(FAKE.replace("# Заголовок\\n\\nТекст", "## Отчёт о гидродинамическом исследовании\\n\\n<table><tr><td>Скважина</td><td>533</td></tr></table>")))
    src = env / "a.pdf"
    src.write_bytes(b"%PDF")
    c = TestClient(api.build_app())
    job = _wait(c.post("/api/ocr/start", json={"path": str(src)}).json()["jobs"][0])
    r = c.post("/api/ocr/db", json={"dir": str(job.dir)}).json()
    assert r["kind"] == "gdi" and (job.dir / "db.xlsx").is_file()
    assert c.post("/api/ocr/db", json={"dir": str(env)}).status_code == 404


def test_export_docx_tables_and_collect(env, monkeypatch):
    tbl = "<table><tr><td>Глубина, м</td><td>Температура</td><td>Давление</td></tr><tr><td>800</td><td>30</td><td>80</td></tr></table>"
    md = "# Отчёт\\n\\nСкважина: 12\\n\\nДата исследования: 01.03.2025\\n\\n" + tbl
    monkeypatch.setattr(engine, "build_cmd", _fake_cmd(FAKE.replace("# Заголовок\\n\\nТекст", md)))
    src = env / "a.pdf"
    src.write_bytes(b"%PDF")
    c = TestClient(api.build_app())
    job = _wait(c.post("/api/ocr/start", json={"path": str(src)}).json()["jobs"][0])
    r = c.post("/api/ocr/docx", json={"dir": str(job.dir)}).json()
    assert r["file"] == "a.docx" and r["tables"] == 1 and (job.dir / "a.docx").is_file()
    r = c.post("/api/ocr/tables", json={"dir": str(job.dir)}).json()
    assert r["file"] == "tables.xlsx" and r["sheets"][0]["name"] == "Термобарика" and (job.dir / "tables.xlsx").is_file()
    r = c.post("/api/ocr/collect", json={"scope": "all"}).json()
    assert r["files"] == 1 and (engine.out_root() / "Сводные" / r["file"]).is_file()
    assert c.post("/api/ocr/docx", json={"dir": str(env)}).status_code == 404


def test_manual_gpu_mode_works_on_linux_but_auto_stays_on_cpu(monkeypatch):
    monkeypatch.setattr(engine, "GPU_SUPPORTED", False)
    hw = {"cores": 8, "gpu": {"name": "RTX 3050", "total_gb": 4.0, "free_gb": 3.6}}
    assert engine.plan("auto", hw)["mode"] == "cpu"
    p = engine.plan("gpu", hw)
    assert p["mode"] == "gpu" and p["vram_gb"] == 3.1 and "мало" in p["why"]
    assert engine.plan("gpu", {"cores": 8, "gpu": None})["mode"] == "cpu"


def test_gpu_diag_never_raises_without_driver(env, monkeypatch):
    monkeypatch.setattr(engine, "_run_text", lambda cmd, timeout=20: "нет")
    monkeypatch.setattr("shutil.which", lambda name: None)
    lines = engine.gpu_diag()
    assert any("nvidia-smi не найден" in l for l in lines) and any(l.startswith("Режим gpu") for l in lines)
    assert TestClient(api.build_app()).get("/api/ocr/gpu").json()["lines"]


def test_db_all_merges_files_and_registers_unrecognised(env, monkeypatch):
    gdi = "## Отчёт о гидродинамическом исследовании\\n\\n<table><tr><td>Скважина</td><td>533</td></tr></table>"
    fake = lambda body: FAKE.replace("# Заголовок\\n\\nТекст", body)  # noqa: E731
    c = TestClient(api.build_app())
    for n, body in (("a", gdi), ("b", gdi), ("c", "Просто текст без вида документа")):
        monkeypatch.setattr(engine, "build_cmd", _fake_cmd(fake(body)))
        src = env / (n + ".pdf")
        src.write_bytes(b"%PDF")
        _wait(c.post("/api/ocr/start", json={"path": str(src)}).json()["jobs"][0])
    r = c.post("/api/ocr/db-all", json={"scope": "all"}).json()
    assert r["files"] == 3 and r["recognised"] == 2
    names = [s["name"] for s in r["sheets"]]
    assert names[-1] == "Файлы" and len(names) >= 2
    reg = r["sheets"][-1]["rows"]
    assert sum(1 for row in reg if row[3]) == 1                      # нераспознанный файл назван с замечанием
    assert (engine.out_root() / "Сводные" / r["file"]).is_file()
