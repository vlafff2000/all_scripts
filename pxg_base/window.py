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


_second: dict = {"open": None}


def open_second(hash_part: str = "") -> bool:
    """Открыть второе окно той же программы (для второго монитора); False, если окно открыть нечем (сервер без окна)."""
    fn = _second["open"]
    if fn is None:
        return False
    try:
        fn("#" + hash_part.lstrip("#") if hash_part else "")
    except Exception:
        return False
    return True


def second_window_route():
    """Маршрут POST /api/second-window {hash}: оба окна обслуживает один и тот же сервер."""
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def handler(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        part = str(body.get("hash", ""))[:100] if isinstance(body, dict) else ""
        return JSONResponse({"opened": open_second(part)})
    return Route("/api/second-window", handler, methods=["POST"])


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
            webview.create_window(title, url, width=1280, height=860, min_size=(900, 600))
            _second["open"] = lambda h: webview.create_window(title + " — окно 2", url + h, width=1280, height=860, min_size=(900, 600))
            webview.start()
            server.should_exit = True
            return 0
        except Exception as error:  # например, нет WebView2
            print("Окно приложения не открылось (%s), открываю в браузере" % error)
    _second["open"] = lambda h: webbrowser.open(url + h)
    if not app_profile:  # профиль по умолчанию: свой у каждой программы, обычный браузер пользователя не затрагивается
        import os
        import re
        slug = re.sub(r"[^0-9A-Za-zА-Яа-я]+", "_", title).strip("_") or "app"
        app_profile = os.path.join(os.path.expanduser("~"), ".pxg", "app_window", slug)
    if app_profile:  # окно приложения через Chromium (Яндекс, Chromium, Chrome); закрыли окно — сервер останавливается
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
