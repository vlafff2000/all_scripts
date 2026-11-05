"""Выбор пути для файла: Word и PDF с текстом — скриптом, сканы и картинки — OCR; ручной выбор главнее."""
from __future__ import annotations

import sys

import pytest
from starlette.testclient import TestClient

from pxg_ocr import api, batch, engine, route
from test_pxg_ocr import FAKE, _fake_cmd, env  # noqa: F401  (фикстура движка-заглушки)


def _pdf(path, text):
    """PDF из одной страницы: с текстом (text, латиница) или пустая страница (скан без текстового слоя)."""
    stream = ("BT /F1 12 Tf 20 150 Td (%s) Tj ET" % text).encode("ascii") if text else b""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    path.write_bytes(out)


def test_word_and_images_by_extension(tmp_path):
    assert route.classify(str(tmp_path / "a.docx"))["route"] == "script"
    assert route.classify(str(tmp_path / "a.doc"))["route"] == "script"
    assert route.classify(str(tmp_path / "a.jpg"))["route"] == "ocr"


def test_pdf_scan_vs_text(tmp_path):
    scan = tmp_path / "scan.pdf"
    _pdf(scan, "")
    text = tmp_path / "text.pdf"
    _pdf(text, "Zakluchenie po rezultatam interpretacii dannyh GIS skvazhina 118")
    s, t = route.classify(str(scan)), route.classify(str(text))
    assert s["route"] == "ocr" and s["kind"] == "pdf_scan" and s["text_pages"] == 0
    assert t["route"] == "script" and t["kind"] == "pdf_text" and t["text_pages"] == 1


def test_manual_override_wins(tmp_path):
    scan = tmp_path / "scan.pdf"
    _pdf(scan, "")
    r = route.classify(str(scan), "script")
    assert r["route"] == "script" and r["auto"] == "ocr" and r["manual"] and "вручную" in r["reason"]
    assert route.classify(str(tmp_path / "x.docx"), "ocr")["route"] == "ocr"


def test_api_route(tmp_path):
    c = TestClient(api.build_app())
    r = c.post("/api/ocr/route", json={"paths": [str(tmp_path / "a.docx"), str(tmp_path / "b.png")], "overrides": {str(tmp_path / "b.png"): "script"}}).json()
    assert [i["route"] for i in r["items"]] == ["script", "script"]
    assert r["items"][1]["manual"] is True


def test_batch_ocr_only_scans(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(engine, "build_cmd", _fake_cmd(FAKE))
    src = env / "src"
    (src / "sub").mkdir(parents=True)
    _pdf(src / "scan.pdf", "")
    _pdf(src / "sub" / "scan.pdf", "")
    _pdf(src / "text.pdf", "Zakluchenie po rezultatam interpretacii dannyh GIS skvazhina 118")
    (src / "report.docx").write_bytes(b"x")
    out = env / "ocr_md"
    rows = batch.run([str(src)], str(out), mode="cpu")
    by = {r["path"].replace("\\", "/").split("/src/")[1]: r for r in rows}
    assert by["report.docx"]["status"] == "скрипт" and by["text.pdf"]["status"] == "скрипт"
    assert by["scan.pdf"]["status"].startswith("готово") and by["sub/scan.pdf"]["status"].startswith("готово")
    assert sorted(p.name for p in out.glob("*.ocr.md")) == ["scan.ocr.md", "sub__scan.ocr.md"]
    again = batch.run([str(src)], str(out), mode="cpu")
    assert all(r["status"] in ("скрипт", "уже распознано") for r in again)
