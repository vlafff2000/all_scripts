"""Окно приложения без pywebview (РЕД ОС): Chromium-браузер запускается с --app и отдельным профилем."""
from __future__ import annotations

from pxg_base import window


def test_app_window_uses_chromium_app_mode(monkeypatch, tmp_path):
    calls = []

    class FakeProc:
        pass

    monkeypatch.setattr(window, "chromium_path", lambda: "/usr/bin/yandex-browser")
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kw: calls.append(cmd) or FakeProc())
    assert window.app_window("http://127.0.0.1:1/", str(tmp_path)) is not None
    cmd = calls[0]
    assert cmd[0] == "/usr/bin/yandex-browser"
    assert "--app=http://127.0.0.1:1/" in cmd
    assert "--user-data-dir=" + str(tmp_path) in cmd


def test_app_window_without_browser(monkeypatch):
    monkeypatch.setattr(window, "chromium_path", lambda: "")
    assert window.app_window("http://127.0.0.1:1/", "x") is None


def test_chromium_path_finds_yandex(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/opt/yb" if n == "yandex-browser" else None)
    assert window.chromium_path() == "/opt/yb"
