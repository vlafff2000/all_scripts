from __future__ import annotations

import datetime as dt
import struct
import subprocess
import sys

from tnav_results import iter_restart_steps, read_egrid, read_restart_keyword, read_summary, read_all


def _blk(kw, dtype, vals):
    out = struct.pack(">i8si4si", 16, kw.ljust(8).encode(), len(vals), dtype.encode(), 16)
    code, size, per = {"INTE": (">i", 4, 1000), "REAL": (">f", 4, 1000), "DOUB": (">d", 8, 1000),
                       "CHAR": (None, 8, 105)}[dtype]
    for i in range(0, len(vals), per):
        part = vals[i:i + per]
        raw = b"".join(v.ljust(8).encode() for v in part) if dtype == "CHAR" else \
            b"".join(struct.pack(code, v) for v in part)
        out += struct.pack(">i", len(raw)) + raw + struct.pack(">i", len(raw))
    return out


def test_roundtrip_big_array_and_char(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(_blk("BIG", "REAL", [float(i) for i in range(2500)]) + _blk("NAMES", "CHAR", ["W%d" % i for i in range(250)]))
    (b1, v1), (b2, v2) = read_all(str(p))
    assert len(v1) == 2500 and v1[2499] == 2499.0
    assert v2[249] == "W249" and b2.count == 250


def test_egrid_summary_restart(tmp_path):
    head = [1, 2, 1, 1] + [0] * 29
    grid = tmp_path / "M.EGRID"
    grid.write_bytes(_blk("GRIDHEAD", "INTE", head) + _blk("ACTNUM", "INTE", [1, 0]) +
                     _blk("ZCORN", "REAL", [10.0] * 8 * 2))
    g = read_egrid(str(grid))
    assert (g.ni, g.nj, g.nk) == (2, 1, 1) and g.actnum == [1, 0] and g.cell_depth(1, 0, 0) == 10.0

    sm = tmp_path / "M.SMSPEC"
    sm.write_bytes(_blk("STARTDAT", "INTE", [1, 1, 2020, 0, 0, 0]) + _blk("KEYWORDS", "CHAR", ["TIME", "WGPR"]) +
                   _blk("WGNAMES", "CHAR", [":+:+:+:+", "W1"]) + _blk("NUMS", "INTE", [0, 0]) +
                   _blk("UNITS", "CHAR", ["DAYS", "SM3/DAY"]))
    us = tmp_path / "M.UNSMRY"
    us.write_bytes(b"".join(_blk("MINISTEP", "INTE", [i]) + _blk("PARAMS", "REAL", [31.0 * (i + 1), 5.0 + i]) for i in range(2)))
    s = read_summary(str(sm), str(us))
    assert s.dates[1] == dt.datetime(2020, 3, 3) and s.data[1][1] == 6.0 and s.columns[1][:2] == ("WGPR", "W1")

    ih = [0] * 100
    ih[64], ih[65], ih[66] = 15, 3, 2021
    rs = tmp_path / "M.UNRST"
    body = b""
    for n in (1, 2):
        ih[64] = n
        body += _blk("SEQNUM", "INTE", [n]) + _blk("INTEHEAD", "INTE", ih) + _blk("PRESSURE", "REAL", [100.0 * n, 2.0])
    rs.write_bytes(body)
    steps = list(iter_restart_steps(str(rs)))
    assert [x.seqnum for x in steps] == [1, 2] and steps[1].date == dt.datetime(2021, 3, 2)
    assert list(read_restart_keyword(str(rs), steps[1], "PRESSURE")) == [200.0, 2.0]
    out = subprocess.run([sys.executable, "-m", "tnav_results.list_restart", str(rs)], capture_output=True, text=True)
    assert "SGAS: НЕТ" in out.stdout and "PRESSURE: есть" in out.stdout and "Всего шагов: 2" in out.stdout
