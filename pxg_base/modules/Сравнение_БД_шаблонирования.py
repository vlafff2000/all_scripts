"""Сравнение двух БД шаблонирования: прежней (по Excel) и новой (из отчётов) → «Сравнение_БД_шаблонирования.xlsx».

Сопоставление по скважине и году (на пару берётся самая глубокая отбивка). Листы: «Сводка» (штуки и проценты), «Совпало», «Расхождения»
(глубина старая/новая, разница, источник новой), «Только в старой», «Только в новой». Допуск по глубине задаётся (по умолчанию 1 м).
Ничего не перезаписывается: в листах есть столбец «Решение инженера»; заполненную книгу можно подать как --marks, решения перенесутся в новую выгрузку.
"""
from __future__ import annotations

import os
import sys

from pxg_core import templating_db, параметры

_ = sys


def main(argv=None):
    args = параметры.parse("Сравнение БД шаблонирования", argv,
                           old="прежняя БД: Excel (скважина, год, глубина) или БД_шаблонирования.xlsx",
                           new="новая БД: БД_шаблонирования.xlsx, templating_db.* или папка с ними",
                           tol="допуск по глубине, м (по умолчанию 1)", marks="прежняя выгрузка сравнения с решениями инженера, необязательно")
    old = параметры.ask_path("Прежняя БД шаблонирования (файл)", args.old, "file")
    new = параметры.ask_path("Новая БД шаблонирования (файл или папка)", args.new, "file")
    if not old or not new:
        print("❌ Нужны обе БД.")
        return 1
    try:
        tol = float((args.tol or "1").replace(",", ".") or 1)
        path, frames = templating_db.export_compare(old, new, os.getcwd(), tol, параметры.clean_path(args.marks or ""))
    except (ValueError, OSError) as e:
        print("❌ %s" % e)
        return 1
    for _i, r in frames["Сводка"].iterrows():
        print("%s: %s" % (r["Показатель"], r["Значение"]))
    print("✅ %s" % os.path.basename(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
