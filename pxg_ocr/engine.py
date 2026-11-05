"""Распознавание (OCR) через локальный MinerU: поиск движка, режимы CPU/GPU с лимитом видеопамяти, запуск и результат.

Движок лежит в папке OCR: свой Python с MinerU (``python`` или ``mineru-env``) и модели (``mineru-home``). Папка ищется
в PXG_OCR_HOME, затем ``ocr`` рядом с программой, затем C:\\OCR. Устанавливать ничего не нужно: всё автономно и без интернета.
Только стандартная библиотека. Запуск: ``mineru-kit parse файл -o результат.zip -f zip --tier standard``.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
TIERS = {"standard": "Точный (рекомендуется для русского)", "basic": "Быстрый (кириллицу читает плохо)", "flash": "Самый быстрый (кириллицу не читает)"}
OCR_MODES = {"ocr": "Скан: распознавать всё", "auto": "Авто: слой текста, где он есть", "txt": "Только слой текста"}
MODES = {"auto": "Авто (видеокарта, если хватает памяти)", "gpu": "Видеокарта", "cpu": "Только процессор"}
SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".docx", ".pptx", ".xlsx"}
VRAM_RESERVE_GB = 2.0  # запас под рабочий стол и драйвер
VRAM_MIN_GB = 5.0  # меньше — слабая карта (1050 Ti, 1650): считаем на процессоре
VRAM_MAX_GB = 6.0  # потолок MinerU на ПК с 8 ГБ проверен как стабильный


def home() -> Optional[Path]:
    """Папка с движком или None, если его нет."""
    candidates = [os.environ.get("PXG_OCR_HOME") or "", str(ROOT / "ocr"), r"C:\OCR" if os.name == "nt" else ""]
    for c in candidates:
        if c and (Path(c) / "mineru-home").is_dir() and python_exe(Path(c)):
            return Path(c)
    return None


def python_exe(h: Path) -> Optional[Path]:
    for rel in ("python/python.exe", "python/bin/python3", "mineru-env/Scripts/python.exe", "mineru-env/bin/python"):
        if (h / rel).is_file():
            return h / rel
    return None


def out_root() -> Path:
    base = os.environ.get("PXG_OCR_OUT")
    if base:
        return Path(base)
    project = os.environ.get("PXG_PROJECT")
    return Path(project) / "OCR" if project else Path(os.environ.get("PXG_HOME") or Path.home() / ".pxg") / "ocr"


def hardware() -> Dict[str, Any]:
    """Ядра, видеокарта NVIDIA (имя, память всего/свободно, ГБ). Без nvidia-smi — видеокарты нет."""
    info: Dict[str, Any] = {"cores": os.cpu_count() or 1, "gpu": None}
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0 and out.stdout.strip():
            name, total, free = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
            info["gpu"] = {"name": name, "total_gb": round(float(total) / 1024, 1), "free_gb": round(float(free) / 1024, 1)}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return info


def plan(mode: str, hw: Dict[str, Any]) -> Dict[str, Any]:
    """Что реально будет использовано: режим, лимит видеопамяти (ГБ), число потоков и причина выбора."""
    gpu = hw.get("gpu")
    threads = max(2, (hw.get("cores") or 2) // 2)
    cpu = {"mode": "cpu", "vram_gb": 0.0, "threads": threads}
    if mode == "cpu":
        return {**cpu, "why": "выбран режим «Только процессор»"}
    if not gpu:
        return {**cpu, "why": "видеокарта NVIDIA не найдена"}
    usable = min(VRAM_MAX_GB, round(gpu["free_gb"] - VRAM_RESERVE_GB, 1))
    if usable < VRAM_MIN_GB:
        if mode == "gpu":
            return {"mode": "gpu", "vram_gb": max(usable, 1.0), "threads": threads, "why": "видеопамяти мало, возможны ошибки: надёжнее режим «Только процессор»"}
        return {**cpu, "why": "видеопамяти мало (%s ГБ свободно): считаем на процессоре, ошибок памяти не будет" % gpu["free_gb"]}
    return {"mode": "gpu", "vram_gb": usable, "threads": threads, "why": "%s, лимит видеопамяти %s ГБ" % (gpu["name"], usable)}


def build_env(h: Path, p: Dict[str, Any]) -> Dict[str, str]:
    env = dict(os.environ)
    env.update({"MINERU_HOME": str(h / "mineru-home"), "MINERU_TELEMETRY_DISABLED": "1", "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1",
                "MINERU_CPU_NUM_THREADS": str(p["threads"])})
    if p["mode"] == "cpu":
        env.update({"MINERU_DEVICE_MODE": "cpu", "MINERU_LLAMA_CPP_BACKEND": "cpu", "MINERU_MODEL_ONNX_DEVICE": "cpu"})
    else:
        env["MINERU_VIRTUAL_VRAM_SIZE"] = str(int(p["vram_gb"]))
    return env


def build_cmd(py: Path, src: str, out_zip: str, tier: str, ocr_mode: str, pages: str) -> List[str]:
    cmd = [str(py), "-s", "-X", "utf8", "-c", "from mineru.kit.main import main; main()", "parse", src, "-o", out_zip, "-f", "zip",
           "--tier", tier, "--ocr-mode", ocr_mode, "-p", pages or "all"]
    return cmd


class Job:
    def __init__(self, src: str, params: Dict[str, Any]):
        self.id = uuid.uuid4().hex[:10]
        self.src = src
        self.params = params
        self.dir = out_root() / ("%s_%s" % (dt.datetime.now().strftime("%Y%m%d_%H%M%S"), re.sub(r"[^\w.-]+", "_", Path(src).stem)[:60]))
        self.state = "queued"  # queued | running | done | error | cancelled
        self.error = ""
        self.log: List[str] = []
        self.plan: Dict[str, Any] = {}
        self.t0 = time.monotonic()
        self.t1 = 0.0
        self.proc: Optional[subprocess.Popen] = None
        self.cancel = threading.Event()

    def snapshot(self) -> Dict[str, Any]:
        return {"id": self.id, "src": self.src, "name": Path(self.src).name, "state": self.state, "error": self.error, "log": self.log[-30:],
                "plan": self.plan, "params": self.params, "dir": str(self.dir), "elapsed": round((self.t1 or time.monotonic()) - self.t0, 1)}


_jobs: Dict[str, Job] = {}
_lock = threading.Lock()
_run_lock = threading.Lock()  # распознавание грузит весь ПК: файлы идут по одному


def get(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)


def start(src: str, tier: str = "standard", mode: str = "auto", ocr_mode: str = "ocr", pages: str = "all") -> Job:
    if not os.path.isfile(src):
        raise ValueError("Файл не найден: %s" % src)
    if Path(src).suffix.lower() not in SUFFIXES:
        raise ValueError("Этот тип файла не читается. Подходят: PDF, изображения, Word, Excel, PowerPoint.")
    if tier not in TIERS or mode not in MODES or ocr_mode not in OCR_MODES:
        raise ValueError("Неизвестный режим распознавания.")
    if pages != "all" and not re.fullmatch(r"r?\d+(-r?\d+)?(,r?\d+(-r?\d+)?)*", pages):
        raise ValueError("Страницы: all, 1-5 или 1-5,8 (r3-r1 — с конца).")
    if home() is None:
        raise ValueError("Движок распознавания не найден. Положите папку ocr рядом с программой или задайте PXG_OCR_HOME.")
    job = Job(src, {"tier": tier, "mode": mode, "ocr_mode": ocr_mode, "pages": pages})
    with _lock:
        _jobs[job.id] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job


def cancel(job_id: str) -> bool:
    job = get(job_id)
    if job is None:
        return False
    job.cancel.set()
    if job.proc and job.proc.poll() is None:
        job.proc.kill()
    return True


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError("Недопустимый путь в архиве результата: %s" % m.filename)
        z.extractall(dest)


def collect(job_dir: Path) -> Dict[str, Any]:
    """Файлы результата: markdown и JSON (первый подходящий), остальное (картинки) отдельно."""
    files = sorted(p for p in job_dir.rglob("*") if p.is_file() and p.name not in ("meta.json", "result.zip"))
    md = next((p for p in files if p.suffix == ".md"), None)
    js = next((p for p in files if p.suffix == ".json" and "middle" in p.name), None) or next((p for p in files if p.suffix == ".json"), None)
    rel = lambda p: p.relative_to(job_dir).as_posix() if p else ""  # noqa: E731
    return {"md": rel(md), "json": rel(js), "files": [rel(p) for p in files]}


def _run(job: Job) -> None:
    with _run_lock:
        if job.cancel.is_set():
            job.state, job.t1 = "cancelled", time.monotonic()
            return
        job.state = "running"
        job.t0 = time.monotonic()
        try:
            h = home()
            assert h is not None
            hw = hardware()
            job.plan = plan(job.params["mode"], hw)
            job.dir.mkdir(parents=True, exist_ok=True)
            zip_path = job.dir / "result.zip"
            cmd = build_cmd(python_exe(h), job.src, str(zip_path), job.params["tier"], job.params["ocr_mode"], job.params["pages"])  # type: ignore[arg-type]
            job.log.append("Режим: %s (%s)" % ("видеокарта" if job.plan["mode"] == "gpu" else "процессор", job.plan["why"]))
            job.proc = subprocess.Popen(cmd, env=build_env(h, job.plan), cwd=str(job.dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert job.proc.stdout is not None
            for line in job.proc.stdout:
                line = line.rstrip()
                if line:
                    job.log.append(line[:300])
            code = job.proc.wait()
            if job.cancel.is_set():
                job.state = "cancelled"
            elif code != 0 or not zip_path.is_file():
                job.state, job.error = "error", _explain(job.log)
            else:
                _safe_extract(zip_path, job.dir)
                zip_path.unlink()
                job.state = "done"
        except Exception as e:  # noqa: BLE001 - причина показывается в окне
            job.state, job.error = "error", "%s: %s" % (type(e).__name__, e)
        finally:
            job.t1 = time.monotonic()
            try:
                job.dir.mkdir(parents=True, exist_ok=True)
                (job.dir / "meta.json").write_text(json.dumps({**job.snapshot(), "result": collect(job.dir) if job.state == "done" else {}},
                                                              ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                pass


def _explain(log: List[str]) -> str:
    text = "\n".join(log[-15:])
    low = text.lower()
    if "out of memory" in low or "cuda" in low and "memory" in low:
        return "Не хватило видеопамяти. Выберите режим «Только процессор»."
    if "not found" in low and "model" in low:
        return "Не найдены модели распознавания (папка mineru-home)."
    return "Распознавание не удалось. " + (log[-1] if log else "Подробности в журнале.")


def history(limit: int = 50) -> List[Dict[str, Any]]:
    root = out_root()
    rows = []
    if root.is_dir():
        for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)[:limit]:
            try:
                rows.append(json.loads((d / "meta.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return rows


def resolve_file(job_dir: str, rel: str) -> Optional[Path]:
    """Файл внутри папки результата (без выхода за её пределы), иначе None."""
    base = Path(job_dir).resolve()
    root = out_root().resolve()
    if root not in base.parents:
        return None
    target = (base / rel).resolve()
    return target if base in target.parents and target.is_file() else None


def delete_result(job_dir: str) -> bool:
    base = Path(job_dir).resolve()
    if out_root().resolve() not in base.parents or not (base / "meta.json").is_file():
        return False
    shutil.rmtree(base, ignore_errors=True)
    return True
