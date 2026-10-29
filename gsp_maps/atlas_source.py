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
import pyarrow as pa
import pyarrow.parquet as pq

from . import atlas_seasons
from .store import KIND_BY_NAME, _frame_to_arrays

KGF_TO_BAR = 0.980665          # Атлас хранит давления в кгс/см², Карты считают в барах
MIN_RUN_DAYS = 5               # режим короче этого срока при выводе периодов сливается с предыдущим
# ключи точек, как в `atlas/engine/core/exclusions.py: KEYS` (текстовые поля; дата; числовые ключи не нужны этим таблицам)
KEYS = {"production": ["kind", "well", "date"], "response": ["well", "date", "horizon"], "object_pressure": ["date"],
        "operations": ["well", "date", "kind"], "water": ["well", "date"], "bottom": ["well", "date"],
        "annulus": ["well", "date"], "gis_packs": ["well", "date", "pack"], "gis_intervals": ["well", "date", "pack", "from_m"], "ggh": ["well", "date"], "elpro": ["kind", "group", "well", "date", "np"]}
# таблицы Атласа, которые можно положить на карту по скважинам (параметр); без номера скважины — нет
PARAM_TABLES = {"production": "Расходы по скважинам", "response": "Отклик: давления и уровни", "operations": "Режимы работы",
                "water": "Вода по скважинам", "bottom": "Забой", "construction": "Конструкция скважины", "gdi": "ГДИ",
                "pressure_match": "Адаптация давлений", "ggh": "ГГХ", "elpro": "Эльпро", "annulus": "Затрубное давление",
                "well_geo": "Положение и перфорация"}
PARAM_SKIP = {"well", "year", "np", "season", "x", "y"}   # номера и координаты — не параметры
PARAM_LABELS = {"q": "Расход", "pressure": "Давление, кгс/см²", "level": "Уровень", "work_hours": "Время работы, ч",
                "water_rate": "Расход воды, т/сут", "water_factor_l": "Водный фактор", "bottom_m": "Забой, м", "top_m": "Верх, м",
                "altitude": "Альтитуда, м", "perf_top": "Перфорация, верх, м", "perf_bottom": "Перфорация, низ, м", "dp2": "Депрессия",
                "fact": "Факт", "model": "Модель", "hc": "Углеводороды", "gas": "Газ", "p": "Давление", "diameter_mm": "Диаметр, мм"}
