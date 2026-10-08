"""Диагностика сетки EGRID с укрупнением ячеек (COARSEN): как соотносятся ACTNUM, ACTNUMC и CORSNUM.

Запуск:  python -m tnav_results.grid_info РАСЧЁТ.EGRID [ЧИСЛО_АКТИВНЫХ_В_INIT]
Читает только ACTNUM, ACTNUMC, CORSNUM, GRIDHEAD (ZCORN пропускается), поэтому работает быстро.
"""
from __future__ import annotations

import sys
from collections import Counter

try:
    from .ecl import read_all
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tnav_results.ecl import read_all


def describe(path: str, n_init: int = 0) -> str:
    d = {b.keyword: v for b, v in read_all(path, ["GRIDHEAD", "ACTNUM", "ACTNUMC", "CORSNUM"])}
    h = d["GRIDHEAD"]
    total = h[1] * h[2] * h[3]
    out = ["сетка %d x %d x %d = %d ячеек" % (h[1], h[2], h[3], total)]
    act, actc, cor = d.get("ACTNUM"), d.get("ACTNUMC"), d.get("CORSNUM")
    n_act = sum(1 for a in act if a) if act is not None else None
    n_actc = sum(1 for a in actc if a) if actc is not None else None
    out.append("ACTNUM > 0: %s;  ACTNUMC > 0: %s;  в INIT/UNRST на активную ячейку: %s"
               % (n_act, n_actc, n_init or "не задано"))
    if cor is not None:
        groups = Counter(c for c in cor if c)
        out.append("CORSNUM: ячеек в укрупнённых блоках %d, блоков %d, размеры блоков (ячеек: сколько блоков) %s"
                   % (sum(groups.values()), len(groups), dict(Counter(groups.values()).most_common(6))))
        if act is not None:
            single = sum(1 for a, c in zip(act, cor) if a and not c)
            blocks = len({c for a, c in zip(act, cor) if a and c})
            out.append("активные неукрупнённые + блоки с активными ячейками = %d + %d = %d" % (single, blocks, single + blocks))
        if actc is not None and act is not None:
            out.append("ACTNUMC и ACTNUM различаются в %d ячейках" % sum(1 for a, b in zip(act, actc) if bool(a) != bool(b)))
    else:
        out.append("CORSNUM нет: укрупнения в сетке нет")
    return "\n".join(out)


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if not a:
        print(__doc__)
        return 2
    print(describe(a[0], int(a[1]) if len(a) > 1 else 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
