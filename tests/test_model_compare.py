import datetime as dt

from schedule_pxg import model_compare as mc


def d(s):
    return dt.date.fromisoformat(s)


def ser(*pairs):
    return [(dt.datetime.fromisoformat(a), v) for a, v in pairs]


MODEL_A = {"W1": ser(("2023-01-01", 100.0), ("2023-02-01", 90.0)), "W2": ser(("2023-01-01", mc.MISSING))}
MODEL_B = {"W1": ser(("2023-01-03", 104.0))}


def test_diff_is_model_minus_fact_and_nearest_date():
    out = mc.compare([{"well": "W1", "date": "2023-01-02", "p": 98.0}], {"A": MODEL_A, "B": MODEL_B})
    row = out["rows"][0]
    assert row["models"]["A"]["value"] == 100.0 and row["models"]["A"]["gap_days"] == 1
    assert row["models"]["A"]["diff"] == 2.0
    assert row["models"]["B"]["diff"] == 6.0
    assert out["stats"]["A"]["n"] == 1 and out["stats"]["A"]["mean"] == 2.0


def test_missing_values_are_skipped_not_used():
    out = mc.compare([{"well": "W2", "date": "2023-01-01", "p": 120.0},
                      {"well": "W1", "date": "2023-01-01", "p": -999.25}], {"A": MODEL_A})
    w2, w1 = out["rows"]
    assert w2["models"]["A"]["value"] is None and w2["models"]["A"]["hint"] == "нет давления модели у скважины"
    assert w2["hint"] == ""
    assert w1["fact"] is None and w1["hint"] == "нет замера (пропуск или ноль)"
    assert out["stats"]["A"]["n"] == 0 and out["stats"]["A"]["mean"] is None


def test_manual_exclusion_removes_row_from_stats_and_keeps_hint():
    key = mc.pair_key("W1", d("2023-01-01"))
    meas = [{"well": "W1", "date": "2023-01-01", "p": 95.0}, {"well": "W1", "date": "2023-02-01", "p": 80.0}]
    base = mc.compare(meas, {"A": MODEL_A})
    assert base["stats"]["A"]["n"] == 2 and base["stats"]["A"]["mean"] == 7.5
    out = mc.compare(meas, {"A": MODEL_A}, excluded=[key])
    assert out["rows"][0]["excluded"] is True and out["excluded_count"] == 1
    assert out["stats"]["A"]["n"] == 1 and out["stats"]["A"]["mean"] == 10.0
    assert out["stats"]["A"]["wells"]["W1"]["n"] == 1


def test_tolerance_hint_blocks_row_until_tolerance_widened():
    meas = [{"well": "W1", "date": "2023-01-20", "p": 90.0}]
    strict = mc.compare(meas, {"A": MODEL_A}, tolerance_days=5)
    assert strict["rows"][0]["models"]["A"]["hint"].startswith("дата модели дальше допуска")
    assert strict["stats"]["A"]["n"] == 0
    loose = mc.compare(meas, {"A": MODEL_A}, tolerance_days=30)
    assert loose["stats"]["A"]["n"] == 1


def test_stats_mean_abs_and_max_abs_and_empty_models():
    meas = [{"well": "W1", "date": "2023-01-01", "p": 105.0}, {"well": "W1", "date": "2023-02-01", "p": 85.0}]
    out = mc.compare(meas, {"A": MODEL_A, "B": {}})
    assert out["stats"]["A"]["mean"] == 0.0 and out["stats"]["A"]["mean_abs"] == 5.0 and out["stats"]["A"]["max_abs"] == 5.0
    assert out["stats"]["B"]["n"] == 0
    assert out["models"] == ["A", "B"]


def test_negative_tolerance_is_refused():
    try:
        mc.compare([], {}, tolerance_days=-1)
    except ValueError:
        return
    raise AssertionError("ожидалась ошибка")
