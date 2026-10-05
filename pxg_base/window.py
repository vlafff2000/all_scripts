"""Окно приложения «Базы ПХГ»: сервер на свободном порту внутри процесса + окно pywebview (или браузер).

Отдельный сервер запускать не нужно: всё живёт в одном процессе, закрыли окно — всё остановилось.
"""
from __future__ import annotations

import socket
import threading
import time
import webbrowser


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(port: int, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run(browser: bool = False, port: int = 0, title: str = "База ПХГ", app_factory=None) -> int:
    import uvicorn

    if app_factory is None:
        from .api import build_app as app_factory

    port = port or free_port()
    url = "http://127.0.0.1:%d/" % port
    server = uvicorn.Server(uvicorn.Config(app_factory(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if not wait_ready(port):
        print("Сервер не запустился")
        return 1

    webview = None
    if not browser:
        try:
            import webview  # pywebview
        except Exception as error:  # нет пакета или не загрузился .NET
            print("Окно приложения недоступно (%s), открываю в браузере" % error)
    if webview is not None:
        try:
            webview.settings["ALLOW_DOWNLOADS"] = True
        except (AttributeError, TypeError):
            pass
        try:
            webview.create_window(title, url, width=1280, height=860, min_size=(900, 600))
            webview.start()
            server.should_exit = True
            return 0
        except Exception as error:  # например, нет WebView2
            print("Окно приложения не открылось (%s), открываю в браузере" % error)
    webbrowser.open(url)
    print("%s: %s  (остановка: Ctrl+C)" % (title, url))
    try:
        thread.join()
    except KeyboardInterrupt:
        server.should_exit = True
    return 0
