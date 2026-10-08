"""Шаг А10: осреднение истории, комбинации лет, три показателя, совет и выбор долей."""
import contextlib
import io
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import averaging as av  # noqa: E402
from schedule_pxg import forecast as fc  # noqa: E402
from schedule_pxg import history as hist  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402
from tests.test_schedule_forecast import S, _project, have, old_module, _sample_project  # noqa: E402

MONTHS = ["Май", "Июнь"]
# доли скважин a, b, c одинаковы в мае и июне; объём группы за месяц — 100
SHARES = {2022: (.5, .3, .2), 2023: (.4, .4, .2), 2024: (.3, .5, .2), 2025: (.35, .45, .2)}


def _hist(drop=(), shares=SHARES):
    rows = []
    for y, sh in shares.items():
        for mo in (5, 6):
            for w, s in zip("abc", sh):
                if (w, y, mo) in drop or (w, y, None) in drop:
                    continue
                rows.append((w, "%d-%02d-10" % (y, mo), 100.0 * s))
    return pd.DataFrame({"well": [r[0] for r in rows], "date": pd.to_datetime([r[1] for r in rows]),
                         "rate": [r[2] for r in rows], "hours": 24.0, "kind": "закачка"})


def _proj():
    return _project({"1": ["a", "b", "c"]})


def _av(**kw):
    return av.Averaging.from_history(_hist(**{k: kw.pop(k) for k in ("drop",) if k in kw}), _proj(), MONTHS, **kw)


def test_hand_checked_metrics():
    a = _av()
    assert a.years == [2022, 2023, 2024, 2025]
    assert len(a.combos()) == 15
    m = a.metrics("a", (2022,))
    assert m["holdout"] == pytest.approx(15.0) and m["closeness"] == pytest.approx(15.0) and m["stability"] == 0
    assert m["n_years"] == 1
    m = a.metrics("a", (2022, 2023))   # среднее .45 против .35 отложенного 2025
    assert m["holdout"] == pytest.approx(10.0) and m["stability"] == pytest.approx(5.0)
    m = a.metrics("a", (2023, 2024))
    assert m["holdout"] == pytest.approx(0.0) and m["closeness"] == pytest.approx(0.0)
    assert m["stability"] == pytest.approx(5.0)
    # комбинация с отложенным годом: показатель отложенного года не считается
    assert a.metrics("a", (2024, 2025))["holdout"] != a.metrics("a", (2024, 2025))["holdout"]
    mape = _av(metric="mape").metrics("a", (2022,))["holdout"]
    assert mape == pytest.approx(0.15 / 0.35 * 100)


def test_advice_by_holdout_and_ties():
    a = _av()
    assert a.advice("a") == ((2023, 2024), "отложенный год")
    # доля c постоянна: все ошибки 0 и стабильность 0 — берётся комбинация с наибольшим числом лет
    assert a.advice("c") == ((2022, 2023, 2024), "отложенный год")
    done = a.apply_advice()
    assert done["a"] == (2023, 2024) and a.chosen("b") == a.choice["b"]
    a.choose("a", (2022, 2025))
    assert a.chosen("a") == (2022, 2025)
    with pytest.raises(ValueError):
        a.choose("a", (1999,))


def test_idle_year_excluded_automatically_and_listed():
    a = _av(drop={("b", 2023, None), ("b", 2023, 5), ("b", 2023, 6)})
    assert a.auto_excluded["b"] == {2023: "нулевой расход за сезон"}
    assert {(r["well"], r["year"], r["auto"]) for r in a.exclusions()} == {("b", 2023, True)}
    # год 2023 у b не участвует: комбинация (2022, 2023) = только 2022, n_years = 1
    m = a.metrics("b", (2022, 2023))
    assert m["n_years"] == 1 and a._vec("b", (2022, 2023)) == pytest.approx([.3, .3])
    # у других скважин группы 2023 учтён (доли не искажены простоем b: доля a = a/(a+c) в этом году)
    assert a.share["a"]["Май"][2023] == pytest.approx(0.4 / 0.6)
    # вернуть год вручную: нулевая доля считается как есть
    a.include("b", 2023)
    assert a.exclusions() == [] and a._vec("b", (2023,)) == pytest.approx([0.0, 0.0])
    a.exclude("b", 2022)
    assert a.excluded_years("b") == {2022}
    assert a.exclusions()[0]["auto"] is False


def test_idle_month_excluded_only_that_month():
    a = _av(drop={("b", 2024, 6)})
    assert a.auto_months["b"] == {2024: ["Июнь"]}
    assert 2024 not in a.auto_excluded.get("b", {})
    assert a._vec("b", (2024,)) == pytest.approx([.5, av.NAN], nan_ok=True)


def test_manual_share_and_to_shares_normalised():
    a = _av()
    a.apply_advice()
    sh = a.to_shares()
    for m in MONTHS:
        s = sh.get("1", m)
        assert sum(s.values()) == pytest.approx(1.0) and set(s) == {"a", "b", "c"}
    a.set_manual("a", "Май", 0.6)
    sh = a.to_shares()
    assert sh.get("1", "Май")["a"] == pytest.approx(0.6)
    assert sum(sh.get("1", "Май").values()) == pytest.approx(1.0)
    assert sh.get("1", "Июнь")["a"] != pytest.approx(0.6)
    t = a.shares_table()
    assert t[(t["well"] == "a") & (t["month"] == "Май")]["manual"].iloc[0]
    assert not t[(t["well"] == "a") & (t["month"] == "Июнь")]["manual"].iloc[0]
    with pytest.raises(ValueError):
        a.set_manual("a", "Май", 1.5)


