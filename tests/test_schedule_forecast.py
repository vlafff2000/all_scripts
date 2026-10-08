"""Ядро прогноза «Скедул ПХГ»: сетка шагов, доли, остаток округления, запись и паритет со старым скриптом."""
import os
import sys
from datetime import date, timedelta

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_pxg import forecast as fc  # noqa: E402
from schedule_pxg import history as hist  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402
from tests.golden import golden  # noqa: E402

SAMPLES = os.environ.get("SCHEDULE_TR_SAMPLES") or "/mnt/project-files/schedule-tr-samples"
have = pytest.mark.skipif(not os.path.isdir(SAMPLES), reason="нет образцов schedule-tr-samples")


def S(name):
    return os.path.join(SAMPLES, name)


# ---------------------------------------------------------------- без образцов

def _project(groups):
    p = Project()
    for g, wells in groups.items():
        p.add_group(g)
        for w in wells:
            p.add_well(w, group=g)
    return p


def _tm(kind="закачка", months=("Май", "Июнь"), days=(31, 30), vols=None):
    t = tmod.TechMap("Карта", kind, list(months))
    t.days = dict(zip(months, days))
    t.volumes = vols or {"1": {m: 31.0 for m in months}}
    return t


def test_grid_steps_and_cuts():
    work = {date(2026, 5, d) for d in range(1, 32)} | {date(2026, 6, d) for d in range(1, 31)}
    g = fc.build_grid(date(2026, 5, 1), date(2026, 6, 30), work, "decade")
    assert g[:4] == [(date(2026, 5, 1), date(2026, 5, 10)), (date(2026, 5, 11), date(2026, 5, 20)),
                     (date(2026, 5, 21), date(2026, 5, 31)), (date(2026, 6, 1), date(2026, 6, 10))]
    assert len(fc.build_grid(date(2026, 5, 1), date(2026, 6, 30), work, "month")) == 2
    assert fc.build_grid(date(2026, 5, 1), date(2026, 5, 31), work, "half")[1][0] == date(2026, 5, 16)
    wk = fc.build_grid(date(2026, 5, 1), date(2026, 5, 31), work, "week")
    assert [(b - a).days + 1 for a, b in wk] == [7, 7, 7, 7, 3]
    # своя дата-разрез и смена длины шага
    cut = fc.build_grid(date(2026, 5, 1), date(2026, 5, 31), work, "month", cuts=[date(2026, 5, 12)])
    assert cut == [(date(2026, 5, 1), date(2026, 5, 11)), (date(2026, 5, 12), date(2026, 5, 31))]
    per = fc.build_grid(date(2026, 5, 1), date(2026, 5, 31), work, "month", periods=[(date(2026, 5, 20), "day")])
    assert per[0] == (date(2026, 5, 1), date(2026, 5, 19)) and len(per) == 1 + 12
    with pytest.raises(ValueError):
        fc.build_grid(date(2026, 5, 1), date(2026, 5, 2), work, "год")


def test_grid_cut_on_work_change_and_covers_every_day():
    work = {date(2026, 4, d) for d in range(27, 31)} | {date(2026, 5, d) for d in range(1, 11)}
    g = fc.build_grid(date(2026, 4, 20), date(2026, 5, 15), work, "month")
    assert g == [(date(2026, 4, 20), date(2026, 4, 26)), (date(2026, 4, 27), date(2026, 4, 30)),
                 (date(2026, 5, 1), date(2026, 5, 10)), (date(2026, 5, 11), date(2026, 5, 15))]
    days = [a + timedelta(days=k) for a, b in g for k in range((b - a).days + 1)]
    assert days == [date(2026, 4, 20) + timedelta(days=k) for k in range(26)]


