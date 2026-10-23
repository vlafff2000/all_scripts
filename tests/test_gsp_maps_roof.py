"""«Карты»: кровля пласта из модели (gsp_maps/roof.py)."""
import pytest

from gsp_maps import roof
from tests.test_tnav_indicators import _egrid


def test_roof_grid_layer_tops_are_negative_tvdss(tmp_path):
    _egrid(tmp_path / "M.EGRID")
    r = roof.roof_grid(str(tmp_path / "M.EGRID"), 2)
    flat = [v for row in r["z"] for v in row if v is not None]
    assert flat and set(flat) == {-1010.0} and r["layers"] == 3        # слои 1000–1010–1020–1030, верх 2-го слоя 1010
    top = roof.roof_grid(str(tmp_path / "M.EGRID"), 0)
    assert {v for row in top["z"] for v in row if v is not None} == {-1000.0}


def test_roof_layer_out_of_range_is_a_clear_error(tmp_path):
    _egrid(tmp_path / "M.EGRID")
    with pytest.raises(ValueError, match="слоёв"):
        roof.roof_grid(str(tmp_path / "M.EGRID"), 9)
    with pytest.raises(ValueError, match="EGRID"):
        roof.roof_grid(str(tmp_path / "нет.SMSPEC"), 1)


def test_same_size_grid_is_read_once_for_all_models(tmp_path):
    from unittest import mock
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    _egrid(tmp_path / "a" / "A.EGRID"); _egrid(tmp_path / "b" / "B.EGRID")
    roof._cache.clear()
    with mock.patch.object(roof, "load_model", wraps=roof.load_model) as load:
        first = roof.roof_grid(str(tmp_path / "a" / "A.EGRID"), 1)
        second = roof.roof_grid(str(tmp_path / "b" / "B.EGRID"), 1)
    assert load.call_count == 1 and first["z"] == second["z"] and "A.EGRID" in second["note"] and "A.EGRID" not in first["note"]


def test_roof_endpoint_reports_every_failure_and_logs_traceback(tmp_path, caplog, monkeypatch):
    pytest.importorskip("pyarrow")
    from starlette.testclient import TestClient
    from gsp_maps import api
    _egrid(tmp_path / "M.EGRID")
    client = TestClient(api.build_app(), raise_server_exceptions=False)
    ok = client.get("/api/roof", params={"model": str(tmp_path / "M.EGRID"), "layer": 1})
    assert ok.status_code == 200 and "mapaxes" in ok.json()
    # известная ошибка: сообщение на экране и запись в лог
    with caplog.at_level("WARNING"):
        bad = client.get("/api/roof", params={"model": str(tmp_path / "нет.EGRID"), "layer": 1})
    assert bad.status_code == 400 and "Кровля из модели не построена" in bad.json()["error"]
    assert any("Кровля из модели не построена" in r.getMessage() for r in caplog.records)

    # непредвиденная ошибка: не пустой экран, а понятный текст; трассировка в логе
    def boom(*a, **k):
        raise TypeError("странный файл")
    monkeypatch.setattr(roof, "roof_grid", boom)
    caplog.clear()
    with caplog.at_level("ERROR"):
        r = client.get("/api/roof", params={"model": str(tmp_path / "M.EGRID"), "layer": 1})
    assert r.status_code == 500 and "TypeError" in r.json()["error"] and "Лог" in r.json()["error"]
    assert any(rec.exc_info for rec in caplog.records)


def test_client_log_endpoint_writes_to_log(caplog):
    pytest.importorskip("pyarrow")
    from starlette.testclient import TestClient
    from gsp_maps import api
    with caplog.at_level("WARNING"):
        r = TestClient(api.build_app()).post("/api/client-log", json={"where": "кровля", "text": "вне карты скважин"})
    assert r.status_code == 200 and any("вне карты скважин" in x.getMessage() for x in caplog.records)
