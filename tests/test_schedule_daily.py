"""R7: суточное осреднение по выбранным сезонам, заполнение суток без данных, сходимость с тех.картой, форма суток по эталону."""
import os
import sys
from datetime import date, timedelta

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import daily  # noqa: E402
from schedule_pxg import forecast as fc  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from tests.test_schedule_forecast import _project  # noqa: E402

MONTHS = ["Ноябрь", "Декабрь", "Январь", "Февраль", "Март"]


def _season_dates(y):
    d, end = date(y, 11, 1), date(y + 1, 3, 31)
    while d <= end:
        yield d
        d += timedelta(days=1)


def _hist(shares, skip=lambda y, d: False):
    """shares: {год сезона: доля скважины a}; b получает остаток; группа за сутки = 100."""
    rows = []
    for y, a in shares.items():
        for d in _season_dates(y):
            if skip(y, d):
                continue
            rows += [("a", d, 100 * a), ("b", d, 100 * (1 - a))]
    return pd.DataFrame({"well": [r[0] for r in rows], "date": pd.to_datetime([r[1] for r in rows]),
                         "rate": [r[2] for r in rows], "kind": "отбор"})


def _proj():
    return _project({"1": ["a", "b"]})


def test_methods_by_hand():
    h = _hist({2021: .2, 2022: .4, 2023: .9})
    got = {m: daily.build(h, _proj(), MONTHS, "отбор", method=m).offset[("1", 0)]["a"] for m in daily.METHODS}
    assert got["mean"] == pytest.approx(0.5)
    assert got["median"] == pytest.approx(0.4)
    assert got["recency"] == pytest.approx((.2 * 1 + .4 * 2 + .9 * 3) / 6)   # последний сезон весит больше
    assert got["trimmed"] == pytest.approx(0.4)                              # без самого малого и самого большого
    only = daily.build(h, _proj(), MONTHS, "отбор", seasons=[2022, 2023])
    assert only.seasons == [2022, 2023] and only.offset[("1", 0)]["a"] == pytest.approx(.65)
    with pytest.raises(ValueError):
        daily.build(h, _proj(), MONTHS, "отбор", method="нет")


def test_days_count_from_season_start_and_leap():
    # 2023: 1 ноября 2023 — сутки 0; в високосном сезоне 2023/24 после 29 февраля даты смещены на сутки относительно 2024/25
    h = _hist({2023: .5, 2024: .5}, skip=lambda y, d: False)
    p = daily.build(h, _proj(), MONTHS, "отбор")
    assert p.days == daily.season_days(MONTHS, 2023) + 1 == 152 + 1
    assert daily.season_days(MONTHS, 2024) == 151
    assert not p.filled or all(d >= 151 for _, d in p.filled)   # заполнены только лишние сутки запаса


def test_fill_chain_flags():
    # сутки 10 — одни без данных (окно ±3); 40..46 — семь подряд (середина требует окна ±7); весь февраль — нет и доли месяца (поровну)
    def skip(y, d):
        off = (d - date(y, 11, 1)).days
        return off == 10 or 40 <= off <= 46 or d.month == 2
    p = daily.build(_hist({2022: .3, 2023: .5}, skip), _proj(), MONTHS, "отбор")
    assert p.filled[("1", 10)] == "window3" and p.offset[("1", 10)]["a"] == pytest.approx(.4)
    assert p.filled[("1", 40)] == "window3" and p.filled[("1", 43)] == "window7"
    feb = (date(2023, 2, 15) - date(2022, 11, 1)).days
    assert p.filled[("1", feb)] == "equal" and p.offset[("1", feb)] == {"a": .5, "b": .5}
    fl = p.flagged()
    assert (fl[0]["group"], fl[0]["day"]) == ("1", 10) and p.summary()["filled"] == len(p.filled) and p.summary()["by"]["поровну"] > 10


def test_month_fallback():
    # нет данных в сутках 31..34 (декабрь), окно ±3/±7 даст данные соседей — проверяем долю месяца: убираем весь декабрь, кроме 1-го числа
    h = _hist({2022: .3, 2023: .5}, skip=lambda y, d: d.month == 12 and d.day > 1 and d.day < 30)
    p = daily.build(h, _proj(), MONTHS, "отбор")
    assert p.filled[("1", 40)] in ("month", "window7")


def test_group_month_totals_match_techmap():
    h = _hist({2022: .3, 2023: .5}, skip=lambda y, d: d.month == 1 and d.day % 5 == 0)
    prof = daily.build(h, _proj(), MONTHS, "отбор", method="median")
    tm = tmod.TechMap("Отбор", "отбор", MONTHS)
    tm.days = dict(zip(MONTHS, (30, 31, 31, 28, 31)))
    vols = {"Ноябрь": 30.0, "Декабрь": 31.0, "Январь": 12.34, "Февраль": 29.0, "Март": 31.0}
    tm.volumes = {"1": vols}
    for year in (2025, 2027):                    # 2027/28 — високосный
        sh = prof.apply(fc.Shares.uniform(_proj(), tm))
        ref = pd.DataFrame({"Дата": pd.to_datetime([date(2022, 11, 1) + timedelta(days=k) for k in range(150)]),
                            "Объем": [1000 + 10 * (k % 7) for k in range(150)]})
        dw = daily.reference_weights(ref, MONTHS, [2022], year)
        res = fc.forecast_season(tm, _proj(), sh, year, "day", day_weights=dw)
        grp = {r["month"]: r for r in res.rows if r["level"] == "группа"}
        for m, v in vols.items():
            assert grp[m]["written"] == pytest.approx(v * 1e6, rel=1e-6, abs=1.0), (year, m)
        wells = {r["month"]: r["written"] for r in res.rows if r["level"] == "скважина" and r["name"] == "a"}
        assert all(0 < wells[m] < vols[m] * 1e6 for m in vols)
        assert len({round(s.rates.get("a", 0), 3) for s in res.steps if s.work_days}) > 3   # доли меняются по суткам
        if year == 2027:
            assert any(s.start <= date(2028, 2, 29) <= s.end and s.work_days for s in res.steps)   # високосный день учтён


def test_reference_weights_by_season_day():
    ref = pd.DataFrame({"Дата": pd.to_datetime(["2022-11-01", "2023-11-01", "2022-11-02", "2030-01-01"]), "Объем": [10, 20, 5, 7]})
    w = daily.reference_weights(ref, MONTHS, [2022, 2023], 2025)
    assert w[date(2025, 11, 1)] == 15 and w[date(2025, 11, 2)] == 5 and date(2025, 11, 3) not in w
    assert daily.reference_weights(pd.DataFrame(columns=["Дата", "Объем"]), MONTHS, [2022], 2025) == {}
