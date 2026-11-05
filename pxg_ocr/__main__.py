"""Запуск «Распознавания»: python -m pxg_ocr (окно приложения), --browser (в браузере), --server [порт] (только сервер)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _no_console() -> None:
    import os
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _exit_when_tab_closed(idle: float = 180.0) -> None:
    import os
    import threading
    import time
    from . import api

    def watch() -> None:
        while True:
            time.sleep(5)
            if api.LAST_PING and time.monotonic() - api.LAST_PING > idle:
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def serve(port: int = 8770) -> int:
    import uvicorn
    print("«Распознавание» открыто на http://127.0.0.1:%d (остановить: Ctrl+C)" % port)
    uvicorn.run("pxg_ocr.api:app", host="127.0.0.1", port=port, log_level="warning")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _no_console()
    if argv and argv[0] == "--server":
        return serve(int(argv[1]) if len(argv) > 1 else 8770)
    import os
    from pxg_base.window import run
    from .api import build_app
    if argv and argv[0] == "--browser":
        _exit_when_tab_closed()
    profile = os.path.join(os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg"), "ocr_window")
    return run(browser=bool(argv and argv[0] == "--browser"), title="Распознавание", app_factory=build_app, app_profile=profile)


if __name__ == "__main__":
    sys.exit(main())
