"""Перечисляет даты и ключевые слова рестарт-файла (UNRST), не загружая его целиком.

Запуск:  python -m tnav_results.list_restart РАСЧЁТ.UNRST [-o отчёт.txt]
         или просто  python путь/к/list_restart.py РАСЧЁТ.UNRST
Читает только заголовки блоков (данные пропускаются), поэтому 2,7 ГБ проходятся быстро.
Проверяет: есть ли SGAS и PRESSURE, на какие даты, размер массивов (LGR, двойная пористость).
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import OrderedDict

try:
    from .files import iter_restart_steps
except ImportError:  # запуск просто как скрипт: python путь/к/list_restart.py
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tnav_results.files import iter_restart_steps


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("unrst")
    p.add_argument("-o", "--out", help="сохранить отчёт в файл")
    p.add_argument("--report-next-to", action="store_true", help="сохранить отчёт рядом с UNRST (<имя>_keywords.txt)")
    a = p.parse_args(argv)
    if a.report_next_to and not a.out:
        a.out = os.path.splitext(a.unrst)[0] + "_keywords.txt"
    lines = []
    seen = OrderedDict()  # ключевое слово -> (тип, элементов, шагов)
    nsteps = 0
    for st in iter_restart_steps(a.unrst):
        if st.seqnum is None:  # служебный заголовок файла (TNAVHEAD, BASEPATH), не рестарт
            continue
        nsteps += 1
        kws = [b.keyword for b in st.blocks]
        for b in st.blocks:
            t = seen.get(b.keyword)
            seen[b.keyword] = (b.dtype, b.count, (t[2] if t else 0) + 1)
        lines.append("шаг %s: %s" % (st.seqnum, st.date.strftime("%Y-%m-%d %H:%M") if st.date else "дата не определена"))
    lines.append("")
    lines.append("Всего шагов: %d" % nsteps)
    lines.append("Ключевые слова (имя, тип, элементов, в скольких шагах):")
    for k, (t, c, n) in seen.items():
        lines.append("  %-8s %-5s %10d  %d" % (k, t, c, n))
    for need in ("SGAS", "PRESSURE"):
        lines.append("%s: %s" % (need, "есть" if need in seen else "НЕТ"))
    text = "\n".join(lines)
    print(text)
    if a.out:
        print("\nОтчёт сохранён: " + a.out)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
