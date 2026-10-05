"""Запуск «Базы ПХГ»: python -m pxg_base (меню), python -m pxg_base <номер|имя модуля>, python -m pxg_base --app (окно приложения), --browser (в браузере), --server (только сервер)."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

from .registry import MODULES

MODULES_DIR = Path(__file__).parent / "modules"
# общий пакет pxg_core лежит в корне репозитория
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def show_menu() -> None:
    group = None
    for i, (g, name, desc) in enumerate(MODULES, 1):
        if g != group:
            group = g
            print(f"\n{g}")
        print(f"  {i:2}. {name}\n      {desc}")
    print()


def pick(arg: str):
    if arg.isdigit() and 1 <= int(arg) <= len(MODULES):
        return MODULES[int(arg) - 1]
    for m in MODULES:
        if arg == m[1]:
            return m
    return None


def serve(port: int = 8766) -> int:
    import uvicorn
    print("«База ПХГ» открыта на http://127.0.0.1:%d (остановить: Ctrl+C)" % port)
    uvicorn.run("pxg_base.api:app", host="127.0.0.1", port=port, log_level="warning")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--server":
        return serve(int(argv[1]) if len(argv) > 1 else 8766)
    if argv and argv[0] in ("--app", "--browser"):
        from .window import run
        return run(browser=argv[0] == "--browser")
    if argv:
        choice = pick(argv[0])
    else:
        show_menu()
        choice = pick(input("Номер модуля (Enter — выход): ").strip())
    if choice is None:
        return 0
    path = MODULES_DIR / (choice[1] + ".py")
    print(f"\n=== {choice[1]} ===\n")
    # скрипты интерактивные и запускаются как отдельные программы
    sys.argv = [str(path)] + argv[1:]
    runpy.run_path(str(path), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
