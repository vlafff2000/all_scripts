"""Перфорации из входных файлов модели tNavigator (tnav_results/perforations.py)."""
import datetime as dt
from array import array

from tnav_results import Grid
from tnav_results import perforations as P

DATA = """-- модель
START
 1 JAN 2020 /
RUNSPEC
GRID
SCHEDULE
WELSPECS
 'A1' 'G1' 5 6 1* GAS /
 'A2' 'G1' 7 8 1* GAS /
/
COMPDAT
 'A1' 1* 1* 2 3 OPEN 1* 0.1 /   -- I,J из WELSPECS
 'A1' 5 6 4 4 SHUT /
 'A2' 7 8 1 2 /
/
INCLUDE
 'inc/sch.inc' /
"""
INC = """DATES
 1 'MAR' 2020 /
/
WELOPEN
 'A1' SHUT /
/
DATES
 1 JLY 2020 /
/
COMPDAT
 'A1' 5 6 2 3 OPEN /
/
WELOPEN
 'A*' SHUT 7 8 2 /
/
TSTEP
 10 20 /
WCONHIST
 'A1' OPEN /
/
COMPDATMD
 'A2' 1* 1* 1* 2500 2550 OPEN /
/
"""


def _model(tmp_path):
    (tmp_path / "inc").mkdir()
    (tmp_path / "M.data").write_text(DATA, encoding="utf-8")
    (tmp_path / "inc" / "sch.inc").write_text(INC, encoding="utf-8")
    (tmp_path / "RESULTS").mkdir()
    (tmp_path / "RESULTS" / "M.EGRID").write_bytes(b"")
    return tmp_path


def test_parse_and_state(tmp_path):
    root = _model(tmp_path)
    res = P.read_perforations(str(root / "RESULTS" / "M.EGRID"))   # .data находится выше результатов
    assert res.start == dt.datetime(2020, 1, 1) and len(res.files) == 2
    assert [(w.well, w.i, w.j) for w in res.wells] == [("A1", 5, 6), ("A2", 7, 8)]
    r0 = P.perforations_at(res, dt.datetime(2020, 2, 1))
    got = {(r.well, r.i, r.j, r.k1, r.k2) for r in r0}
    assert got == {("A1", 5, 6, 2, 3), ("A2", 7, 8, 1, 2)}          # K=4 закрыт, I,J по умолчанию взяты из WELSPECS
    assert [r for r in P.perforations_at(res, dt.datetime(2020, 2, 1), only_open=False) if r.status == "SHUT"]
    r1 = P.perforations_at(res, dt.datetime(2020, 4, 1))             # WELOPEN SHUT закрыл всю A1
    assert {r.well for r in r1} == {"A2"}
    r2 = P.perforations_at(res, dt.datetime(2020, 8, 1))             # COMPDAT снова открыл A1 K2–3; WELOPEN 'A*' закрыл A2 K=2
    byw = {r.well: r for r in r2 if r.k1 is not None}
    assert (byw["A1"].k1, byw["A1"].k2) == (2, 3)
    assert (byw["A2"].k1, byw["A2"].k2) == (1, 1)
    assert P.change_dates(res) == [dt.datetime(2020, 1, 1), dt.datetime(2020, 3, 1), dt.datetime(2020, 7, 1),
                                    dt.datetime(2020, 7, 31)]


def test_tstep_and_md(tmp_path):
    res = P.read_perforations(str(_model(tmp_path) / "M.data"))
    md = [e for e in res.events if e.kind == "COMPDATMD"][0]
    assert md.date == dt.datetime(2020, 7, 31) and (md.md_top, md.md_bottom) == (2500.0, 2550.0)
    assert (md.i, md.j) == (7, 8)
    rows = P.perforations_at(res)
    assert any(r.k1 is None and r.md_top == 2500.0 for r in rows)


def test_missing_and_notes(tmp_path):
    res = P.read_perforations(str(tmp_path / "X.EGRID"))
    assert res.events == [] and any(".data" in n for n in res.notes)
    (tmp_path / "bad.data").write_text("COMPDAT\n 'Z' 1* 1* 3 3 /\n/\nINCLUDE\n 'нет.inc' /\n", encoding="utf-8")
    res = P.read_perforations(str(tmp_path / "bad.data"))
    assert any("пропущена" in n for n in res.notes) and any("не найден" in n for n in res.notes)


def test_depths():
    ni = nj = 1
    nk = 3
    z = array("f")
    for k in range(nk):                      # слои 1000–1010, 1010–1020, 1020–1030 (по 4 угла сверху и снизу)
        z.extend([1000.0 + 10 * k] * 4)
        z.extend([1010.0 + 10 * k] * 4)
    g = Grid(ni, nj, nk, [1] * nk, array("f"), z, None)
    rows = [P.PerfRow("A", 1, 1, 2, 3, "OPEN"), P.PerfRow("A", 5, 5, 1, 1, "OPEN")]
    out = P.add_depths(rows, g)
    assert (out[0].top_ao, out[0].bottom_ao) == (-1010.0, -1030.0)
    assert out[1].top_ao is None


def test_base_model_params(tmp_path):
    from tnav_results import base_model
    f = tmp_path / "M.data"
    f.write_text("WELSPECS\n 'A1' 'ГСП-1' 5 6 1* GAS /\n/\nWELLTRACK 'A1'\n 1000.5 2000.5 -150.0 0.0\n 1000.5 2000.5 1000.0 1150.0 /\n"
                 "COMPDAT\n 'A1' 1* 1* 2 3 OPEN /\n/\nCOMPDAT\n 'B' 1* 1* 2 3 OPEN /\n/\n", encoding="utf-8")
    r = base_model.well_params(str(f))
    a = r["wells"]["A1"]
    assert (a["group"], a["i"], a["j"], a["x"], a["y"], a["altitude"]) == ("ГСП-1", 5, 6, 1000.5, 2000.5, 150.0)
    assert a["intervals"][0]["k1"] == 2 and "WELLTRACK" in a["sources"]["x"]
    assert "B" not in r["wells"] and any("нет I" in n for n in r["notes"])        # без I,J и WELSPECS запись пропущена с заметкой
    cmp = base_model.compare(r["wells"], {"A1": 148.0, "B": 1.0})
    assert [(c["well"], c["ok"], c["diff"]) for c in cmp] == [("A1", False, 2.0)]
