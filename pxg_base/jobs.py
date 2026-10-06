"""Запуск консольных модулей как фоновых задач: подпроцесс, ввод из формы, журнал, файлы результата."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from .registry import MODULES
from .webspec import WebSpec, get as get_spec, lines_of

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = Path(__file__).resolve().parent / "modules"


def runs_dir() -> Path:
    """Куда складываются результаты запусков (по умолчанию ./pxg_runs, меняется PXG_RUNS_DIR)."""
    return Path(os.environ.get("PXG_RUNS_DIR") or "pxg_runs").resolve()


class Job:
    def __init__(self, module: str, values: Dict[str, str], out_dir: Path):
        self.id = uuid.uuid4().hex[:12]
        self.module = module
        self.values = values
        self.out_dir = out_dir
        self.log: List[str] = []
        self.status = "running"          # running | done | failed
        self.started = time.time()
        self.finished: Optional[float] = None
        self.files: List[str] = []
        self.sizes: Dict[str, int] = {}
        self.lock = threading.Lock()

    def view(self, since: int = 0) -> dict:
        with self.lock:
            return {
                "id": self.id, "module": self.module, "status": self.status,
                "started": self.started, "finished": self.finished,
                "out_dir": str(self.out_dir), "files": list(self.files), "sizes": dict(self.sizes),
                "values": dict(self.values),
                "log": self.log[since:], "log_len": len(self.log),
            }


JOBS: Dict[str, Job] = {}


def _snapshot(d: Path) -> Dict[str, float]:
    return {str(p.relative_to(d)): p.stat().st_mtime for p in d.rglob("*") if p.is_file()}


def _run(job: Job, spec: WebSpec) -> None:
    path = MODULES_DIR / (job.module + ".py")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PXG_WEB"] = "1"
    env["PXG_DIALOGS"] = json.dumps(spec.dialog_config(job.values), ensure_ascii=False)
    env.update(spec.env_values(job.values))
    code = -1
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).with_name("runner.py")), str(path)] + spec.argv(job.values), cwd=str(job.out_dir), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, encoding="utf-8", errors="replace")
        try:
            proc.stdin.write(spec.build_stdin(job.values))
            proc.stdin.close()
        except OSError:
            pass
        for line in proc.stdout:
            with job.lock:
                job.log.append(line.rstrip("\n"))
        code = proc.wait()
    except Exception as e:  # не удалось запустить подпроцесс
        with job.lock:
            job.log.append("Не удалось запустить модуль: %s" % e)
    with job.lock:
        job.files = sorted(_snapshot(job.out_dir))
        job.sizes = {f: (job.out_dir / f).stat().st_size for f in job.files}
        job.status = "done" if code == 0 else "failed"
        job.finished = time.time()


def start(module: str, values: Dict[str, str]) -> Job:
    spec = get_spec(module)
    if spec is None or module not in {m[1] for m in MODULES}:
        raise KeyError(module)
    for p in spec.params:
        if p.required and not (values.get(p.id) or "").strip():
            raise ValueError("Заполните поле «%s»." % p.label)
        if p.kind == "paths":
            for line in lines_of(values.get(p.id, "")):
                if not os.path.exists(line):
                    raise ValueError("«%s»: путь не найден: %s" % (p.label, line))
        if p.kind in ("folder", "file") and (values.get(p.id) or "").strip():
            v = values[p.id].strip()
            ok = os.path.isdir(v) if p.kind == "folder" else os.path.isfile(v)
            if not ok:
                raise ValueError("«%s»: путь не найден: %s" % (p.label, v))
    base = Path((values.get("out_dir") or "").strip()) if (values.get("out_dir") or "").strip() else \
        runs_dir() / time.strftime("%Y%m%d_%H%M%S")
    base.mkdir(parents=True, exist_ok=True)
    # пути из формы абсолютные: подпроцесс стартует в папке результатов
    vals = dict(values)
    for p in spec.params:
        if p.kind in ("folder", "file") and (vals.get(p.id) or "").strip():
            vals[p.id] = os.path.abspath(vals[p.id].strip())
        elif p.kind == "paths":
            vals[p.id] = "\n".join(os.path.abspath(x) for x in lines_of(vals.get(p.id, "")))
    job = Job(module, vals, base.resolve())
    JOBS[job.id] = job
    threading.Thread(target=_run, args=(job, spec), daemon=True).start()
    return job
