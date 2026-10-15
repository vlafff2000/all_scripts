"""ГДМ: «Создание schedule-файла по поскважинной истории» — шаг сутки и по датам замеров давлений."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pxg_base", "modules"))

from pxg_base.registry import MODULES  # noqa: E402
from pxg_base.webspec import SPECS  # noqa: E402
import Создание_schedule_по_поскважинной_истории as gdm  # noqa: E402

# один вид на сутки: 1 января — отбор скважины 56, 2 января — закачка в 83
HIST = ("DATES\n\t01\tJAN\t2024 /\n/\n\nWCONHIST\n56\tOPEN\tGRAT\t1*\t1*\t1000.00\t1*\t/\n/\n\n"
        "DATES\n\t02\tJAN\t2024 /\n/\n\nWCONINJH\n83\tGAS\tOPEN\t600.00\t /\n/\n")


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_module_registered_in_gdm_section():
    names = {m[1] for m in MODULES if m[0] == "ГДМ"}
    assert names == {"Извлечение_ключевых_слов_из_schedule", "Создание_schedule_по_поскважинной_истории"}
    assert any(s.module == "Создание_schedule_по_поскважинной_истории" for s in SPECS)


def test_daily_steps(tmp_path):
    hist = _write(tmp_path, "h.inc", HIST)
    r = gdm.create(hist, str(tmp_path / "o"))
    assert r["mode"] == "daily" and r["steps"] == 2
    text = open(r["schedule"], encoding="utf-8").read()
    assert "WCONHIST" in text and "WCONINJH" in text


def test_module_check_passes(tmp_path):
    from pxg_base import checks
    hist = _write(tmp_path, "h.inc", HIST)
    rep = checks.run("Создание_schedule_по_поскважинной_истории", {"history": hist, "by_dates": ""})
    errors = [i for i in rep.issues if i.level == "ошибка"]
    assert not errors, rep.to_text()


def test_dates_steps_from_pressure_dates(tmp_path):
    hist = _write(tmp_path, "h.inc", HIST)
    dates = _write(tmp_path, "d.txt", "02.01.2024\n")
    r = gdm.create(hist, str(tmp_path / "o"), by_pressure_dates=True, dates_file=dates)
    assert r["mode"] == "dates" and r["steps"] >= 1
    assert "по_датам_замеров" in os.path.basename(r["schedule"])


def test_dates_mode_needs_dates_file(tmp_path):
    hist = _write(tmp_path, "h.inc", HIST)
    try:
        gdm.create(hist, str(tmp_path / "o"), by_pressure_dates=True)
    except FileNotFoundError as e:
        assert "дат" in str(e)
    else:
        raise AssertionError("ожидалась ошибка без файла дат")
