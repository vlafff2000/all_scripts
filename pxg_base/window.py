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


_CHROMIUM = ("yandex-browser", "yandex-browser-stable", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
             "chrome", "brave-browser", "microsoft-edge", "microsoft-edge-stable")


def chromium_path() -> str:
    """Браузер на движке Chromium (Яндекс, Chromium, Chrome, Edge): умеет открывать страницу окном приложения без адресной строки."""
    import os
    import shutil
    for name in _CHROMIUM:
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            path = os.path.join(base, rel) if base else ""
            if path and os.path.isfile(path):
                return path
    return ""


def app_window(url: str, profile: str):
    """Отдельное окно приложения (без вкладок и адресной строки, своя группа на панели задач); None, если подходящего браузера нет."""
    import subprocess
    exe = chromium_path()
    if not exe:
        return None
    try:
        return subprocess.Popen([exe, "--app=" + url, "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check",
                                 "--class=PxgApp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def run(browser: bool = False, port: int = 0, title: str = "Работа с исходными данными", app_factory=None, app_profile: str = "") -> int:
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
            from pxg_core.desktop_save import SaveApi

            saver = SaveApi()
            saver.bind(webview.create_window(title, url, width=1280, height=860, min_size=(900, 600), js_api=saver))
            webview.start()
            server.should_exit = True
            return 0
        except Exception as error:  # например, нет WebView2
            print("Окно приложения не открылось (%s), открываю в браузере" % error)
    if app_profile:  # окно приложения через Chromium; закрыли окно — сервер останавливается
        proc = app_window(url, app_profile)
        if proc is not None:
            started = time.monotonic()
            try:
                proc.wait()
            except KeyboardInterrupt:
                pass
            if time.monotonic() - started > 5:  # браузер не подхватил чужой экземпляр: окно закрыто пользователем
                server.should_exit = True
                return 0
            print("%s: окно открыто в уже запущенном браузере (остановка: Ctrl+C)" % title)
            try:
                thread.join()
            except KeyboardInterrupt:
                server.should_exit = True
            return 0
    webbrowser.open(url)
    print("%s: %s  (остановка: Ctrl+C)" % (title, url))
    try:
        thread.join()
    except KeyboardInterrupt:
        server.should_exit = True
    return 0
