"""Единицы расходов проекта Атласа одинаковы для «Карт» и «ГДМ»: скважины — м³/сут, БД учёта газа — тыс. м³/сут."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from gsp_atlas_storage import write_project  # noqa: E402
from gsp_maps import atlas_source  # noqa: E402
from pxg_core import atlas_flows  # noqa: E402

DAYS = pd.date_range("2025-11-01", periods=3)


def test_core_units():
    assert atlas_flows.production_m3(pd.Series([250000.0, "x"])).tolist()[0] == 250000.0
    assert atlas_flows.production_thousand_m3(pd.Series([250000.0])).tolist() == [250.0]
    assert atlas_flows.gas_db_m3(pd.Series([250.0])).tolist() == [250000.0]


def test_maps_and_gdm_read_same_volume(tmp_path):
    """Скважина даёт 250 000 м³/сут, узел учёта — 250 тыс. м³/сут: один и тот же объём в обеих программах."""
    from schedule_pxg import atlas_data
    rows = [{"well": "11", "date": d, "q": 250000.0, "kind": "withdrawal", "season": "2025-2026", "year": "", "group": "ГСП 1"} for d in DAYS]
    gas = pd.DataFrame({"date": DAYS, "kind": "withdrawal", "gas": 250.0})
    root = write_project(tmp_path / "st", {"production": pd.DataFrame(rows), "gas_db": gas})
    arrays = atlas_source.AtlasData(root, "a" * 32).flow_arrays()
    assert arrays["flow"].tolist() == [250.0] * 3                       # Карты: тыс. м³/сут
    hist, ref, _name, _found, _groups = atlas_data.load(str(root))
    assert hist["rate"].tolist() == [250000.0] * 3                      # ГДМ: м³/сут
    assert ref["Объем"].tolist() == [250000.0] * 3                      # эталон — те же м³/сут, что и у скважины