PARAM_AGG = {"mean": "среднее", "sum": "сумма", "last": "последнее", "count": "число записей"}
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
        self._frames: Dict[str, Optional[pd.DataFrame]] = {}   # таблицы для параметров, читаются один раз

    def frame(self, name: str) -> Optional[pd.DataFrame]:
        if self._dir is None or not self.tables.get(name):
            return None
        path = self._dir / (name + ".parquet")
        return pd.read_parquet(path) if path.is_file() else None

    # ---------- расходы ----------
    def groups_override(self) -> Dict[str, str]:
        return {str(w): str(v.get("group")) for w, v in (self.manifest.get("groups") or {}).items()
                if isinstance(v, dict) and str(v.get("group") or "").strip()}

    @property
    def settings(self) -> dict:
        return self.manifest.get("settings") or {}

    def period_labels(self, prod: pd.DataFrame) -> pd.Series:
        """Сезон каждой строки расходов, как его считает Атлас (настройки месяцев, автоопределение, расписание периодов)."""
        base = pd.DataFrame({"date": pd.to_datetime(prod["date"]).dt.normalize(), "kind": prod["kind"], "q": prod["q"]}, index=prod.index)
        for col in ("season", "year"):
            if col in prod:
                base[col] = prod[col]
        return atlas_seasons.period_labels(base, self.settings)

    def flow_arrays(self, kind_overrides: Optional[Dict[str, str]] = None) -> Dict[str, np.ndarray]:
        """Массивы для `Store.from_raw`: отбор и закачка по скважинам и суткам.
        `kind_overrides` — ручная правка типа сезона инженером: «Отбор|2025-2026» → «Закачка» (решение за инженером, Атлас — подсказка)."""
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
        period = self.period_labels(prod)
        parts = []
        for atlas_kind, kind, name in (("withdrawal", 0, "Отбор"), ("injection", 1, "Закачка")):
            sel = prod[prod["kind"].eq(atlas_kind)]
            if not self.settings.get("show_neutral_periods"):      # как в Атласе: нейтральные периоды и «вне сезона» — не сезоны
                neutral = period.loc[sel.index].map(atlas_seasons.is_neutral).astype(bool)
                if neutral.any():
                    self.warnings.append("%s: строк вне сезонов Атласа (нейтральные периоды) — %d, в сезоны Карт они не входят."
                                         % (name, int(neutral.sum())))
                sel = sel[~neutral.to_numpy()]
            if sel.empty:
                continue
            frame = pd.DataFrame({"Скважина": sel["well"].to_numpy(), "Дата": pd.to_datetime(sel["date"]).dt.normalize().to_numpy(),
                                  "Суточный расход газа": sel["q"].to_numpy(), "Источник": group.loc[sel.index].to_numpy()})
            frame["Период"] = period.loc[sel.index].to_numpy()      # сезон строки — по правилу проекта Атласа
            if hours is not None:
                keys = pd.MultiIndex.from_arrays([sel["well"].to_numpy(), frame["Дата"].to_numpy()])
                frame["Время работы"] = hours.reindex(keys).to_numpy()
            parts.append(_frame_to_arrays(frame[frame["Источник"].astype(str).str.strip().ne("")], kind))
        if not parts:
            raise ValueError("В расходах проекта «%s» нет ни отбора, ни закачки." % self.name)
        raw = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        for key, target in (kind_overrides or {}).items():
            was, _, label = key.partition("|")
            if was in KIND_BY_NAME and target in KIND_BY_NAME and was != target:
                raw["kind"][(raw["kind"] == KIND_BY_NAME[was]) & (raw["season"] == label)] = KIND_BY_NAME[target]
        return raw

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

    # ---------- любой параметр по скважинам ----------
    def parameters(self) -> List[dict]:
        """Числовые колонки таблиц Атласа с номером скважины — всё, что можно положить на карту. Читается только схема файлов."""
        out: List[dict] = []
        if self._dir is None:
            return out
        for table, title in PARAM_TABLES.items():
            path = self._dir / (table + ".parquet")
            if not self.tables.get(table) or not path.is_file():
                continue
            for field in pq.read_schema(path):
                if field.name in PARAM_SKIP or not (pa.types.is_integer(field.type) or pa.types.is_floating(field.type)):
                    continue
                out.append({"table": table, "column": field.name, "title": title, "label": PARAM_LABELS.get(field.name, field.name),
                            "rows": int(self.tables[table]), "perWell": table != "well_geo"})
        return out

    def parameter_values(self, table: str, column: str, agg: str = "mean", start: str = "", end: str = "") -> Tuple[Dict[int, float], List[str]]:
        """Значение параметра по каждой скважине за период: среднее, сумма, последнее или число записей.
        Исключённые в Атласе точки — пропуск. Пустой результат — не ошибка, а пустой словарь с пояснением."""
        if table not in PARAM_TABLES or agg not in PARAM_AGG:
            raise ValueError("Нет такого параметра: %s / %s / %s" % (table, column, agg))
        warn: List[str] = []
        df = self._param_frame(table)
        if df is None or column not in df or "well" not in df:
            return {}, ["В проекте Атласа нет параметра «%s» (%s)." % (column, PARAM_TABLES[table])]
        well = pd.to_numeric(df["well"], errors="coerce")
        val = pd.to_numeric(df[column], errors="coerce")
        keep = well.notna() & val.notna()
        if "date" in df:
            date = pd.to_datetime(df["date"], errors="coerce")
            keep &= date.notna()
            if start:
                keep &= date >= pd.Timestamp(start)
            if end:
                keep &= date <= pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        if self.excluded:
            if table in KEYS:
                ids = point_ids(df, table) + (":" + column if table == "response" else "")
                keep &= ~ids.isin(self.excluded)
            else:
                warn.append("Исключения для таблицы «%s» на карте не учтены: проверьте точки в Атласе." % PARAM_TABLES[table])
        part = pd.DataFrame({"well": well[keep].astype(int).to_numpy(), "v": val[keep].to_numpy()})
        if "date" in df:
            part["date"] = date[keep].to_numpy()
            part = part.sort_values("date", kind="stable")
        grouped = part.groupby("well")["v"]
        series = {"mean": grouped.mean, "sum": grouped.sum, "last": grouped.last, "count": grouped.count}[agg]()
        return {int(w): float(v) for w, v in series.items() if np.isfinite(v)}, warn

    def _param_frame(self, table: str) -> Optional[pd.DataFrame]:
        if table not in self._frames:
            self._frames[table] = self.frame(table)
        return self._frames[table]
