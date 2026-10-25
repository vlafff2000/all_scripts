"""История и эталон из проекта Газового Атласа (его `storage/`): база расходов и «БД по учету газа» подтягиваются сами.

Читаем так же, как «Карты» (`gsp_maps.atlas_source`): только чтение таблиц `production` и `gas_db` снимка проекта. Расходы Атласа —
тыс. м³/сут, ГДМ считает в м³/сут, поэтому ×1000. Точки, исключённые в Атласе, пропускаются (последнее слово за инженером там).
Какое хранилище и какой проект — подсказка: хранилище из `GAS_ATLAS_STORAGE` или заданное вручную, проект — самый свежий не
демонстрационный с расходами; выбор можно поменять.
Python 3.8+.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import pandas as pd

from . import history

KIND = {"withdrawal": history.PROD, "injection": history.INJ}


def projects(storage: str = "") -> Tuple[List[dict], Optional[str]]:
    """(проекты Атласа с расходами, путь хранилища); нет хранилища — ([], None)."""
    from gsp_maps import atlas_source
    root = atlas_source.storage_root(storage)
    if root is None:
        return [], None
    return [p for p in atlas_source.list_projects(root) if p["tables"].get("production")], str(root)


def well_groups(data) -> dict:
    """Разбивка скважин на группы из Атласа: ручные правки групп проекта главнее, затем столбец группы в расходах,
    затем в других таблицах со скважиной и группой (ЭЛПРО). Пусто — группы не заданы."""
    out: dict = {}
    for name in ("elpro", "production"):               # позднее перекрывает раннее: расходы главнее ЭЛПРО
        df = data.frame(name)
        if df is None or df.empty or "group" not in df or "well" not in df:
            continue
        part = df[["well", "group"]].dropna()
        part = part.assign(well=part["well"].astype(str).str.strip(), group=part["group"].astype(str).str.strip())
        part = part[part["group"].ne("") & part["group"].ne("nan")]
        out.update(dict(zip(part["well"], part["group"])))
    out.update({str(w).strip(): g for w, g in data.groups_override().items()})
    return out


def load(storage: str = "", project_id: str = ""):
    """(история, эталон, подпись, проекты, группы скважин) из проекта Атласа или None, если хранилища/проекта с расходами нет.
    История — таблица `history.COLUMNS` (м³/сут), эталон — «Дата», «Объем» (м³/сут) или пустая таблица."""
    from gsp_maps import atlas_source
    found, root = projects(storage)
    if not found:
        return None
    pid = project_id if any(p["id"] == project_id for p in found) else atlas_source.default_project(found) or found[0]["id"]
    data = atlas_source.AtlasData(atlas_source.storage_root(storage), pid)
    prod = data.frame("production")
    if prod is None or prod.empty:
        return None
    prod = prod[prod["kind"].isin(KIND)].copy()
    prod["q"] = pd.to_numeric(prod["q"], errors="coerce")
    if data.excluded:
        prod = prod[~atlas_source.point_ids(prod, "production").isin(data.excluded)]
    prod = prod[prod["q"].notna()]
    hist = pd.DataFrame({"well": prod["well"].astype(str).str.strip().to_numpy(),
                         "date": pd.to_datetime(prod["date"]).dt.normalize().to_numpy(),
                         "rate": (prod["q"] * 1000.0).to_numpy(), "hours": float("nan"),
                         "kind": prod["kind"].map(KIND).to_numpy()})[history.COLUMNS].reset_index(drop=True)
    gas = data.frame("gas_db")
    if gas is not None and not gas.empty:
        g = gas.assign(d=pd.to_datetime(gas["date"]).dt.normalize(), gas=pd.to_numeric(gas["gas"], errors="coerce"))
        g = g.dropna(subset=["gas"]).groupby("d")["gas"].sum().reset_index()
        daily = pd.DataFrame({"Дата": g["d"], "Объем": g["gas"] * 1000.0})
    else:
        daily = pd.DataFrame(columns=["Дата", "Объем"])
    return hist, daily, "проект Атласа «%s»" % data.name, found, well_groups(data)


def base_model_info(storage: str = "", project_id: str = "") -> Tuple[str, str]:
    """(базовая модель, папка с её .data) проекта Атласа (раздел «Импорт»); пустые строки — не заданы.
    Проект выбирается как для расходов (самый свежий не демонстрационный с расходами, если не задан)."""
    from gsp_maps import atlas_source
    found, root = projects(storage)
    if not found:
        return "", ""
    pid = project_id if any(p["id"] == project_id for p in found) else atlas_source.default_project(found) or found[0]["id"]
    cfg = atlas_source.AtlasData(atlas_source.storage_root(storage), pid).manifest.get("settings") or {}
    return tuple(str(cfg.get(k) or "").strip().strip('"') for k in ("base_model", "base_model_data"))  # type: ignore[return-value]


def base_model(storage: str = "", project_id: str = "") -> str:
    return base_model_info(storage, project_id)[0]
