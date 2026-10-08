"""Описывает файлы расчёта tNavigator: сетку (EGRID), свойства (INIT), вектора и даты (SMSPEC/UNSMRY).

Запуск:  python -m tnav_results.describe_model файл.EGRID [файл.SMSPEC ...] [-o отчёт.txt]
         или просто  python путь/к/describe_model.py файл...
Без больших вычислений: списки ключевых слов берутся по заголовкам, данные читаются только для
GRIDHEAD, ACTNUM, ZCORN, PORV, PORO, DEPTH и колонки TIME.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import OrderedDict

try:
    from .ecl import iter_blocks
    from . import grid_info
except ImportError:  # запуск просто как скрипт
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tnav_results.ecl import iter_blocks
    from tnav_results import grid_info


def _headers(path, want=()):
    """(список (имя, тип, элементов), {имя: данные для нужных})."""
    heads, data = [], {}
    with open(path, "rb") as f:
        for b, v in iter_blocks(f, lambda b: b.keyword in want):
            heads.append((b.keyword, b.dtype, b.count))
            if v is not None and b.keyword not in data:
                data[b.keyword] = v
    return heads, data


def _kw_table(heads):
    seen = OrderedDict()
    for k, t, c in heads:
        s = seen.get(k)
        seen[k] = (t, c, (s[2] if s else 0) + 1)
    return ["  %-8s %-5s %10d  x%d" % (k, t, c, n) for k, (t, c, n) in seen.items()]


def _rng(a):
    return "%g … %g" % (min(a), max(a)) if len(a) else "пусто"


def describe_egrid(path):
    heads, d = _headers(path, ("GRIDHEAD", "ACTNUM", "ZCORN", "MAPAXES"))
    out = ["EGRID %s" % os.path.basename(path)]
    gh = d.get("GRIDHEAD")
    if gh:
        ni, nj, nk = gh[1], gh[2], gh[3]
        out.append("  размер сетки: %d x %d x %d = %d ячеек" % (ni, nj, nk, ni * nj * nk))
    if "ACTNUM" in d:
        out.append("  активных ячеек: %d" % sum(1 for x in d["ACTNUM"] if x))
    if "ZCORN" in d:
        out.append("  глубины ZCORN, м: " + _rng(d["ZCORN"]))
    if "MAPAXES" in d:
        out.append("  MAPAXES: " + " ".join("%g" % x for x in d["MAPAXES"]))
    if any(k in ("CORSNUM", "ACTNUMC") for k, _t, _c in heads):
        out.append("  укрупнение ячеек (COARSEN):")
        out += ["    " + ln for ln in grid_info.describe(path).splitlines()[1:]]
    n_grid = sum(1 for k, _t, _c in heads if k == "GRIDHEAD")
    lgr = [k for k, _t, _c in heads if k.startswith("LGR") or k in ("ENDGRID", "ENDLGR")]
    out.append("  блоков GRIDHEAD: %d (больше одного — есть локальные сетки LGR)%s" % (n_grid, "; LGR-ключи: " + ", ".join(sorted(set(lgr))) if lgr else ""))
    out.append("  ключевые слова (имя, тип, элементов, повторов):")
    return out + _kw_table(heads)


def describe_init(path):
    heads, d = _headers(path, ("PORV", "PORO", "DEPTH", "PERMX", "NTG"))
    out = ["INIT %s" % os.path.basename(path)]
    if "PORV" in d:
        out.append("  PORV: %d значений, сумма %.6g" % (len(d["PORV"]), sum(d["PORV"])))
    for k in ("PORO", "DEPTH", "NTG", "PERMX"):
        if k in d:
            out.append("  %s: %d значений, %s" % (k, len(d[k]), _rng(d[k])))
    out.append("  ключевые слова (имя, тип, элементов, повторов):")
    return out + _kw_table(heads)


def describe_smspec(path):
    heads, d = _headers(path, ("KEYWORDS", "WGNAMES", "NAMES", "UNITS", "STARTDAT", "DIMENS"))
    out = ["SMSPEC %s" % os.path.basename(path)]
    kws = d.get("KEYWORDS", [])
    names = d.get("WGNAMES") or d.get("NAMES") or []
    units = d.get("UNITS", [])
    if "STARTDAT" in d:
        s = d["STARTDAT"]
        out.append("  начало расчёта: %04d-%02d-%02d" % (s[2], s[1], s[0]))
    out.append("  векторов: %d" % len(kws))
    cnt = OrderedDict()
    for k in kws:
        cnt[k] = cnt.get(k, 0) + 1
    out.append("  по ключевым словам (вектор: сколько): " + ", ".join("%s:%d" % kv for kv in cnt.items()))
    wells = sorted({n for k, n in zip(kws, names) if k.startswith("W") and n and not n.startswith(":+")})
    groups = sorted({n for k, n in zip(kws, names) if k.startswith("G") and n and not n.startswith(":+")})
    out.append("  скважин: %d, групп: %d" % (len(wells), len(groups)))
    if wells:
        out.append("  скважины: " + ", ".join(wells[:60]) + (" …" if len(wells) > 60 else ""))
    if groups:
        out.append("  группы: " + ", ".join(groups[:40]) + (" …" if len(groups) > 40 else ""))
    ti = kws.index("TIME") if "TIME" in kws else None
    out.append("  TIME: " + ("колонка %d, единицы %s" % (ti, units[ti] if ti is not None and ti < len(units) else "?") if ti is not None else "НЕТ"))
    return out, (ti, d.get("STARTDAT"), units[ti] if ti is not None and ti < len(units) else "")


def describe_unsmry(path, ti, startdat, unit):
    out = ["UNSMRY %s" % os.path.basename(path)]
    times = []
    with open(path, "rb") as f:
        for b, v in iter_blocks(f, lambda b: b.keyword == "PARAMS" and ti is not None):
            if v is not None:
                times.append(v[ti])
    out.append("  шагов (PARAMS): %d" % len(times))
    if times and startdat:
        s = dt.datetime(startdat[2], startdat[1], startdat[0])
        k = 1.0 if str(unit).upper().startswith("DAY") else 1.0 / 24.0
        out.append("  от %s до %s" % ((s + dt.timedelta(days=times[0] * k)).strftime("%Y-%m-%d"),
                                      (s + dt.timedelta(days=times[-1] * k)).strftime("%Y-%m-%d")))
    elif times:
        out.append("  TIME: %g … %g" % (times[0], times[-1]))
    return out


def porv_check(egrid, init):
    """Сверка PORV (на всю сетку) с активностью: помогает понять, как PORV записан при укрупнении ячеек."""
    from .ecl import read_all
    g = {b.keyword: v for b, v in read_all(egrid, ["ACTNUM", "ACTNUMC", "CORSNUM"])}
    porv = {b.keyword: v for b, v in read_all(init, ["PORV"])}.get("PORV")
    if porv is None or "ACTNUM" not in g or len(porv) != len(g["ACTNUM"]):
        return []
    tot = sum(porv)
    act = sum(v for v, a in zip(porv, g["ACTNUM"]) if a)
    out = ["PORV: сумма по всей сетке %.6g, по ячейкам ACTNUM %.6g" % (tot, act)]
    if "ACTNUMC" in g:
        out[0] += ", по ячейкам ACTNUMC %.6g" % sum(v for v, a in zip(porv, g["ACTNUMC"]) if a)
    if "CORSNUM" in g and any(g["CORSNUM"]):
        zero = sum(1 for v, c, a in zip(porv, g["CORSNUM"], g["ACTNUM"]) if c and not a and v != 0)
        out.append("PORV ненулевой в неопорных ячейках укрупнённых блоков: %d из них" % zero)
    return out


def describe(paths):
    by_ext = {}
    for p in paths:
        by_ext[os.path.splitext(p)[1].upper()] = p
    lines, tinfo = [], (None, None, "")
    if ".EGRID" in by_ext:
        lines += describe_egrid(by_ext[".EGRID"]) + [""]
    if ".INIT" in by_ext:
        lines += describe_init(by_ext[".INIT"]) + [""]
    if ".EGRID" in by_ext and ".INIT" in by_ext:
        chk = porv_check(by_ext[".EGRID"], by_ext[".INIT"])
        if chk:
            lines += ["Сверка INIT и EGRID"] + ["  " + c for c in chk] + [""]
    if ".SMSPEC" in by_ext:
        part, tinfo = describe_smspec(by_ext[".SMSPEC"])
        lines += part + [""]
    if ".UNSMRY" in by_ext:
        lines += describe_unsmry(by_ext[".UNSMRY"], *tinfo) + [""]
    if not lines:
        lines = ["Не найдено файлов .EGRID, .INIT, .SMSPEC, .UNSMRY среди: " + ", ".join(paths)]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("files", nargs="+")
    p.add_argument("-o", "--out", help="сохранить отчёт в файл")
    p.add_argument("--report-next-to", action="store_true", help="сохранить отчёт рядом с первым файлом (<имя>_model.txt)")
    a = p.parse_args(argv)
    groups = OrderedDict()  # файлы одного расчёта — с одним именем без расширения
    for f in a.files:
        groups.setdefault(os.path.splitext(f)[0], []).append(f)
    for base, files in groups.items():
        text = describe(files)
        print("=== " + os.path.basename(base))
        print(text)
        out = a.out if (a.out and len(groups) == 1) else (base + "_model.txt" if a.report_next_to else None)
        if out:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print("Отчёт сохранён: " + out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