def test_feeds_forecast_core_and_keeps_techmap_totals():
    a = _av()
    a.apply_advice()
    tm = tmod.TechMap("Закачка", "закачка", MONTHS)
    tm.days = {"Май": 31, "Июнь": 30}
    tm.volumes = {"1": {"Май": 31.0, "Июнь": 30.0}}
    f = fc.forecast_season(tm, _proj(), a.to_shares(), 2026, step="week")
    obj = [r for r in f.rows if r["level"] == "объект"][0]
    assert obj["written"] == pytest.approx(61e6, rel=1e-6)
    assert not f.over()


def test_max_years_limits_candidates_and_storage_roundtrip(tmp_path):
    a = _av(max_years=3)
    assert a.years == [2023, 2024, 2025] and a.skipped_years == [2022]
    assert len(a.combos()) == 7
    a.apply_advice()
    a.set_manual("c", "Июнь", 0.25)
    a.exclude("b", 2023)
    p = _proj()
    p.averaging = a.to_dict()
    p.save(str(tmp_path))
    b = av.Averaging.from_history(_hist(), _proj(), MONTHS, max_years=3)
    b.load_settings(Project.load(str(tmp_path)).averaging)
    assert b.choice == a.choice and b.manual == a.manual and b.excluded_years("b") == {2023}
    # устаревший выбор (года нет в истории) тихо пропускается
    b.load_settings({"choice": {"a": [1999]}, "manual": [{"well": "zz", "month": "Май", "share": .1}]})
    assert b.choice["a"] != (1999,) and ("zz", "Май") not in b.manual


def test_season_year_for_withdrawal_crossing_new_year():
    assert av.season_year(10, 2023, 10) == 2023 and av.season_year(1, 2024, 10) == 2023
    assert av.season_year(4, 2024, 10) == 2023 and av.season_year(5, 2023, 4) == 2023
    rows = [("a", "2023-10-05", 10.0), ("b", "2023-10-05", 10.0), ("a", "2024-01-10", 30.0), ("b", "2024-01-10", 10.0),
            ("a", "2024-10-05", 20.0), ("b", "2024-10-05", 10.0)]
    h = pd.DataFrame({"well": [r[0] for r in rows], "date": pd.to_datetime([r[1] for r in rows]),
                      "rate": [r[2] for r in rows], "hours": 24.0, "kind": "отбор"})
    a = av.Averaging.from_history(h, _project({"1": ["a", "b"]}), ["Октябрь", "Январь"])
    assert a.years == [2023, 2024]
    assert a.share["a"]["Январь"] == {2023: pytest.approx(0.75)}   # январь 2024 — сезон 2023
    assert a.share["a"]["Октябрь"] == {2023: pytest.approx(0.5), 2024: pytest.approx(2 / 3)}


def test_no_holdout_falls_back_to_closeness():
    h = _hist(shares={2025: (.4, .4, .2)})
    a = av.Averaging.from_history(h, _proj(), MONTHS)
    assert a.advice("a") == ((2025,), "близость к последним сезонам")
    assert a.heatmap().isna().all().all()


# ------------------------------------------------------------ паритет с рабочим кодом и старым скриптом

@have
def test_parity_year_share_with_shares_from_history():
    """Доля одного года = доля `shares_from_history` за тот же календарный год (закачка, образцы ГСП 8 и 9)."""
    proj = _sample_project()
    h = pd.concat([hist.import_history(S("ГСП_8_a.xlsx")), hist.import_history(S("ГСП_9_a.xlsx"))])
    months = ["Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь"]
    a = av.Averaging.from_history(h, proj, months, kind="закачка")
    assert a.years, "в образцах нет истории закачки"
    checked = 0
    for y in a.years:
        ref = fc.shares_from_history(h, proj, years=[y], kind="закачка")
        for (g, m), shares in ref.month.items():
            for w, s in shares.items():
                if y in a.share[w][m]:
                    assert a.share[w][m][y] == pytest.approx(s, abs=1e-12), (y, g, m, w)
                    checked += 1
    assert checked > 100


@have
def test_parity_with_old_script_day_percents():
    """Месячная доля = Σ(процент старого скрипта по дню × объём группы за день) / объём группы за месяц."""
    old = old_module()
    with contextlib.redirect_stdout(io.StringIO()):
        pct, _wells = old.process_injection_file_for_percents(S("ГСП_9_a.xlsx"), "закачка")
    proj = _sample_project()
    h = hist.import_history(S("ГСП_9_a.xlsx"))
    h = h[h["kind"] == "закачка"]
    months = ["Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь"]
    a = av.Averaging.from_history(h, proj, months, kind="закачка")
    y = a.years[-1]
    h = h.assign(date=pd.to_datetime(h["date"]))
    checked = 0
    for (gsp, month), days in pct.items():
        if gsp != 9 or month not in months:
            continue
        mn = tmod.MONTHS.index(month) + 1
        sub = h[(h["date"].dt.month == mn) & (h["date"].dt.year == y) & (h["rate"] > 0)]
        day_tot = sub.groupby(sub["date"].dt.day)["rate"].sum()
        month_tot = day_tot.sum()
        for w in sub["well"].unique():
            from_old = sum(days.get(int(d), {}).get(w, 0.0) / 100.0 * t for d, t in day_tot.items())
            ours = a.share[proj.resolve(w)][month].get(y)
            assert ours is not None
            # старый скрипт округляет проценты до 0,01 %: ошибка суммы суток не больше 0,005 % объёма суток
            assert abs(ours - from_old / month_tot) < 1e-4, (month, w)
            checked += 1
    assert checked > 50
