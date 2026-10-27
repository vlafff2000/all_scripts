"""Запуск «Поисковика»: python -m pxg_finder (окно приложения), --browser (в браузере), --server [порт] (только сервер)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _no_console() -> None:
    """pythonw.exe (ярлык без окна консоли) не даёт потоков вывода: подставляем пустые, иначе сервер падает при первой записи."""
    import os
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _exit_when_tab_closed(idle: float = 180.0) -> None:
    """Режим браузера: страница шлёт сигнал раз в несколько секунд; закрыли вкладку — сервер завершается, лишних процессов не остаётся."""
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


def serve(port: int = 8769) -> int:
    import uvicorn
    print("«Поисковик» открыт на http://127.0.0.1:%d (остановить: Ctrl+C)" % port)
    uvicorn.run("pxg_finder.api:app", host="127.0.0.1", port=port, log_level="warning")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _no_console()
    import os
    folder = next((a for a in argv if not a.startswith("--") and not a.isdigit() and os.path.isdir(a)), "")
    if folder:  # папка из аргумента (пункт меню папки, «папки по умолчанию») открывается в новой вкладке
        os.environ["PXG_FINDER_START"] = os.path.abspath(folder)
        argv = [a for a in argv if a != folder]
    if argv and argv[0] == "--server":
        return serve(int(argv[1]) if len(argv) > 1 else 8769)
    from pxg_base.window import run
    from .api import build_app
    if argv and argv[0] == "--browser":
        _exit_when_tab_closed()
    return run(browser=bool(argv and argv[0] == "--browser"), title="Поисковик", app_factory=build_app)


if __name__ == "__main__":
    sys.exit(main())
