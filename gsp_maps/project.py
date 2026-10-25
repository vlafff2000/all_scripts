"""Состояние приложения: пути к файлам, загруженные таблицы с кэшем, расчёты для карты и выгрузка в Excel."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pxg_core import runlog, workspace

from . import atlas_source, gis_source, inputs, observers, wellmap
from .store import KIND_BY_NAME, KIND_NAMES, OTBOR, ZAKACHKA, Store, season_of

PATH_KEYS = ["map", "atlas_storage", "atlas_project"]    # карта-сетка Excel — необязательный запасной источник положений
LABELS = {"map": "Карта-сетка (Excel)", "atlas_storage": "Хранилище Атласа", "atlas_project": "Проект Атласа"}


def config_file() -> Path:
    return Path(os.environ.get("GSP_MAPS_HOME") or Path.home() / ".gsp_maps") / "config.json"


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


class Project:
    def __init__(self) -> None:
        self.paths: Dict[str, str] = {k: "" for k in PATH_KEYS}
        self.results_dir = ""
        self.observer_marks: Dict[str, Dict[str, str]] = {}  # проект Атласа → {скважина: obs|prod}, ручной выбор инженера
        self.models: List[str] = []  # модели tNavigator, отмеченные для карты (пути из общего каталога)
        self.store: Optional[Store] = None
        self.atlas: Optional[atlas_source.AtlasData] = None
        self._tables: Dict[str, object] = {}
        self.state = "idle"  # idle | loading | ready | error
        self.log: List[str] = []
        self._cache: Dict[Tuple, object] = {}
        self._lock = threading.Lock()
        self._load()

    # ---------- настройки ----------
    def _load(self) -> None:
        try:
            data = json.loads(config_file().read_text(encoding="utf-8"))
            self.paths.update({k: str(v) for k, v in data.get("paths", {}).items() if k in self.paths})
            self.results_dir = str(data.get("results_dir", ""))
            self.models = [str(x) for x in data.get("models", [])]
            self.observer_marks = {str(p): {str(w): str(k) for w, k in m.items()} for p, m in (data.get("observers") or {}).items()}
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        try:
            config_file().parent.mkdir(parents=True, exist_ok=True)
            config_file().write_text(json.dumps({"paths": self.paths, "results_dir": self.results_dir, "models": self.models,
                                                  "observers": self.observer_marks}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
        except OSError:
            pass

    def mark_observer(self, well: int, kind: str) -> None:
        """Ручное решение инженера: obs — наблюдательная, prod — эксплуатационная, auto — убрать пометку."""
        marks = self.observer_marks.setdefault(self.project_id(), {})
        if kind == "auto":
            marks.pop(str(well), None)
        elif kind in observers.MANUAL:
            marks[str(well)] = kind
        else:
            raise ValueError("Вид скважины: obs, prod или auto.")
        self._save()

    def observers_payload(self) -> dict:
        assert self.atlas is not None and self.store is not None
        return observers.observers(self.atlas, np.unique(self.store.well).tolist(), self.xy()[0], self.observer_marks.get(self.project_id(), {}))

    def set_models(self, ids: List[str]) -> None:
        self.models = list(ids)
        self._save()

    def set_paths(self, paths: Dict[str, str], results_dir: Optional[str] = None) -> None:
        with self._lock:
            old = (self.paths["atlas_storage"], self.paths["atlas_project"])
            for k in PATH_KEYS:
                if k in paths:
                    self.paths[k] = str(paths[k] or "").strip().strip('"')
            if results_dir is not None:
                self.results_dir = results_dir.strip()
            if (self.paths["atlas_storage"], self.paths["atlas_project"]) != old:
                self.store, self.atlas, self._tables, self.state = None, None, {}, "idle"
            self._save()

    # ---------- проект Атласа ----------
    def storage(self) -> Optional[Path]:
        return atlas_source.storage_root(self.paths["atlas_storage"])

    def atlas_projects(self) -> List[dict]:
        return atlas_source.list_projects(self.storage())

    def project_id(self) -> str:
        """Выбранный проект Атласа; если выбора нет — самый свежий не демонстрационный с расходами (подсказка)."""
        chosen = self.paths["atlas_project"]
        return chosen or atlas_source.default_project(self.atlas_projects())

    def out_dir(self) -> Path:
        if self.results_dir:
            base = Path(self.results_dir)
        elif workspace.load():
            base = Path(workspace.load()) / "Результаты карт ГСП"
        else:
            base = Path.home() / "Результаты карт ГСП"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # ---------- загрузка данных ----------
    def start_loading(self) -> None:
        """Читает проект Атласа. Если проект в Атласе изменился (новая ревизия), данные перечитываются."""
        with self._lock:
            if self.state == "loading":
                return
            pid = self.project_id()
            root = self.storage()
            if not pid or root is None:
                self.state, self.log = "idle", []
                return
            known = {p["id"]: p for p in self.atlas_projects()}
            if pid not in known:
                # сохранённый проект исчез из хранилища (перенос, другая папка, пересоздание): выбор остаётся за инженером
                self.state = "idle"
                self.log = ["Проект Атласа %s не найден в хранилище %s. Выберите проект из списка (в нём %d)."
                            % (pid, root, len(known))]
                return
            if self.atlas is not None and self.atlas.pid == pid:
                try:
                    fresh = atlas_source.AtlasData(root, pid).key == self.atlas.key
                except FileNotFoundError:
                    fresh = False
                if fresh and self.store is not None:
                    self.state = "ready"
                    return
            self.state, self.log = "loading", []
        threading.Thread(target=self._load_db, args=(root, pid), daemon=True).start()

    def _load_db(self, root: Path, pid: str) -> None:
        try:
            t0 = time.time()
            atlas = atlas_source.AtlasData(root, pid)
            self.log.append("Читаю проект Атласа «%s»…" % atlas.name)
            store = Store.from_raw(atlas.flow_arrays())
            store.path = atlas.key
            tables = {}
            for key, read in (("periods", atlas.periods), ("water", atlas.water), ("press_gsp", lambda: atlas.pressure(True)),
                              ("press_obj", lambda: atlas.pressure(False)), ("geo", atlas.geo)):
                try:    # сбой одной таблицы не должен лишать данных остальные: причина — в журнале окна
                    tables[key] = read()
                except Exception as e:
                    self.log.append("Таблица «%s» не прочитана: %s: %s" % (key, type(e).__name__, e))
            with self._lock:
                self._cache.clear()
                self.atlas, self.store, self._tables = atlas, store, tables
            threading.Thread(target=self._warm_map, daemon=True).start()
            self.log.append("Готово: ГСП — %d, строк — %d (%.1f с)" % (len(store.gsp_names), len(store.well), time.time() - t0))
            self.state = "ready"
        except Exception as e:  # показываем человеку, а не роняем сервер
            self.log.append("Ошибка: %s: %s" % (type(e).__name__, e))
            runlog.action("Карты: проект Атласа не открылся", error="%s: %s" % (type(e).__name__, e), project=pid)
            self.state = "error"

    def _warm_map(self) -> None:
        """Книга карты читается в фоне сразу после загрузки проекта, чтобы первый выбор групп не ждал её."""
        p = self.paths["map"]
        if p and os.path.isfile(p):
            try:
                wellmap.read_grids(p)
            except Exception:
                pass  # ошибку покажет обычный запрос группы

    # ---------- кэш по файлам ----------
    def _memo(self, key: Tuple, mt: float, make: Callable[[], object]):
        hit = self._cache.get(key)
        if hit is not None and hit[0] == mt:  # type: ignore[index]
            return hit[1]  # type: ignore[index]
        val = make()
        self._cache[key] = (mt, val)
        return val

    def periods(self):
        return self._tables.get("periods", ([], []))

    def depths(self):
        geo = self._tables.get("geo")
        return (geo[2], geo[1]) if geo else ({}, {})

    def water(self):
        return self._tables.get("water", (pd.DataFrame(columns=["Скважина", "Месяц", "Год", "Дата_замера", "Метка_замера",
                                                                "Водный_фактор", "Расход_воды_лч", "Примечание"]), []))

    def pressure(self, which: str):
        return self._tables.get("press_" + which, (pd.DataFrame(columns=["Дата", "Давление_бар", "Скважина"]), []))

    def gsp_pressure(self, which: str, gsp: str):
        """Давление для ГСП. Замеры ГСП относятся к группе по номеру скважины; несколько замеров
        за день усредняются. Если номера в данных не совпадают ни с одной скважиной базы, ряд общий."""
        df, warn = self.pressure(which)
        if which != "gsp" or not len(df) or self.store is None:
            return df, warn
        known = set(np.unique(self.store.well).tolist())
        if not known.intersection(df["Скважина"]):
            return df, warn
        df = df[df["Скважина"].isin(self.store.wells(gsp))]
        if len(df):
            df = df.groupby("Дата", as_index=False)["Давление_бар"].mean().round({"Давление_бар": 2})
        return df, warn

    def grid(self, gsp: str):
        p = self.paths["map"]
        return self._memo(("grid", p, gsp), _mtime(p), lambda: wellmap.read_grid(p, gsp))

    def xy(self):
        geo = self._tables.get("geo")
        return (geo[0], []) if geo else ({}, [])

    # ---------- проверка файлов ----------
    def gsp_meta(self) -> Dict[str, dict]:
        """Есть ли у ГСП положения скважин (лист карты или XY), чтобы по умолчанию открывать ГСП с картой."""
        if self.store is None:
            return {}
        sheets: List[str] = []
        if self.paths["map"] and os.path.isfile(self.paths["map"]):
            try:
                sheets = [x.lower() for x in wellmap.list_sheets(self.paths["map"])]
            except Exception:
                sheets = []
        xy = self.xy()[0]
        out = {}
        for g in self.store.gsp_names:
            grid = any(g.lower() in sh for sh in sheets)
            has_xy = bool(xy) and any(w in xy for w in self.store.wells(g))
            out[g] = {"grid": grid, "xy": has_xy}
        return out

    def _why_closed(self) -> str:
        """Почему проект Атласа не открыт: последняя строка журнала загрузки (ошибка), иначе общая фраза."""
        if self.state == "error" and self.log:
            return self.log[-1]
        if self.state == "loading":
            return "идёт чтение проекта Атласа…"
        return self.log[0] if self.log else "проект Атласа не открыт: нажмите «Обновить из Атласа»"

    def check(self) -> List[dict]:
        """Чеклист источников: что из нужного есть в проекте Атласа. Недостающее загружается в Атласе, не здесь."""
        out = []
        a, t = self.atlas, self._tables
        geo = t.get("geo")
        counts = {
            "flow": (len(self.store.well) if self.store else 0, "строк: %d, ГСП: %d" % (len(self.store.well), len(self.store.gsp_names)) if self.store else ""),
            "periods": (len(t["periods"][0]) if "periods" in t else 0, ""),
            "press_gsp": (len(t["press_gsp"][0]) if "press_gsp" in t else 0, ""),
            "press_obj": (len(t["press_obj"][0]) if "press_obj" in t else 0, ""),
            "water": (len(t["water"][0]) if "water" in t else 0, ""),
            "xy": (len(geo[0]) if geo else 0, ""), "altitude": (len(geo[1]) if geo else 0, ""), "perf": (len(geo[2]) if geo else 0, ""),
        }
        for key, label in atlas_source.SOURCES:
            n, info = counts[key]
            if a is None:
                out.append({"id": key, "label": label, "path": "", "ok": False, "info": self._why_closed()})
            elif n:
                out.append({"id": key, "label": label, "path": "", "ok": True, "info": info or ("записей: %d" % n)})
            else:
                out.append({"id": key, "label": label, "path": "", "ok": False, "info": "в проекте Атласа нет"})
        return out

    # ---------- расчёты для интерфейса ----------
    def season_pressure(self, which: str, gsp: str = "") -> Dict[Tuple[int, str], float]:
        """Среднее давление за сезон: по месяцу замера (как add_directions_and_pressure)."""
        return self._memo(("season_pressure", which, gsp), 0.0, lambda: self._season_pressure(which, gsp))

    def _season_pressure(self, which: str, gsp: str) -> Dict[Tuple[int, str], float]:
        df, _ = self.gsp_pressure(which, gsp) if gsp else self.pressure(which)
        if not len(df):
            return {}
        ts = pd.DatetimeIndex(df["Дата"])
        keys = [season_of(int(m), int(y)) for m, y in zip(ts.month, ts.year)]
        ser = pd.Series(df["Давление_бар"].to_numpy(), index=pd.MultiIndex.from_tuples(
            [(KIND_BY_NAME[k], s) for s, k in keys]))
        return {k: float(v) for k, v in ser.groupby(level=[0, 1]).mean().items()}

    def season_frame(self, gsp: str, kind: int, season: str, layout_dirs: Dict[int, str]) -> pd.DataFrame:
        """Итоги сезона + направление, давление и (для отбора и закачки) водные замеры по меткам."""
        assert self.store is not None
        df = self.store.aggregate(gsp, kind, season).copy()
        if not len(df):
            return df
        if layout_dirs:
            df["Направление"] = df["Скважина"].map(layout_dirs)
        for which, col in (("gsp", "Сред_давл_ГСП_бар"), ("obj", "Сред_давл_Объект_бар")):
            v = self.season_pressure(which, gsp).get((kind, season))
            if v is not None:
                df[col] = v
        w = self.water()[0]
        if len(w):
            wk = self._memo(("water_seasons",), 0.0, lambda: [season_of(int(m), int(y)) for m, y in zip(w["Месяц"], w["Год"])])
            sel = w[[k == (season, KIND_NAMES[kind]) for k in wk]]
            for mark in sorted(sel["Метка_замера"].unique()):
                part = sel[sel["Метка_замера"] == mark].drop_duplicates("Скважина").set_index("Скважина")
                df["Водный_фактор_" + mark] = df["Скважина"].map(part["Водный_фактор"])
                df["Расход_воды_%s_лч" % mark] = df["Скважина"].map(part["Расход_воды_лч"])
        return df

    def layout_for(self, gsp: str, mode: str) -> dict:
        assert self.store is not None
        wells = self.store.wells(gsp)
        cells, dims, notes = {}, (0, 0), []
        missing_sheet = ""
        if self.paths["map"] and os.path.isfile(self.paths["map"]) and mode in ("auto", "grid", "xy"):
            try:
                cells, dims, _ = self.grid(gsp)
            except KeyError as e:
                missing_sheet = str(e.args[0])
            except Exception as e:
                notes.append("Карта-сетка не прочитана: %s" % e)
        xy: Dict[int, Tuple[float, float]] = self.xy()[0] if mode in ("auto", "xy") else {}
        # у группы нет листа карты, но скважины есть в XY — это не замечание, положения известны
        if missing_sheet and not any(w in xy for w in wells):
            notes.append(missing_sheet)
        res = wellmap.layout(wells, cells, dims, xy, mode)
        res["notes"] = notes + res["notes"]
        res["has_grid"], res["has_xy"] = bool(cells), any(w in xy for w in wells)
        return res

    def gsp_payload(self, gsp: str, mode: str = "auto") -> dict:
        """Данные карты группы; готовый ответ запоминается до перезагрузки проекта или смены файла карты."""
        mp = self.paths["map"]
        return self._memo(("gsp_payload", gsp, mode, mp), _mtime(mp) if mp else 0.0, lambda: self._gsp_payload(gsp, mode))

    def _gsp_payload(self, gsp: str, mode: str) -> dict:
        st = self.store
        assert st is not None
        lay = self.layout_for(gsp, mode)
        depths, alt = self.depths()
        wells = st.wells(gsp)
        seasons = {}
        for kind in (OTBOR, ZAKACHKA):
            lst = []
            for s in st.seasons(gsp, kind):
                lo, hi = st.segments[(gsp, kind, s)]
                d = st.day[lo:hi]
                lst.append({"key": s, "start": int(d.min()), "end": int(d.max())})
            seasons[KIND_NAMES[kind]] = lst
        periods = [{"day": d, "type": t} for d, t in self.periods()[0]]
        wdf = self.water()[0]
        water = []
        if len(wdf):
            ws = set(wells)
            for r in wdf.itertuples(index=False):
                if r.Скважина in ws:
                    water.append({"well": int(r.Скважина), "month": int(r.Месяц), "year": int(r.Год),
                                  "factor": None if pd.isna(r.Водный_фактор) else float(r.Водный_фактор),
                                  "flow": None if pd.isna(r.Расход_воды_лч) else float(r.Расход_воды_лч),
                                  "note": r.Примечание})
        series = {}
        for which in ("gsp", "obj"):
            df = self.gsp_pressure(which, gsp)[0]
            if len(df):
                ds = df["Дата"].values.astype("datetime64[D]").astype("int64")
                series[which] = {"days": ds.tolist(), "bar": df["Давление_бар"].tolist()}
        sp = {w: {"%s|%s" % (KIND_NAMES[k], s): v for (k, s), v in self.season_pressure(w, gsp).items()} for w in ("gsp", "obj")}
        warnings = list(self.water()[1]) + list(self.periods()[1])
        warnings += ["Давление ГСП: " + m for m in self.pressure("gsp")[1]] + ["Давление объекта: " + m for m in self.pressure("obj")[1]]
        dirs = {w: v["dir"] for w, v in lay["wells"].items()}
        tr = self.trends([self.season_frame(gsp, OTBOR, s, dirs) for s in st.seasons(gsp, OTBOR)])
        trends = tr.to_dict("records") if len(tr) else []
        fd, ff = self.daily_flow(gsp)
        return {"gsp": gsp, "wells": wells, "layout": lay, "seasons": seasons, "periods": periods, "water": water,
                "gspFlow": {"days": fd.tolist(), "bar": [round(float(v), 1) for v in ff]},
                "pressure": series, "seasonPressure": sp, "warnings": warnings, "trends": trends,
                "depths": {str(w): list(v) for w, v in depths.items() if w in set(wells)},
                "altitude": {str(w): v for w, v in alt.items() if w in set(wells)}}

    def summary_payload(self, gsp: str, kind: str, season: str, mode: str = "auto") -> dict:
        """Таблица итогов сезона со всеми столбцами старого листа (время работы, давление, замеры воды)."""
        lay = self.layout_for(gsp, mode)
        dirs = {w: v["dir"] for w, v in lay["wells"].items()}
        k = KIND_BY_NAME[kind]
        df = self.season_frame(gsp, k, season, dirs) if season != "*" else pd.concat(
            [self.season_frame(gsp, k, s, dirs) for s in self.store.seasons(gsp, k)], ignore_index=True, sort=False)  # type: ignore[union-attr]
        df = df.sort_values(["Сезон", "Скважина"]) if len(df) else df
        rows = df.astype(object).where(df.notna(), None).values.tolist()
        return {"columns": [str(c) for c in df.columns], "rows": [[v.item() if hasattr(v, "item") else v for v in r] for r in rows]}

    def season_payload(self, gsp: str, kind: str, season: str) -> dict:
        assert self.store is not None
        k = KIND_BY_NAME[kind]
        m = self.store.matrix(gsp, k, season)
        if m is None:
            return {"wells": [], "days": [], "flow": []}
        return {"wells": m["wells"].tolist(), "days": m["days"].tolist(),
                "flow": np.round(m["flow"], 1).tolist()}

    def parameter_catalog(self) -> List[dict]:
        return self.atlas.parameters() if self.atlas is not None else []

    def parameter_payload(self, table: str, column: str, agg: str, start: str, end: str) -> dict:
        assert self.atlas is not None
        values, warn = self.atlas.parameter_values(table, column, agg, start, end)
        return {"table": table, "column": column, "agg": agg, "title": atlas_source.PARAM_TABLES[table],
                "values": {str(w): v for w, v in values.items()}, "warnings": warn}

    def gis_catalog(self) -> dict:
        return gis_source.catalog(self.atlas) if self.atlas is not None else {"packs": [], "seasons": [], "metrics": [], "note": ""}

    def gis_payload(self, pack: str, metric: str, season: str, against: str, pins: Dict[int, str]) -> dict:
        assert self.atlas is not None
        return gis_source.values(self.atlas, pack, metric, season, against, pins)

    def work_payload(self, gsp: str) -> dict:
        """Работа скважин по сезонам и месяцам: матрицы «скважина × сезон» и «скважина × месяц», очерёдность ввода."""
        st = self.store
        assert st is not None
        wells = st.wells(gsp)
        widx = {w: i for i, w in enumerate(wells)}
        segs = sorted(((gsp, kind, s) for (g, kind, s) in st.segments if g == gsp),
                      key=lambda t: (int(t[2].split("-")[0]) if t[2].split("-")[0].isdigit() else 0, t[1]))
        seasons = []
        month_set = set()
        per_month = {}
        for _g, kind, s in segs:
            lo, hi = st.segments[(gsp, kind, s)]
            w, day = st.well[lo:hi], st.day[lo:hi]
            fl = np.where(np.isfinite(st.flow[lo:hi]), st.flow[lo:hi], 0.0)
            rt = st.runtime[lo:hi]
            dt = day.astype("datetime64[D]")
            ym = dt.astype("datetime64[M]").astype("int64") + 1970 * 12  # год*12 + месяц(0–11)
            n = len(wells)
            total, days, first, idle = [0.0] * n, [0] * n, [-2] * n, [0] * n  # first: -2 нет в сезоне, -1 не работала
            starts = np.flatnonzero(np.r_[True, w[1:] != w[:-1]])
            for a, b in zip(starts, list(starts[1:]) + [len(w)]):
                i = widx[int(w[a])]
                f = fl[a:b]
                pos = f > 0
                first[i] = -1
                total[i], days[i] = float(f.sum()), int(pos.sum())
                if pos.any():
                    first[i] = int(day[a:b][pos][0])
                if np.isfinite(rt[a:b]).any():
                    idle[i] = int(((rt[a:b] > 0) & (f == 0)).sum())
            seasons.append({"kind": KIND_NAMES[kind], "key": s, "total": total, "days": days, "first": first, "idle": idle,
                            "start": int(day.min()), "end": int(day.max())})
            # по месяцам
            key = w.astype("int64") * 100000 + ym
            edges = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
            ends = list(edges[1:]) + [len(key)]
            for a, b in zip(edges, ends):
                m = int(ym[a])
                month_set.add(m)
                cell = per_month.setdefault((widx[int(w[a])], m), [0.0, 0, KIND_NAMES[kind]])
                f = fl[a:b]
                cell[0] += float(f.sum())
                cell[1] += int((f > 0).sum())
        months = sorted(month_set)
        mi = {m: j for j, m in enumerate(months)}
        n = len(wells)
        flow_m = [[0.0] * len(months) for _ in range(n)]
        days_m = [[0] * len(months) for _ in range(n)]
        for (i, m), (f, d, _k) in per_month.items():
            flow_m[i][mi[m]], days_m[i][mi[m]] = f, d
        wdf = self.water()[0]
        water_m = [[0.0] * len(months) for _ in range(n)]
        if len(wdf):
            for r in wdf.itertuples(index=False):
                m = int(r.Год) * 12 + int(r.Месяц) - 1
                if r.Скважина in widx and m in mi and r.Водный_фактор is not None and r.Водный_фактор == r.Водный_фактор:
                    water_m[widx[r.Скважина]][mi[m]] = max(water_m[widx[r.Скважина]][mi[m]], float(r.Водный_фактор))
        return {"wells": wells, "seasons": seasons, "months": months, "monthFlow": [[round(v, 1) for v in row] for row in flow_m],
                "monthDays": days_m, "monthWater": water_m}

    # ---------- анализ и выгрузка ----------
    def trends(self, frames: List[pd.DataFrame]) -> pd.DataFrame:
        """Тренд среднего суточного расхода по сезонам отбора (наклон прямой), как analyze_trends; тренд воды — по среднему ВФ сезона."""
        if not frames:
            return pd.DataFrame()
        allf = pd.concat(frames, ignore_index=True)
        wf_cols = [c for c in allf.columns if c.startswith("Водный_фактор_")]
        if wf_cols:
            allf["_wf"] = allf[wf_cols].mean(axis=1, skipna=True)
        rows = []
        for well, wd in allf.groupby("Скважина"):
            wd = wd.sort_values("Сезон")
            if len(wd) < 2:
                continue
            flow = wd["Средний_суточный_расход"].dropna().to_numpy()
            ft = float(np.polyfit(range(len(flow)), flow, 1)[0]) if len(flow) >= 2 else 0.0
            wt = 0.0
            if "_wf" in wd:
                wv = wd["_wf"].dropna().to_numpy()
                if len(wv) >= 2:
                    wt = float(np.polyfit(range(len(wv)), wv, 1)[0])
            rows.append({"Скважина": int(well), "Направление": (lambda v: v if isinstance(v, str) else "")(wd["Направление"].iloc[0]) if "Направление" in wd else "",
                         "Тренд_расхода": round(ft, 2), "Тренд_воды": round(wt, 2),
                         "Средний_расход": round(float(flow.mean()), 1) if len(flow) else 0.0})
        return pd.DataFrame(rows)

    def share_tables(self, gsp: str, dirs: Dict[int, str]) -> Dict[str, pd.DataFrame]:
        """Доли скважин и направлений по сезонам (листы старого create_well_share_analysis, те же названия столбцов)."""
        assert self.store is not None
        st = self.store
        out: Dict[str, pd.DataFrame] = {}
        any_water = len(self.water()[0]) > 0
        otbor, zak = [], []
        for kind, bucket in ((OTBOR, otbor), (ZAKACHKA, zak)):
            for s in st.seasons(gsp, kind):
                bucket.append(self.season_frame(gsp, kind, s, dirs))
        o_all = pd.concat(otbor, ignore_index=True) if otbor else pd.DataFrame()
        z_all = pd.concat(zak, ignore_index=True) if zak else pd.DataFrame()

        def detail(frames, flow, mean, days, with_water):
            data: Dict[int, dict] = {}
            seasons = []
            for df in frames:
                if not len(df):
                    continue
                season = str(df["Сезон"].iloc[0])
                total = df[flow].sum()
                if total == 0:
                    continue
                seasons.append(season)
                share = (df[flow] / total * 100).round(1)
                wf = [c for c in df.columns if c.startswith("Водный_фактор_")]
                fl = [c for c in df.columns if c.startswith("Расход_воды_")]
                for i, w in enumerate(df["Скважина"].astype(int)):
                    row = data.setdefault(w, {"Скважина": w})
                    row[season + "_Доля_%"] = share.iloc[i]
                    row[season + "_Накоп_расход"] = round(df[flow].iloc[i])
                    row[season + "_Сред_сут_расход"] = round(df[mean].iloc[i])
                    row[season + "_Дней"] = df[days].iloc[i]
                    if with_water:
                        if wf:
                            vals = df[wf].iloc[i]
                            row[season + "_Вод_фактор_сред"] = round(vals.mean(), 1) if vals.notna().any() else np.nan
                            row[season + "_Вод_фактор_макс"] = round(vals.max(), 1) if vals.notna().any() else np.nan
                            row[season + "_Замеров_с_водой"] = int((vals > 0).sum())
                            row[season + "_Расход_воды_лч"] = round(df[fl].iloc[i].sum(), 1) if fl else 0
                        elif any_water:
                            row[season + "_Вод_фактор_сред"] = np.nan
                            row[season + "_Вод_фактор_макс"] = np.nan
                            row[season + "_Замеров_с_водой"] = 0
                            row[season + "_Расход_воды_лч"] = 0
            if not data:
                return pd.DataFrame(), seasons
            frame = pd.DataFrame(list(data.values()))
            metrics = ["Доля_%", "Накоп_расход", "Сред_сут_расход", "Дней"] + (
                ["Вод_фактор_сред", "Вод_фактор_макс", "Замеров_с_водой", "Расход_воды_лч"] if with_water else [])
            cols = ["Скважина"] + [s + "_" + m for m in metrics for s in sorted(seasons) if s + "_" + m in frame.columns]
            frame = frame[cols]
            if dirs:
                frame.insert(1, "Направление", frame["Скважина"].map(dirs))
            first = sorted(seasons)[0] + "_Доля_%"
            return frame.sort_values(first, ascending=False), seasons

        if len(o_all):
            d, seasons_o = detail(otbor, "Накопленный_расход_газа", "Средний_суточный_расход", "Количество_дней", True)
            if len(d):
                out["Доли_отбор_по_сезонам"] = d
            summary = o_all.groupby("Скважина").agg(
                Средняя_доля_отбор_проц=("Накопленный_расход_газа", lambda x: round(x.sum() / o_all["Накопленный_расход_газа"].sum() * 100, 1) if o_all["Накопленный_расход_газа"].sum() > 0 else 0),
                Суммарный_отбор_тыс_м3=("Накопленный_расход_газа", "sum"),
                Средний_сут_расход_отбор=("Средний_суточный_расход", "mean"),
                Сезонов_отбора=("Сезон", "nunique"),
                Дней_работы_отбор=("Количество_дней", "sum")).reset_index()
            if len(z_all):
                zs = z_all.groupby("Скважина").agg(
                    Средняя_доля_закачка_проц=("Накопленный_расход_газа_закачка", lambda x: round(x.sum() / z_all["Накопленный_расход_газа_закачка"].sum() * 100, 1) if z_all["Накопленный_расход_газа_закачка"].sum() > 0 else 0),
                    Суммарная_закачка_тыс_м3=("Накопленный_расход_газа_закачка", "sum"),
                    Средний_сут_расход_закачка=("Средний_суточный_расход_закачка", "mean"),
                    Сезонов_закачки=("Сезон", "nunique"),
                    Дней_работы_закачка=("Количество_дней_закачка", "sum")).reset_index()
                summary = summary.merge(zs, on="Скважина", how="left").fillna(0)
            wcols = [c for c in o_all.columns if c.startswith("Водный_фактор_")]
            if wcols:
                avg = o_all.groupby("Скважина")[wcols].mean().mean(axis=1).reset_index()
                avg.columns = ["Скважина", "Сред_водный_фактор"]
                cnt = o_all.groupby("Скважина")[wcols].apply(lambda x: (x > 0).sum().sum()).reset_index()
                cnt.columns = ["Скважина", "Всего_замеров_с_водой"]
                summary = summary.merge(avg, on="Скважина", how="left").merge(cnt, on="Скважина", how="left")
            if dirs:
                summary["Направление"] = summary["Скважина"].map(dirs)
            out["Сводка_долей"] = summary.sort_values("Средняя_доля_отбор_проц", ascending=False)
            if dirs:
                rows = []
                for df in otbor:
                    if not len(df):
                        continue
                    df = df.copy()
                    df["Направление"] = df["Скважина"].map(dirs)
                    total = df["Накопленный_расход_газа"].sum()
                    if total == 0:
                        continue
                    stats = df.groupby("Направление").agg(
                        Скважин=("Скважина", "nunique"),
                        Сумм_доля_проц=("Накопленный_расход_газа", lambda x: round(x.sum() / total * 100, 1)),
                        Сумм_отбор=("Накопленный_расход_газа", "sum"),
                        Сред_расход=("Средний_суточный_расход", "mean")).reset_index()
                    wc = [c for c in df.columns if c.startswith("Водный_фактор_")]
                    if wc:
                        wd = df.groupby("Направление")[wc].apply(lambda x: (x > 0).sum().sum()).reset_index()
                        wd.columns = ["Направление", "Замеров_с_водой"]
                        stats = stats.merge(wd, on="Направление", how="left")
                    else:
                        stats["Замеров_с_водой"] = 0
                    stats["Сезон"] = "Отбор_" + str(df["Сезон"].iloc[0])
                    rows.append(stats)
                if rows:
                    out["Направления_по_сезонам"] = pd.concat(rows, ignore_index=True)
        if len(z_all):
            d, _ = detail(zak, "Накопленный_расход_газа_закачка", "Средний_суточный_расход_закачка", "Количество_дней_закачка", False)
            if len(d):
                out["Доли_закачка_по_сезонам"] = d
        return out

    def daily_flow(self, gsp: str) -> Tuple[np.ndarray, np.ndarray]:
        """Суточный расход всего ГСП (отбор и закачка вместе): дни от эпохи и сумма по скважинам."""
        assert self.store is not None
        st = self.store
        days, flows = [], []
        for (g, k, s), (lo, hi) in st.segments.items():
            if g == gsp:
                days.append(st.day[lo:hi])
                flows.append(np.where(np.isfinite(st.flow[lo:hi]), st.flow[lo:hi], 0.0))
        if not days:
            return np.zeros(0, dtype="int64"), np.zeros(0)
        d, f = np.concatenate(days), np.concatenate(flows)
        u, inv = np.unique(d, return_inverse=True)
        return u, np.bincount(inv, weights=f, minlength=len(u))

    def pressure_flow_table(self, gsp: str) -> pd.DataFrame:
        """«Данные_для_графика_давления»: давление ГСП и объекта вместе с суточным расходом ГСП по датам."""
        days, flow = self.daily_flow(gsp)
        fl = {int(d): float(v) for d, v in zip(days, flow)}
        pg, po = self.gsp_pressure("gsp", gsp)[0], self.pressure("obj")[0]
        press = {}
        for key, df in (("gsp", pg), ("obj", po)):
            press[key] = {inputs.day_of(t): float(v) for t, v in zip(df["Дата"], df["Давление_бар"])} if len(df) else {}
        alld = sorted(set(fl) | set(press["gsp"]) | set(press["obj"]))
        rows = []
        for d in alld:
            r = {"Дата": inputs.iso(d)[8:10] + "." + inputs.iso(d)[5:7] + "." + inputs.iso(d)[:4]}
            if len(pg):
                r["Давление_ГСП_бар"] = round(press["gsp"][d], 2) if d in press["gsp"] else ""
            if len(po):
                r["Давление_объекта_бар"] = round(press["obj"][d], 2) if d in press["obj"] else ""
            r["Суточный_расход_ГСП_тыс_м3"] = round(fl[d], 1) if d in fl else 0
            rows.append(r)
        cols = ["Дата"] + (["Давление_ГСП_бар"] if len(pg) else []) + (["Давление_объекта_бар"] if len(po) else []) + ["Суточный_расход_ГСП_тыс_м3"]
        return pd.DataFrame(rows, columns=cols)

    def summary_tables(self, frames: Dict[int, List[pd.DataFrame]]) -> Dict[str, pd.DataFrame]:
        """«Сводка_все_сезоны» и «Вода_по_направлениям» из итогов сезонов (как create_output_excel)."""
        out: Dict[str, pd.DataFrame] = {}
        parts = [f for k in (OTBOR, ZAKACHKA) for f in frames[k] if len(f)]
        if parts:
            out["Сводка_все_сезоны"] = pd.concat(parts, ignore_index=True, sort=False).sort_values(["Тип", "Сезон", "Скважина"])
        otb = [f for f in frames[OTBOR] if len(f)]
        if otb:
            o_all = pd.concat(otb, ignore_index=True, sort=False)
            wcols = [c for c in o_all.columns if "Водный_фактор_" in c or "Расход_воды_" in c]
            if "Направление" in o_all.columns and wcols:
                out["Вода_по_направлениям"] = o_all.groupby("Направление")[wcols].mean().reset_index()
        return out

    def export_excel(self, gsp: str, mode: str = "auto") -> Path:
        assert self.store is not None
        lay = self.layout_for(gsp, mode)
        dirs = {w: v["dir"] for w, v in lay["wells"].items()}
        frames = {OTBOR: [], ZAKACHKA: []}
        for kind in (OTBOR, ZAKACHKA):
            for s in self.store.seasons(gsp, kind):
                frames[kind].append(self.season_frame(gsp, kind, s, dirs))
        depths, alt = self.depths()
        path = self.out_dir() / ("Анализ_%s.xlsx" % gsp.replace(" ", "_").replace("/", "_"))
        with pd.ExcelWriter(str(path), engine="xlsxwriter") as xw:
            book = xw.book
            head = book.add_format({"bold": True, "bg_color": "#E6F4F5", "border": 1, "text_wrap": True, "valign": "top"})

            def put(df: pd.DataFrame, name: str) -> None:
                df.to_excel(xw, sheet_name=name[:31], index=False)
                ws = xw.sheets[name[:31]]
                for i, c in enumerate(df.columns):
                    ws.write(0, i, c, head)
                    width = max([len(str(c))] + [len(str(v)) for v in df[c].head(200)]) + 2
                    ws.set_column(i, i, min(width, 28))
                ws.freeze_panes(1, 1)
            for kind, title in ((OTBOR, "Отбор по сезонам"), (ZAKACHKA, "Закачка по сезонам")):
                if frames[kind]:
                    put(pd.concat(frames[kind], ignore_index=True), title)
            tr = self.trends(frames[OTBOR])
            if len(tr):
                put(tr, "Тренды")
            w = self.water()[0]
            if len(w):
                put(w[w["Скважина"].isin(self.store.wells(gsp))], "Вода")
            for which, nm in (("gsp", "Давление ГСП"), ("obj", "Давление объекта")):
                df = self.gsp_pressure(which, gsp)[0]
                if len(df):
                    put(df.assign(Дата=df["Дата"].dt.strftime("%d.%m.%Y")), nm)
            rows = []
            for wl in self.store.wells(gsp):
                p = lay["wells"].get(wl)
                rows.append({"Скважина": wl, "X": p["x"] if p else None, "Y": p["y"] if p else None,
                             "Источник положения": {"grid": "сетка Excel", "xy": "XY tNavigator", "fit": "по сетке (пересчёт в XY)"}.get(p["src"], "") if p else "нет",
                             "Направление": p["dir"] if p else "",
                             "Верх перфорации, м (абс.)": depths.get(wl, (None, None))[0],
                             "Низ перфорации, м (абс.)": depths.get(wl, (None, None))[1], "Альтитуда, м": alt.get(wl)})
            put(pd.DataFrame(rows), "Скважины")
            self._work_sheets(gsp, put)
            for key, df in self.summary_tables(frames).items():
                put(df, key.replace("_", " "))
            if len(self.pressure("gsp")[0]) or len(self.pressure("obj")[0]):
                put(self.pressure_flow_table(gsp), "Давление и расход ГСП")
            names = {"Доли_отбор_по_сезонам": "Доли отбор по сезонам", "Доли_закачка_по_сезонам": "Доли закачка по сезонам",
                     "Сводка_долей": "Сводка долей", "Направления_по_сезонам": "Направления по сезонам"}
            for key, df in self.share_tables(gsp, dirs).items():
                put(df, names[key])
        return path

    def _work_sheets(self, gsp: str, put) -> None:
        """Листы «работа скважин»: по сезонам, по месяцам, очерёдность ввода по каждому сезону."""
        wk = self.work_payload(gsp)
        wells = wk["wells"]
        rows = []
        for i, w in enumerate(wells):
            r = {"Скважина": w}
            for s in wk["seasons"]:
                state = "нет данных" if s["first"][i] == -2 else s["days"][i]
                r["%s %s, дней с расходом" % (s["kind"], s["key"])] = state
            rows.append(r)
        put(pd.DataFrame(rows), "Работа по сезонам")
        cols = ["%02d.%d" % (m % 12 + 1, m // 12) for m in wk["months"]]
        put(pd.DataFrame([[w] + wk["monthDays"][i] for i, w in enumerate(wells)], columns=["Скважина"] + cols), "Работа по месяцам")
        put(pd.DataFrame([[w] + wk["monthFlow"][i] for i, w in enumerate(wells)], columns=["Скважина"] + cols), "Расход по месяцам")
        order = []
        for s in wk["seasons"]:
            got = sorted((s["first"][i], w, i) for i, w in enumerate(wells) if s["first"][i] >= 0)
            for rank, (day, w, i) in enumerate(got, 1):
                order.append({"Вид": s["kind"], "Сезон": s["key"], "№": rank, "Скважина": w,
                              "Первый расход": inputs.iso(day), "Позже первой, дн.": day - got[0][0],
                              "Дней с расходом": s["days"][i], "Накоплено": s["total"][i], "Открыта, расхода нет, дн.": s["idle"][i]})
        if order:
            put(pd.DataFrame(order), "Очерёдность ввода")
        # Гант по дням: все дни всех сезонов подряд, расход в ячейке
        assert self.store is not None
        widx = {w: i for i, w in enumerate(wells)}
        days_all = sorted({int(d) for (g, k, s) in self.store.segments if g == gsp
                           for d in self.store.matrix(gsp, k, s)["days"]})
        col = {d: j for j, d in enumerate(days_all)}
        grid = np.zeros((len(wells), len(days_all)))
        for (g, k, s) in self.store.segments:
            if g != gsp:
                continue
            m = self.store.matrix(gsp, k, s)
            idx = [widx[int(w)] for w in m["wells"]]
            grid[np.ix_(idx, [col[int(d)] for d in m["days"]])] = m["flow"]
        put(pd.DataFrame(grid, columns=[inputs.iso(d) for d in days_all]).assign(Скважина=wells)[["Скважина"] + [inputs.iso(d) for d in days_all]],
            "Гант_работы_скважин")
