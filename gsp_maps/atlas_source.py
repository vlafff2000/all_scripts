"""Данные «Карт ГСП» из проекта Газового Атласа (его `storage/`): расходы, давления, вода, положение и перфорация.

Атлас хранит проект как снимок таблиц parquet и `manifest.json` (формат `atlas/engine/core/storage.py`). Карты только читают
его, ничего не пишут и ничего не импортируют из Атласа: достаточно общей папки хранилища (в едином запуске её задаёт
`GAS_ATLAS_STORAGE`). Что приходит откуда:

| Нужно Картам              | Таблица Атласа                                    | Заметка |
|---------------------------|---------------------------------------------------|---------|
| расходы и время работы    | `production` (+ `operations.work_hours`)          | группа — как в Атласе, с ручными правками групп; исключённые точки — пропуск |
| периоды работы объекта    | `gas_db` или суммы `production` по суткам         | выводятся из данных: подсказка, не приговор |
| давление по ГСП           | `response.pressure` (пересчёт давлений по скважинам) | кгс/см² → бар |
| давление по объекту       | `object_pressure.pressure`                        | горизонты из настройки Атласа, среднее по датам |
| вода по скважинам         | `water` (`water_rate`, `water_factor_l`, `water_flag`) | пропуск остаётся пропуском |
| X, Y, альтитуда, перфорация | `well_geo`                                      | загрузка — в Атласе («Источники», «Импорт данных») |
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .store import _frame_to_arrays

KGF_TO_BAR = 0.980665          # Атлас хранит давления в кгс/см², Карты считают в барах
MIN_RUN_DAYS = 5               # режим короче этого срока при выводе периодов сливается с предыдущим
KEYS = {"production": ["kind", "well", "date"], "response": ["well", "date", "horizon"], "object_pressure": ["date"]}
SOURCES = [("flow", "Расходы по скважинам"), ("periods", "Периоды работы объекта"), ("press_gsp", "Давление по ГСП"),
           ("press_obj", "Давление по объекту"), ("water", "Вынос воды по скважинам"), ("xy", "Координаты X, Y"),
           ("altitude", "Альтитуды"), ("perf", "Перфорации")]


def storage_root(configured: str = "") -> Optional[Path]:
    """Хранилище Атласа: заданное вручную, иначе GAS_ATLAS_STORAGE (в едином запуске её ставит меню)."""
    text = (configured or os.environ.get("GAS_ATLAS_STORAGE", "")).strip()
    return Path(text) if text else None


def list_projects(root: Optional[Path]) -> List[dict]:
    """Проекты Атласа, новые сверху: id, название, обновлён, число строк по таблицам."""
    out: List[dict] = []
    if root is None or not (root / "projects").is_dir():
        return out
    for path in (root / "projects").glob("*/manifest.json"):
        try:
            m = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(m, dict) and m.get("id"):
            out.append({"id": m["id"], "name": str(m.get("name", "")), "updated": str(m.get("updated", "")),
                        "demo": bool(m.get("demo")), "tables": {k: int(v) for k, v in (m.get("tables") or {}).items()}})
    return sorted(out, key=lambda p: p["updated"], reverse=True)


def default_project(projects: List[dict]) -> str:
    """Проект по умолчанию — подсказка, выбор остаётся за инженером: самый свежий не демонстрационный с расходами."""
    for p in projects:
        if p["tables"].get("production") and not p["demo"]:
            return p["id"]
    return ""


def _text(series: pd.Series):
    codes, uniques = pd.factorize(series.fillna(""))
    categories = pd.Index([str(u) for u in uniques], dtype=object)
    if not categories.is_unique:
        return series.fillna("").astype(str)
    return pd.Categorical.from_codes(codes, categories)


def point_ids(df: pd.DataFrame, module: str) -> pd.Series:
    """Идентификаторы точек, как их считает Атлас (`atlas/engine/core/exclusions.py: identify`), чтобы узнать исключённые."""
    values = pd.DataFrame(index=df.index)
    for field in KEYS[module]:
        values[field] = pd.to_datetime(df[field]).astype("datetime64[ns]") if field == "date" else (
            _text(df[field]) if field in df else "")
    hashed = pd.util.hash_pandas_object(values, index=False)
    return pd.Series([module + ":" + str(h) for h in hashed.tolist()], index=df.index, dtype=object)


class AtlasData:
    """Один проект Атласа, прочитанный целиком: таблицы Карт строятся один раз при открытии."""

    def __init__(self, root: Path, pid: str):
        self.root, self.pid = root, pid
        base = root / "projects" / pid
        try:
            self.manifest = json.loads((base / "manifest.json").read_text("utf-8"))
        except (OSError, ValueError) as e:
            raise FileNotFoundError("Проект Атласа не найден или не читается: %s" % pid) from e
        self.name = str(self.manifest.get("name", pid))
        snapshot = self.manifest.get("snapshot")
        self._dir = base / "snapshots" / snapshot if snapshot else None
        self.tables: Dict[str, int] = {k: int(v) for k, v in (self.manifest.get("tables") or {}).items()}
        self.key = "%s:%s:%s" % (pid, snapshot, self.manifest.get("revision"))
        self.excluded = set((self.manifest.get("settings") or {}).get("excluded_points") or {})
        self.warnings: List[str] = []

    def frame(self, name: str) -> Optional[pd.DataFrame]:
        if self._dir is None or not self.tables.get(name):
            return None
        path = self._dir / (name + ".parquet")
        return pd.read_parquet(path) if path.is_file() else None

    # ---------- расходы ----------
    def groups_override(self) -> Dict[str, str]:
        return {str(w): str(v.get("group")) for w, v in (self.manifest.get("groups") or {}).items()
                if isinstance(v, dict) and str(v.get("group") or "").strip()}

    def flow_arrays(self) -> Dict[str, np.ndarray]:
        """Массивы для `Store.from_raw`: отбор и закачка по скважинам и суткам."""
        prod = self.frame("production")
        if prod is None or prod.empty:
            raise ValueError("В проекте Атласа «%s» нет расходов: загрузите базу расходов в Атласе." % self.name)
        prod = prod.copy()
        prod["q"] = pd.to_numeric(prod["q"], errors="coerce")
        if self.excluded:       # исключённая в Атласе точка — пропуск, а не ноль
            prod.loc[point_ids(prod, "production").isin(self.excluded), "q"] = np.nan
        override = self.groups_override()
        group = prod["group"].astype(str).str.strip() if "group" in prod else pd.Series("", index=prod.index)
        if override:
            group = prod["well"].astype(str).map(override).fillna(group)
        ops = self.frame("operations")
        hours = None
        if ops is not None and "work_hours" in ops and ops["work_hours"].notna().any():
            part = ops[["well", "date", "work_hours"]].dropna(subset=["work_hours"]).copy()
            part["date"] = pd.to_datetime(part["date"]).dt.normalize()
            hours = part.drop_duplicates(["well", "date"], keep="last").set_index(["well", "date"])["work_hours"]
        parts = []
        for atlas_kind, kind, name in (("withdrawal", 0, "Отбор"), ("injection", 1, "Закачка")):
            sel = prod[prod["kind"].eq(atlas_kind)]
            if sel.empty:
                continue
            frame = pd.DataFrame({"Скважина": sel["well"].to_numpy(), "Дата": pd.to_datetime(sel["date"]).dt.normalize().to_numpy(),
                                  "Суточный расход газа": sel["q"].to_numpy(), "Источник": group.loc[sel.index].to_numpy()})
            if kind == 0 and "season" in sel:
                frame["Сезон"] = sel["season"].to_numpy()
            if kind == 1 and "year" in sel:
                frame["Год"] = sel["year"].to_numpy()
            if hours is not None:
                keys = pd.MultiIndex.from_arrays([sel["well"].to_numpy(), frame["Дата"].to_numpy()])
                frame["Время работы"] = hours.reindex(keys).to_numpy()
            parts.append(_frame_to_arrays(frame[frame["Источник"].astype(str).str.strip().ne("")], kind))
        if not parts:
            raise ValueError("В расходах проекта «%s» нет ни отбора, ни закачки." % self.name)
        return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}

    # ---------- периоды ----------
    def periods(self) -> Tuple[List[Tuple[int, str]], List[str]]:
        """Режимы объекта по суткам (отбор, закачка, нейтральный) → даты смены режима, как в файле периодов.
        Это подсказка: суммы по суткам берутся из «БД по учету газа», иначе из расходов по скважинам."""
        gas = self.frame("gas_db")
        if gas is not None and not gas.empty:
            daily = gas.assign(date=pd.to_datetime(gas["date"]).dt.normalize()).groupby(["date", "kind"])["gas"].sum().unstack("kind")
            source = "БД по учету газа"
        else:
            prod = self.frame("production")
            if prod is None or prod.empty:
                return [], []
            daily = prod.assign(date=pd.to_datetime(prod["date"]).dt.normalize()).groupby(["date", "kind"])["q"].sum().unstack("kind")
            source = "расходы по скважинам"
        if daily.empty:
            return [], []
        days = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
        daily = daily.reindex(days).fillna(0.0)
        w = daily["withdrawal"] if "withdrawal" in daily else pd.Series(0.0, index=days)
        i = daily["injection"] if "injection" in daily else pd.Series(0.0, index=days)
        mode = np.where((w > 0) & (w >= i), "prod", np.where(i > 0, "inj", "none"))
        runs: List[List] = []        # [тип, начало, длина]
        for day, m in zip(days, mode):
            if runs and runs[-1][0] == m:
                runs[-1][2] += 1
            else:
                runs.append([m, day, 1])
        merged: List[List] = []
        for run in runs:
            if merged and (run[2] < MIN_RUN_DAYS or merged[-1][0] == run[0]):
                merged[-1][2] += run[2]
            else:
                merged.append(run)
        epoch = np.datetime64("1970-01-01", "D")
        out = [(int((np.datetime64(r[1].date(), "D") - epoch).astype("int64")), r[0]) for r in merged]
        return out, ["Периоды работы выведены из данных Атласа (%s): проверьте их, это подсказка." % source]

    # ---------- положение и перфорация ----------
    def geo(self) -> Tuple[Dict[int, Tuple[float, float]], Dict[int, float], Dict[int, Tuple[float, float]]]:
        """(xy, альтитуды, перфорация (верх, низ)) по номерам скважин."""
        df = self.frame("well_geo")
        xy: Dict[int, Tuple[float, float]] = {}
        alt: Dict[int, float] = {}
        perf: Dict[int, Tuple[float, float]] = {}
        if df is None:
            return xy, alt, perf
        for r in df.itertuples(index=False):
            try:
                well = int(float(str(r.well).strip()))
            except ValueError:
                continue
            if r.x == r.x and r.y == r.y:
                xy[well] = (float(r.x), float(r.y))
            if r.altitude == r.altitude:
                alt[well] = float(r.altitude)
            if r.perf_top == r.perf_top and r.perf_bottom == r.perf_bottom:
                perf[well] = (float(r.perf_top), float(r.perf_bottom))
        return xy, alt, perf

    # ---------- вода ----------
    def water(self) -> Tuple[pd.DataFrame, List[str]]:
        cols = ["Скважина", "Месяц", "Год", "Дата_замера", "Метка_замера", "Водный_фактор", "Расход_воды_лч", "Примечание"]
        df = self.frame("water")
        if df is None or df.empty:
            return pd.DataFrame(columns=cols), []
        warn: List[str] = []
        well = pd.to_numeric(df["well"], errors="coerce")
        date = pd.to_datetime(df["date"], errors="coerce")
        ok = well.notna() & date.notna()
        df, well, date = df[ok], well[ok].astype(int), date[ok]
        rate = pd.to_numeric(df["water_rate"], errors="coerce") if "water_rate" in df else pd.Series(np.nan, index=df.index)
        factor = pd.to_numeric(df["water_factor_l"], errors="coerce") if "water_factor_l" in df else pd.Series(np.nan, index=df.index)
        flag = df["water_flag"].astype(str) if "water_flag" in df else pd.Series("Неизвестно", index=df.index)
        note = df["comment"].fillna("").astype(str).str.strip() if "comment" in df else pd.Series("", index=df.index)
        note = note.where(~note.isin(["", "Ок", "nan"]), "")
        unknown = (flag.eq("Неизвестно") & rate.isna()) | (rate.isna() & note.ne(""))
        if rate.notna().any() and not factor.notna().any():
            warn.append("В воде проекта Атласа нет водного фактора: загрузите «БД замеров воды» в Атлас заново.")
        out = pd.DataFrame({"Скважина": well.to_numpy(), "Месяц": date.dt.month.to_numpy(), "Год": date.dt.year.to_numpy(),
                            "Дата_замера": date.dt.strftime("%Y-%m-01").to_numpy(),
                            "Метка_замера": ["%02d.%d" % (m, y) for m, y in zip(date.dt.month, date.dt.year)],
                            "Водный_фактор": factor.mask(unknown).to_numpy(),
                            "Расход_воды_лч": (rate * 1000 / 24).mask(unknown).to_numpy(),
                            "Примечание": note.where(note.ne(""), "Ок").to_numpy()}, columns=cols)
        out = out.assign(_d=date.to_numpy()).sort_values("_d", kind="stable").drop(columns="_d")
        return out.drop_duplicates(["Скважина", "Метка_замера"], keep="last").reset_index(drop=True), warn

    # ---------- давление ----------
    def pressure(self, is_gsp: bool) -> Tuple[pd.DataFrame, List[str]]:
        cols = ["Дата", "Давление_бар", "Скважина"]
        if is_gsp:
            df = self.frame("response")
            if df is None or "pressure" not in df:
                return pd.DataFrame(columns=cols), []
            df = df.copy()
            df["pressure"] = pd.to_numeric(df["pressure"], errors="coerce")
            if self.excluded:
                df.loc[point_ids(df, "response").add(":pressure").isin(self.excluded), "pressure"] = np.nan
            df = df[df["pressure"].notna()]
            well = pd.to_numeric(df["well"], errors="coerce").fillna(0).astype(int)
            out = pd.DataFrame({"Дата": pd.to_datetime(df["date"]).dt.normalize(),
                                "Давление_бар": (df["pressure"] * KGF_TO_BAR).round(2), "Скважина": well}, columns=cols)
            return out.dropna(subset=["Дата"]).sort_values("Дата", kind="stable").reset_index(drop=True), []
        df = self.frame("object_pressure")
        if df is None or "pressure" not in df:
            return pd.DataFrame(columns=cols), []
        df = df.copy()
        df["pressure"] = pd.to_numeric(df["pressure"], errors="coerce")
        if self.excluded:
            df.loc[point_ids(df, "object_pressure").isin(self.excluded), "pressure"] = np.nan
        horizons = (self.manifest.get("settings") or {}).get("object_pressure_horizons") or []
        if horizons and "horizon" in df:
            df = df[df["horizon"].isin(horizons)]
        df = df[df["pressure"].notna()]
        df = df.assign(date=pd.to_datetime(df["date"]).dt.normalize()).groupby("date", as_index=False)["pressure"].mean()
        out = pd.DataFrame({"Дата": df["date"], "Давление_бар": (df["pressure"] * KGF_TO_BAR).round(2), "Скважина": 0}, columns=cols)
        return out.sort_values("Дата", kind="stable").reset_index(drop=True), []