def test_shares_manual_override_keeps_sum_one():
    sh = fc.Shares()
    sh.set_month("Г", "Май", {"a": 2, "b": 1, "c": 1})
    assert sh.get("Г", "Май") == pytest.approx({"a": 0.5, "b": 0.25, "c": 0.25})
    sh.set_manual("Г", "Май", "a", 0.8)
    got = sh.get("Г", "Май")
    assert got["a"] == pytest.approx(0.8) and got["b"] == pytest.approx(0.1) and sum(got.values()) == pytest.approx(1)
    sh.clear_manual("Г", "Май", "a")
    assert sh.get("Г", "Май")["a"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        sh.set_manual("Г", "Май", "a", 1.5)


def test_shares_from_history_split_and_unknown():
    p = _project({"ГСП 1": ["1", "54", "80"]})
    h = pd.DataFrame({"well": ["1", "54/80", "99"], "date": pd.to_datetime(["2025-05-01"] * 3),
                      "rate": [60.0, 40.0, 5.0], "hours": [24] * 3, "kind": ["закачка"] * 3})
    sh = fc.shares_from_history(h, p, split={"54/80": ["54", "80"]})
    assert sh.get("ГСП 1", "Май") == pytest.approx({"1": 0.6, "54": 0.2, "80": 0.2})
    assert sh.unknown_wells == {"99"}


def test_forecast_conserves_techmap_and_rate_is_flat():
    p = _project({"ГСП 1": ["10", "11", "12"]})
    tm = _tm(vols={"1": {"Май": 31.0, "Июнь": 30.0}})
    sh = fc.Shares()
    for m in tm.months:
        sh.set_month("ГСП 1", m, {"10": 0.5, "11": 0.3, "12": 0.2})
    for step in ("day", "week", "decade", "half", "month"):
        f = fc.forecast_season(tm, p, sh, 2026, step=step, decimals=0)
        assert f.steps[0].start == date(2026, 5, 1) and f.steps[-1].end == date(2026, 6, 30)
        # 31 млн м³ за 31 день: 1 млн м³/сут на группу, доля 0,5 → 500000 м³/сут
        assert f.steps[0].rates["10"] == pytest.approx(500000) and f.steps[-1].rates["12"] == pytest.approx(200000)
        obj = [r for r in f.rows if r["level"] == "объект"][0]
        assert obj["target"] == pytest.approx(61e6) and obj["written"] == pytest.approx(61e6) and not f.over()


def test_residual_is_spread_over_all_steps_not_dumped_on_one():
    """Дебит до целого м³/сут: 31 сутки по 100.4 → без размазывания месячный объём 31·100 = 3100 (−12,4 м³)."""
    p = _project({"ГСП 1": ["10"]})
    tm = _tm(months=("Май",), days=(31,), vols={"1": {"Май": 3112.4 / 1e6}})
    sh = fc.Shares()
    sh.set_month("ГСП 1", "Май", {"10": 1})
    plain = fc.forecast_season(tm, p, sh, 2026, decimals=0, spread=False)
    assert {round(s.rates["10"], 3) for s in plain.steps} == {round(3112.4 / 31, 3)}      # без округления
    f = fc.forecast_season(tm, p, sh, 2026, step="day", decimals=0)
    rates = [s.rates["10"] for s in f.steps]
    assert set(rates) == {100.0, 101.0}                      # остаток размазан по суткам
    assert rates.count(101.0) == 12 and sum(rates) == 3112   # 12 суток по +1: 3112 из 3112,4
    row = [r for r in f.rows if r["level"] == "скважина"][0]
    assert abs(row["diff"]) < 1 and not row["over"]
    # месячный шаг: остаток не помещается, ошибка ≤ половины суток, допуск не нарушен
    m = fc.forecast_season(tm, p, sh, 2026, step="month", decimals=0)
    assert abs([r for r in m.rows if r["level"] == "объект"][0]["rel"]) < 0.005


def test_reconciliation_flags_lost_volume():
    p = _project({"ГСП 1": ["10"]})
    tm = _tm(vols={"1": {"Май": 31.0, "Июнь": 30.0}, "7": {"Май": 5.0, "Июнь": 5.0}})  # группы 7 нет в проекте
    sh = fc.Shares()
    sh.set_month("ГСП 1", "Май", {"10": 1})   # на июнь долей нет
    f = fc.forecast_season(tm, p, sh, 2026)
    over = {(r["level"], r["name"], r["month"]) for r in f.over()}
    assert ("группа", "ГСП 1", "Июнь") in over and ("группа", "7", "Май") in over
    assert ("объект", "", "") in over and any("нет в проекте" in n for n in f.notes)
    assert any("потерян" in n for n in f.notes)


def test_day_weights_profile_and_work_override():
    p = _project({"ГСП 1": ["10"]})
    tm = _tm(months=("Май",), days=(2,), vols={"1": {"Май": 3.0}})
    sh = fc.Shares()
    sh.set_month("ГСП 1", "Май", {"10": 1})
    days = [date(2026, 5, 10), date(2026, 5, 11)]
    f = fc.forecast_season(tm, p, sh, 2026, work_dates={"Май": days},
                           day_weights={days[0]: 1.0, days[1]: 2.0}, spread=False)
    assert [round(s.rates["10"]) for s in f.steps] == [1000000, 2000000]


def test_render_modes_and_dates_shift():
    st = [fc.Step(date(2026, 5, 1), date(2026, 5, 3), 3, "закачка", {"10": 123.456, "9": 5.0}),
          fc.Step(date(2026, 5, 4), date(2026, 5, 4), 0, "нейтральный")]
    t = fc.render_schedule(st)
    assert t.startswith("DATES\n\t30\tAPR\t2026 /\n/\n") and "WCONINJH\n9\tGAS\tOPEN\t5.00\t /\n10\tGAS\tOPEN\t123.46\t /\n" in t
    assert "WEFAC\n9\t1.000\t/\n10\t1.000\t/\n" in t and t.count("WELOPEN") == 2 and "DATES\n\t3\tMAY\t2026 /" in t
    r = fc.render_schedule(st, mode="rate", bhp_inj=250.0, dates_shift=0, close=False)
    assert "DATES\n\t1\tMAY\t2026 /" in r and "WCONINJE\n9\tGAS\tOPEN\tRATE\t5.00\t1*\t250\t/" in r and "WCONHIST" not in r
    prod = fc.render_schedule([fc.Step(date(2026, 1, 1), date(2026, 1, 1), 1, "отбор", {"3": 7.0})], mode="rate", close=False)
    assert "WCONPROD\n3\tOPEN\tGRAT\t2*\t7.00\t2*\t1*\t/" in prod
    hp = fc.render_schedule([fc.Step(date(2026, 1, 1), date(2026, 1, 1), 1, "отбор", {"3": 7.0})], close=False)
    assert "WCONHIST\n3\tOPEN\tGRAT\t1*\t1*\t7.00\t1*\t/" in hp
    with pytest.raises(ValueError):
        fc.render_schedule(st, mode="x")


def test_written_schedule_is_read_back_by_history_reader(tmp_path):
    p = _project({"ГСП 1": ["10", "11"]})
    tm = _tm(vols={"1": {"Май": 31.0, "Июнь": 30.0}})
    sh = fc.Shares.uniform(p, tm)
    f = fc.forecast_season(tm, p, sh, 2026, step="decade")
    path = fc.write_schedule(str(tmp_path / "s.inc"), f.steps)
    df = hist.read_schedule(path)
    assert set(df["well"]) == {"10", "11"} and df["date"].min() == pd.Timestamp("2026-05-01")
    assert df[df["date"] == "2026-05-11"]["rate"].iloc[0] == pytest.approx(500000)


# ---------------------------------------------------------------- образцы

def _only(tm, key):
    t = tmod.TechMap.from_dict(tm.to_dict())
    t.volumes = {key: t.volumes[key]}
    return t


def _sample_project():
    p = Project()
    for g, f in (("ГСП 8", "ГСП_8_a.xlsx"), ("ГСП 9", "ГСП_9_a.xlsx")):
        p.add_group(g)
        for w in sorted(hist.import_history(S(f))["well"].unique()):
            p.add_well(w, group=g)
    return p


@have
def test_parity_with_old_forecast_rates(tmp_path):
    """Старый create_forecast_multiple_scenarios (одна группа, сутки) и ядро с теми же долями по дням и профилем
    посуточного файла: дебиты каждой скважины в каждые сутки совпадают."""
    pi, pp = golden("pct_ГСП_9_a")[0], golden("pct_ГСП_9_b")[0]
    ti, tp = golden("tot_inj"), golden("tot_prod")
    old_df = golden("forecast_9")        # schedule старого create_forecast_multiple_scenarios на этих данных
    assert len(old_df) > 5000

    proj = _sample_project()
    steps, extra = [], []
    for path, pct, daily, year in (
            (S("Утвержденные_объемы_отбор.xlsx"), pp, tp, 2025), (S("Утвержденные_объемы_закачка.xlsx"), pi, ti, 2026)):
        tm = _only(tmod.read_techmap(path), "9")
        sh = fc.Shares()
        for (gsp, month), days in pct.items():
            for day, w in days.items():
                sh.set_day("ГСП 9", month, int(day), {k: v / 100.0 for k, v in w.items()})
        months = fc.season_months(tm, year)
        override, weights = {}, {}
        for m, y in months:
            mn = tmod.MONTHS.index(m) + 1
            sub = daily[daily["Дата"].dt.month == mn]
            override[m] = [date(y, mn, int(d)) for d in sub["Дата"].dt.day]
            for d, v in zip(sub["Дата"].dt.day, sub["Объем"]):
                weights[date(y, mn, int(d))] = float(v)
        f = fc.forecast_season(tm, proj, sh, year, step="day", work_dates=override, day_weights=weights, spread=False)
        steps += f.steps
    new_path = fc.write_schedule(str(tmp_path / "new.inc"), steps, close=False)
    new_df = hist.read_schedule(new_path)
    a = {(w, d): r for w, d, r in zip(old_df["well"], old_df["date"], old_df["rate"])}
    b = {(w, d): r for w, d, r in zip(new_df["well"], new_df["date"], new_df["rate"])}
    assert set(a) <= set(b)                         # всё, что писал старый скрипт, есть
    assert max(abs(a[k] - b[k]) for k in a) < 0.0101  # и совпадает до округления .2f
    # лишнее у ядра — только сутки без долей в истории: старый скрипт теряет там объём суток, ядро берёт средние доли месяца
    for w, d in set(b) - set(a):
        pct = pi if d.month in (4, 5, 6, 7, 8, 9, 10) else pp
        assert d.day not in pct.get((9, tmod.MONTHS[d.month - 1]), {}) or not any(pct[(9, tmod.MONTHS[d.month - 1])][d.day].values())
    assert len(a) > 5000


@have
def test_new_method_reconciles_with_techmap_on_samples():
    """Ядро по тех.карте и долям из истории: объём по группам, объекту и каждой скважине = тех.карте."""
    proj = _sample_project()
    tm = tmod.read_techmap(S("Утвержденные_объемы_закачка.xlsx"))
    tm.volumes = {k: v for k, v in tm.volumes.items() if k in ("8", "9")}
    h = hist.import_history(S("ГСП_8_a.xlsx"))
    h = pd.concat([h, hist.import_history(S("ГСП_9_a.xlsx"))])
    sh = fc.shares_from_history(h, proj, kind="закачка")
    assert not sh.unknown_wells
    for step in ("day", "decade", "month"):
        f = fc.forecast_season(tm, proj, sh, 2027, step=step)
        assert not f.over(), f.over()[:3]
        obj = [r for r in f.rows if r["level"] == "объект"][0]
        want = (tm.group_total("8") + tm.group_total("9")) * 1e6
        assert obj["target"] == pytest.approx(want) and obj["written"] == pytest.approx(want, rel=1e-6)
    assert f.steps[0].start == date(2027, 4, 27) and f.steps[-1].end == date(2027, 10, 15)
    assert sum(s.work_days for s in f.steps) == 172
    # апрель: у ГСП 8 объём 0, у ГСП 9 — тоже; первые 4 суток сезона без работы
    assert f.steps[0].rates == {}


@have
def test_first_month_work_days_effect_on_result():
    """Рабочие дни крайних месяцев (расхождение, найденное в А4): как это меняет прогноз."""
    proj = _project({"ГСП 1": ["10"]})
    sh = fc.Shares()
    # закачка, апрель: 30 млн м³ на 4 рабочих дня; посуточный файл подтверждает 27–30 апреля
    inj = _only(tmod.read_techmap(S("Утвержденные_объемы_закачка.xlsx")), "1")
    for m in inj.months:
        sh.set_month("ГСП 1", m, {"10": 1})
    new = fc.forecast_season(inj, proj, sh, 2027, step="month")
    assert (new.steps[0].start, new.steps[0].end, new.steps[0].rates["10"]) == (date(2027, 4, 27), date(2027, 4, 30), 7500000.0)
    # правило старого get_work_days_for_month для апреля (30 дней): 1–4 апреля, затем 26 суток паузы
    wrong = fc.forecast_season(inj, proj, sh, 2027, step="month", work_dates={"Апрель": [date(2027, 4, d) for d in range(1, 5)]})
    assert (wrong.steps[0].start, wrong.steps[0].end) == (date(2027, 4, 1), date(2027, 4, 4))
    assert wrong.steps[1].kind == "нейтральный" and wrong.steps[1].work_days == 0
    # отбор, ноябрь: тех.карта — 26 рабочих суток (5–30 ноября), посуточный файл образца — 30 суток (1–30)
    prod = _only(tmod.read_techmap(S("Утвержденные_объемы_отбор.xlsx")), "1")
    for m in prod.months:
        sh.set_month("ГСП 1", m, {"10": 1})
    by_card = fc.forecast_season(prod, proj, sh, 2025, step="month")
    by_file = fc.forecast_season(prod, proj, sh, 2025, step="month", work_dates={"Ноябрь": [date(2025, 11, d) for d in range(1, 31)]})
    assert by_card.steps[0].start == date(2025, 11, 5) and by_file.steps[0].start == date(2025, 11, 1)
    ratio = by_card.steps[0].rates["10"] / by_file.steps[0].rates["10"]
    assert ratio == pytest.approx(30 / 26)          # объём ноября тот же, суточный дебит на 15,4% выше
    assert by_card.written("10", "Ноябрь") == pytest.approx(by_file.written("10", "Ноябрь"))


@have
def test_old_script_splits_object_volume_by_equal_group_weights(tmp_path):
    """Расхождение со старым скриптом: он складывает проценты групп с равным весом и умножает на объём ВСЕГО ОБЪЕКТА,
    поэтому объёмы групп по тех.карте (сентябрь: ГСП 8 — 220, ГСП 9 — 266 млн м³) расходятся к 243/243. Ядро держит объём каждой группы."""
    df = golden("forecast_sept")       # сентябрь из schedule старого скрипта на группах 8 и 9
    proj = _sample_project()
    sept = df[df["date"].dt.month == 9]
    got = sept.groupby(sept["well"].map(proj.group_at_level))["rate"].sum() / 1e6
    assert got["ГСП 8"] == pytest.approx(243.0, abs=0.01) and got["ГСП 9"] == pytest.approx(243.0, abs=0.01)
    tm = tmod.read_techmap(S("Утвержденные_объемы_закачка.xlsx"))
    assert (tm.volumes["8"]["Сентябрь"], tm.volumes["9"]["Сентябрь"]) == (220.0, 266.0)


# ---------------------------------------------------------------- отключения (А6)

from schedule_pxg import outages as om  # noqa: E402


def _outage_case(fate, groups=None, end=date(2026, 5, 31)):
    p = _project(groups or {"ГСП 1": ["10", "11", "12"], "ГСП 2": ["20", "21"]})
    tm = _tm(months=("Май",), days=(31,), vols={"1": {"Май": 31.0}, "2": {"Май": 31.0}})
    sh = fc.Shares()
    sh.set_month("ГСП 1", "Май", {"10": 0.5, "11": 0.3, "12": 0.2})
    sh.set_month("ГСП 2", "Май", {"20": 0.5, "21": 0.5})
    o = [om.Outage("10", date(2026, 5, 11), end, "ремонт", "", fate)]
    return fc.forecast_season(tm, p, sh, 2026, step="month", decimals=0, outages=o), o


def test_outage_cuts_step_and_is_shut_in_schedule():
    f, o = _outage_case("group")
    assert [(s.start, s.end) for s in f.steps] == [(date(2026, 5, 1), date(2026, 5, 10)), (date(2026, 5, 11), date(2026, 5, 31))]
    assert f.steps[0].shut == {} and f.steps[1].shut == {"10": "ремонт"} and "10" not in f.steps[1].rates
    txt = fc.render_schedule(f.steps, mode="rate")
    assert "10\tSHUT\t/  -- отключена: ремонт" in txt
    assert txt.count("'*'\tSHUT") == 2 and txt.count("10\tSHUT") == 1


def test_outage_volume_to_group_keeps_group_and_object_totals():
    f, _ = _outage_case("group")
    r = {x["name"]: x for x in f.rows if x["level"] == "группа"}
    assert not f.over() and r["ГСП 1"]["written"] == pytest.approx(31e6)
    # 20 суток отключения: доля 0,5 делится 3:2 между 11 и 12
    s1 = f.steps[1]
    assert s1.rates["11"] == pytest.approx(1e6 * (0.3 + 0.5 * 0.6)) and s1.rates["12"] == pytest.approx(1e6 * (0.2 + 0.5 * 0.4))
    assert s1.rates["20"] == pytest.approx(500000) and f.moved[0]["fate"] == "group" and f.moved[0]["lost"] == 0


def test_outage_volume_to_object_goes_to_all_working_wells():
    f, _ = _outage_case("object")
    s1 = f.steps[1]
    # 0,5 млн м³/сут делится по объёму дня: 11:0,3 12:0,2 20:0,5 21:0,5 (всего 1,5)
    assert s1.rates["20"] == pytest.approx(500000 + 500000 * 0.5 / 1.5) and s1.rates["11"] == pytest.approx(300000 + 500000 * 0.3 / 1.5)
    obj = [x for x in f.rows if x["level"] == "объект"][0]
    assert obj["written"] == pytest.approx(62e6)
    g = {x["name"]: x for x in f.rows if x["level"] == "группа"}
    assert g["ГСП 2"]["over"] and g["ГСП 2"]["written"] > g["ГСП 2"]["target"]   # группа получила чужой объём — видно в сверке


def test_outage_lose_drops_volume():
    f, _ = _outage_case("lose")
    obj = [x for x in f.rows if x["level"] == "объект"][0]
    assert obj["written"] == pytest.approx(62e6 - 0.5e6 * 21)
    assert f.moved[0]["lost"] == pytest.approx(0.5e6 * 21) and f.over()


def test_outage_whole_group_off_loses_and_noted():
    p = _project({"ГСП 1": ["10"]})
    tm = _tm(months=("Май",), days=(31,), vols={"1": {"Май": 31.0}})
    sh = fc.Shares(); sh.set_month("ГСП 1", "Май", {"10": 1})
    f = fc.forecast_season(tm, p, sh, 2026, step="month", decimals=0, outages=[om.Outage("10", date(2026, 5, 1))])
    assert f.moved[0]["lost"] == pytest.approx(31e6) and any("все скважины группы" in n for n in f.notes)


def test_outage_object_all_off_lost():
    p = _project({"ГСП 1": ["10"]})
    tm = _tm(months=("Май",), days=(31,), vols={"1": {"Май": 31.0}})
    sh = fc.Shares(); sh.set_month("ГСП 1", "Май", {"10": 1})
    f = fc.forecast_season(tm, p, sh, 2026, step="month", decimals=0, outages=[om.Outage("10", date(2026, 5, 1), None, fate="object")])
    assert f.moved[0]["lost"] == pytest.approx(31e6) and any("объект целиком" in n for n in f.notes)


def test_outage_roundtrip_validation_and_project_storage(tmp_path):
    o = om.Outage("10", "2026-05-11", None, "ремонт", "заметка", "object")
    assert om.Outage.from_dict(o.to_dict()) == o and o.covers(date(2027, 1, 1))
    with pytest.raises(ValueError):
        om.Outage("10", date(2026, 5, 2), date(2026, 5, 1))
    with pytest.raises(ValueError):
        om.Outage("10", date(2026, 5, 2), fate="сжечь")
    p = _project({"Г": ["10"]})
    notes = om.check([om.Outage("99", date(2026, 5, 1)), om.Outage("10", date(2026, 5, 1), date(2026, 5, 9)),
                      om.Outage("10", date(2026, 5, 5))], p)
    assert len(notes) == 2
    p.outages = [o.to_dict()]
    p.save(str(tmp_path))
    assert Project.load(str(tmp_path)).outages == [o.to_dict()]
