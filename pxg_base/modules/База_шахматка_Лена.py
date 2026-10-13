"""База_шахматка_Лена: шахматки отбора и закачки (по файлу на сезон) и книги воды в единую базу (Excel и SQLite).

Параметры: --files (файлы, папки или маски, по одному в строке; вид каждого файла определяется по содержимому),
--output, --otbor-year, --zak-year. Берётся Qгаз.пром: пересчитывается по исходным данным и сравнивается с файловым;
ошибки формул — на листе «Контроль_формул».
"""
from __future__ import annotations

import os
import warnings

from pxg_core import параметры, шахматка


warnings.filterwarnings("ignore", message="Print area cannot be set", category=UserWarning)
warnings.filterwarnings("ignore", message="The behavior of DataFrame concatenation", category=FutureWarning)


def _year(text):
    try:
        return int(str(text).strip()) if text not in (None, "") else None
    except ValueError:
        return None


def main(argv=None):
    args = параметры.parse(
        "База шахматка (Лена)", argv,
        files="файлы, папки или маски (по одному в строке, через перевод строки)", output="имя файла результата",
        otbor_year="год первых суток отбора (по умолчанию из имени файла)", zak_year="год первых суток закачки (по умолчанию из имени файла)",
        years="годы по файлам: строки «часть имени = год», для файлов, где год не определился сам",
        xls_formulas="1 — проверять формулы в .xls через LibreOffice (медленно)")
    raw = args.files if args.files is not None else параметры.ask("Файлы шахматок и воды (через ;)").replace(";", "\n")
    files = шахматка.expand_paths([x for x in (raw or "").splitlines()])
    if not files:
        print("❌ Не выбрано ни одного файла Excel.")
        return 1
    out = (args.output or "").strip() or "База_шахматка_Лена.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    res = шахматка.build(files, out, _year(args.otbor_year), _year(args.zak_year),
                          years=args.years or "",
                          xls_formulas=str(args.xls_formulas or "").strip().lower() in ("1", "y", "yes", "true", "да"))
    issues = res["issues"]
    if len(issues):
        bad = int((issues["Уровень"] == "ошибка").sum())
        print("⚠️ Замечаний к файлам: %d (ошибок %d), подробности на листе «Контроль_формул»" % (len(issues), bad))
        for _i, r in issues[issues["Уровень"] == "ошибка"].head(12).iterrows():
            print("   • [%s] %s: %s" % (r["Файл"], r["Вид"], str(r["Описание"])[:160]))
    print("✅ %s и %s: файлов %d, скважин %d" % (os.path.basename(res["out"]), os.path.basename(res["sqlite"]), res["files"], res["wells"]))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
