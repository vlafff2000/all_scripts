"""Пресеты скважин, общие для всех вкладок и всех программ ПХГ.

Пресет — именованный список скважин. Хранится в файле ``well_presets.json`` той же формы, что в Газовом Атласе
(``atlas/well_sets.py``): ``{"presets": [{"id", "name", "wells"}]}``. Папка — проект Атласа (``<хранилище>/projects/<id>``),
с которым работает программа: тогда пресеты, созданные в «Картах» или «ГДМ», видны в Атласе и наоборот. Нет проекта —
общий каталог пользователя (``~/.pxg``, меняется PXG_HOME).

Фильтр скважин вкладки у каждой вкладки свой (его хранит интерфейс), а пресеты — общие.
Решение за инженером: пресет только подсказка, список всегда правится вручную.

Подключение: ``*well_presets.routes(folder, builtin)`` в списке маршрутов Starlette.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

FILE = "well_presets.json"


def home() -> Path:
    return Path(os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg"))


def norm(well: Any) -> str:
    """«31», 31 и «31.0» — одна скважина (как в Атласе)."""
    text = str(well).strip()
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def _read(folder: Path) -> List[dict]:
    try:
        data = json.loads((folder / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("presets", []) if isinstance(data, dict) else []
    return [p for p in items if isinstance(p, dict) and p.get("id") and isinstance(p.get("wells"), list)]


def _write(folder: Path, presets: List[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE).write_text(json.dumps({"presets": presets}, ensure_ascii=False, indent=1), encoding="utf-8")


def user_presets(folder: Path) -> List[dict]:
    return [{"id": p["id"], "kind": "user", "label": p.get("name", "Без названия"), "wells": list(p["wells"])} for p in _read(folder)]


def add(folder: Path, name: str, wells: Iterable[Any]) -> List[dict]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажите название пресета.")
    listed = [norm(w) for w in wells if str(w).strip()]
    if not listed:
        raise ValueError("В пресете нет скважин. Выберите скважины.")
    presets = _read(folder)
    presets.append({"id": uuid.uuid4().hex, "name": name, "wells": list(dict.fromkeys(listed))})
    _write(folder, presets)
    return user_presets(folder)


def remove(folder: Path, preset_id: str) -> List[dict]:
    _write(folder, [p for p in _read(folder) if p["id"] != preset_id])
    return user_presets(folder)


def routes(folder: Callable[[], Optional[Path]], builtin: Optional[Callable[[], List[dict]]] = None) -> List[Route]:
    """``folder`` — папка с файлом пресетов (``None`` — общий каталог пользователя); ``builtin`` — готовые пресеты программы (группы)."""
    def where() -> Path:
        return folder() or home()

    def listing() -> JSONResponse:
        ready = builtin() if builtin else []
        return JSONResponse({"presets": [*ready, *user_presets(where())], "shared": str(where())})

    async def get(request: Request):
        return listing()

    async def create(request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("wells"), list):
            return JSONResponse({"error": "Ожидается JSON с полями name и wells."}, status_code=400)
        try:
            add(where(), str(body.get("name", "")), body["wells"])
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return listing()

    async def delete(request: Request):
        remove(where(), request.path_params["preset"])
        return listing()

    return [Route("/api/well-presets", get, methods=["GET"]), Route("/api/well-presets", create, methods=["POST"]),
            Route("/api/well-presets/{preset}", delete, methods=["DELETE"])]
