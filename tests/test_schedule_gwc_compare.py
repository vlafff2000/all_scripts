from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from schedule_pxg import gwc_compare as gc


def _daily(zero_ranges):
    days = pd.date_range("2024-04-01", "2025-06-30")
    vol = [0.0 if any(a <= d.date() <= b for a, b in zero_ranges) else 100.0 for d in days]
    return pd.DataFrame({"Дата": days, "Объем": vol})


D = dt.date
PAUSES = [(D(2024, 11, 5), D(2024, 11, 20)), (D(2025, 4, 3), D(2025, 4, 28))]


def test_pauses_and_slice_dates():
    ps = gc.pauses(_daily(PAUSES))
    assert ps == PAUSES
    assert gc.slice_date(D(2024, 11, 30), "осень", ps) == (D(2024, 11, 5), "начало паузы после закачки")
    assert gc.slice_date(D(2025, 4, 10), "весна", ps) == (D(2025, 4, 28), "конец паузы после отбора")
    assert gc.slice_date(D(2025, 7, 1), "", ps) == (D(2025, 7, 1), "дата замера")          # вне сезонов — дата замера
    assert gc.slice_date(D(2024, 11, 30), "осень", []) == (D(2024, 11, 30), "дата замера")
    short = gc.pauses(_daily([(D(2024, 11, 5), D(2024, 11, 7))]))
    assert short == []                                                                    # короче порога — не остановка


CELLS = [{"top": -900.0, "bottom": -910.0, "sg": 0.7}, {"top": -910.0, "bottom": -920.0, "sg": 0.5},
         {"top": -920.0, "bottom": -930.0, "sg": 0.0}, {"top": -930.0, "bottom": -940.0, "sg": 0.0}]


def test_gwc_in_pack_statuses():
    assert gc.gwc_in_pack(CELLS, 0.01, -895.0, -940.0) == (-920.0, gc.OK)
    assert gc.gwc_in_pack(CELLS, 0.01, -895.0, -915.0) == (-915.0, gc.NOT_REACHED)       # газ до подошвы пачки
    assert gc.gwc_in_pack(CELLS, 0.01, -925.0, -940.0) == (None, gc.NO_GAS)
    assert gc.gwc_in_pack(CELLS, 0.6, -895.0, -940.0) == (-910.0, gc.OK)                  # порог меняет контакт


def test_stats():
    s = gc.stats([-2.0, 0.5, 1.5])
    assert s["n"] == 3 and s["mean"] == pytest.approx(0.0) and s["median"] == 0.5 and s["mae"] == pytest.approx(4 / 3)
    assert s["rmse"] == pytest.approx((6.5 / 3) ** 0.5) and s["min"] == -2.0 and s["max"] == 1.5 and s["share_1m"] == pytest.approx(1 / 3)
    assert gc.stats([]) == {"n": 0}


def _fact(well, date, season, gvk, top=-895.0, bottom=-940.0, pack="верхняя"):
    return {"well": well, "date": date, "season": season, "packs": [{"pack": pack, "gvk": gvk, "label": "ГВК", "top": top, "bottom": bottom}]}


def test_compare_rows_overrides_and_exclusion():
    asked = []

    def profiles(day, ws):
        asked.append((day, tuple(ws)))
        return {w: CELLS for w in ws if w != "7"}

    facts = [_fact("1", "2024-11-30", "осень", -921.0), _fact("2", "2025-04-10", "весна", -918.0), _fact("7", "2024-11-30", "осень", -900.0),
             _fact("3", "2025-04-10", "весна", -930.0, top=-925.0)]
    out = gc.compare(facts, _daily(PAUSES), profiles, 0.01, slices={"2|2025-04-10": "2025-04-01"}, excluded=["2|2025-04-10|верхняя"],
                     groups={"1": "ГСП-1", "2": "ГСП-1"})
    r = {x["well"]: x for x in out["rows"]}
    assert r["1"]["slice"] == "2024-11-05" and r["1"]["delta"] == pytest.approx(1.0) and r["1"]["group"] == "ГСП-1"
    assert r["2"]["slice"] == "2025-04-01" and r["2"]["slice_why"] == "вручную" and r["2"]["excluded"]
    assert r["7"]["status"] == "нет модели" and r["7"]["delta"] is None
    assert r["3"]["status"] == gc.NO_GAS
    assert out["all"]["n"] == 1 and out["by"]["pack"]["верхняя"]["n"] == 1             # исключённая и не сравнимые не в статистике
    assert out["skipped"][gc.NO_GAS] == 1 and out["skipped"]["нет модели"] == 1
    assert (D(2024, 11, 5), ("1", "7")) in asked                                         # одна загрузка профилей на дату среза
