from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bp():
    spec = importlib.util.spec_from_file_location("bp_launch", os.path.join(ROOT, "tools", "build_portable.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["bp_launch"] = m
    spec.loader.exec_module(m)
    return m


@pytest.mark.skipif(os.name == "nt", reason="bash")
def test_oneshot_launchers_report_without_terminal(tmp_path):
    bp = _bp()
    bp.write_launchers("linux", tmp_path)
    assert not list(tmp_path.glob("*.desktop"))  # .desktop рядом со скриптами не кладём: файловый менеджер не доверяет им
    (tmp_path / "python" / "bin").mkdir(parents=True)
    py = tmp_path / "python" / "bin" / "python3.13"
    py.write_text('#!/bin/sh\necho "результат $*"; exit ${FAIL:-0}\n')
    py.chmod(0o755)
    (tmp_path / "bin").mkdir()
    z = tmp_path / "bin" / "zenity"
    z.write_text('#!/bin/sh\necho "$*" >> "%s"\n' % (tmp_path / "z.txt"))
    z.chmod(0o755)
    for fail in ("0", "3"):
        subprocess.run(["bash", "sozdat_yarlyki.sh"], cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True,
                       env={"PATH": "%s:/usr/bin:/bin" % (tmp_path / "bin"), "FAIL": fail})
    shown = (tmp_path / "z.txt").read_text(encoding="utf-8")
    assert "результат" in shown and "Ошибка (код 3)" in shown and "logs_zapusk" in shown
    assert len(list((tmp_path / "logs_zapusk").iterdir())) >= 1
