"""Общая папка «выгрузки»: после успешного запуска файлы копируются туда (аудит «Базы ПХГ», шаг 1)."""
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_base import jobs  # noqa: E402
from pxg_core import workspace  # noqa: E402


def test_export_dir_default_and_env(tmp_path, monkeypatch):
    monkeypatch.delenv("PXG_EXPORT_DIR", raising=False)
    assert jobs.export_dir().name == "выгрузки"
    monkeypatch.setenv("PXG_EXPORT_DIR", str(tmp_path / "общая"))
    assert jobs.export_dir() == (tmp_path / "общая").resolve()


def test_successful_job_copies_files_to_export_dir(tmp_path, monkeypatch):
    out = tmp_path / "run"
    out.mkdir()
    (out / "результаты.xlsx").write_bytes(b"data")
    target = tmp_path / "выгрузки"
    monkeypatch.setenv("PXG_EXPORT_DIR", str(target))

    job = jobs.Job("m", {}, out)
    job.status = "running"
    # имитируем завершение: файлы уже лежат в папке запуска, код возврата 0
    monkeypatch.setattr(jobs.subprocess, "Popen", _fake_popen(0))
    monkeypatch.setattr(jobs, "MODULES_DIR", tmp_path)
    (tmp_path / "m.py").write_text("", encoding="utf-8")
    jobs._run(job, _spec())
    assert job.status == "done"
    assert (target / "результаты.xlsx").read_bytes() == b"data"


class _Pipe:
    def __init__(self):
        self.lines = iter([])

    def write(self, _):
        pass

    def close(self):
        pass

    def __iter__(self):
        return self.lines


def _fake_popen(code):
    class P:
        def __init__(self, *a, **k):
            self.stdin = _Pipe()
            self.stdout = _Pipe()

        def wait(self):
            return code
    return P


class _spec:  # noqa: N801 — минимальная подмена WebSpec для _run
    def __new__(cls):
        return cls

    @staticmethod
    def dialog_config(values):
        return {}

    @staticmethod
    def env_values(values):
        return {}

    @staticmethod
    def argv(values):
        return []

    @staticmethod
    def build_stdin(values):
        return ""


def test_export_dir_follows_chosen_project(tmp_path, monkeypatch):
    # без PXG_EXPORT_DIR папка выгрузок — подпапка «выгрузки» выбранного проекта
    monkeypatch.delenv("PXG_EXPORT_DIR", raising=False)
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    project = tmp_path / "проект"
    project.mkdir()
    workspace.save(str(project))
    assert jobs.export_dir() == (project / "выгрузки").resolve()
    # переменная окружения сильнее выбора проекта
    monkeypatch.setenv("PXG_EXPORT_DIR", str(tmp_path / "другая"))
    assert jobs.export_dir() == (tmp_path / "другая").resolve()
