"""Запуск «Скедул ПХГ»: python -m schedule_pxg (окно приложения), --browser (в браузере), --server [порт] (только сервер)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def serve(port: int = 8768) -> int:
    import uvicorn
    print("«Скедул ПХГ» открыт на http://127.0.0.1:%d (остановить: Ctrl+C)" % port)
    uvicorn.run("schedule_pxg.api:app", host="127.0.0.1", port=port, log_level="warning")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--server":
        return serve(int(argv[1]) if len(argv) > 1 else 8768)
    from pxg_base.window import run
    from .api import build_app
    return run(browser=bool(argv and argv[0] == "--browser"), title="Скедул ПХГ", app_factory=build_app)


if __name__ == "__main__":
    sys.exit(main())
