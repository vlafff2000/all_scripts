"""Режим «история» «Скедул ПХГ»: сборка только по выбранным сезонам и датам — для дополнения готовой модели."""
import os
import sys
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from schedule_pxg import historymode as hm  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402

PROD, INJ = "отбор", "закачка"


def frame(rows):
    return pd.DataFrame({"well": [r[0] for r in rows], "date": pd.to_datetime([r[1] for r in rows]),
                         "rate": [float(r[2]) for r in rows], "hours": 24.0, "kind": [r[3] for r in rows]})


def project():
    p = Project()
    p.add_group("ГСП 1")
    for w in ("1", "2"):
        p.add_well(w, group="ГСП 1")
    return p


def history():
    rows = []
    for d in pd.date_range("2024-05-01", "2024-05-10"):
        rows.append(("1", d, 100, INJ))
    for d in pd.date_range("2024-11-01", "2024-11-10"):
        rows.append(("1", d, 80, PROD))
    for d in pd.date_range("2025-05-01", "2025-05-10"):
        rows.append(("2", d, 120, INJ))
    return frame(rows)


def test_list_seasons_from_history():
    s = hm.list_seasons(history(), project())
    assert [(x["kind"], x["start"], x["end"]) for x in s] == [
        (INJ, "2024-05-01", "2024-05-10"), (PROD, "2024-11-01", "2024-11-10"), (INJ, "2025-05-01", "2025-05-10")]
    assert [x["id"] for x in s] == [0, 1, 2]


def test_build_only_selected_season_continues_model():
    p, h = project(), history()
    res = hm.build_history(h, p, "daily", seasons=[2])
    assert res.steps[0].start == date(2025, 5, 1) and res.steps[-1].end == date(2025, 5, 10)
    assert {s.kind for s in res.steps} == {INJ} and len(res.steps) == 10
    # DATES первого шага — сутки до среза: модель должна быть посчитана до этой даты
    assert hm.render(res).splitlines()[1].split() == ["30", "APR", "2025", "/"]


def test_two_seasons_with_gap_get_neutral_step_between():
    res = hm.build_history(history(), project(), "daily", seasons=[0, 2])
    gap = [s for s in res.steps if s.kind == hm.NEUTRAL]
    assert len(gap) == 1 and gap[0].start == date(2024, 5, 11) and gap[0].end == date(2025, 4, 30)


def test_date_range_clips_and_kind_comes_from_full_history():
    res = hm.build_history(history(), project(), "daily", date_from=date(2024, 11, 5), date_to=date(2024, 11, 7))
    assert [s.start for s in res.steps] == [date(2024, 11, 5), date(2024, 11, 6), date(2024, 11, 7)]
    assert {s.kind for s in res.steps} == {PROD}


def test_dates_mode_slice_uses_only_dates_inside():
    res = hm.build_history(history(), project(), "dates", model_dates=[date(2024, 5, 5), date(2025, 5, 5), date(2025, 5, 10)],
                           seasons=[2])
    assert res.steps[0].start == date(2025, 5, 1) and res.steps[-1].end == date(2025, 5, 10)
    assert len(res.steps) == 2
