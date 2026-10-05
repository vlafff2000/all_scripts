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

from . import inputs, wellmap
from .store import KIND_BY_NAME, KIND_NAMES, OTBOR, ZAKACHKA, Store, season_of

PATH_KEYS = ["db", "periods", "water", "map", "xy", "press_gsp", "press_obj", "depths"]
LABELS = {"db": "База расходов", "periods": "Периоды работы", "water": "Замеры воды", "map": "Карта-сетка (Excel)",
          "xy": "Координаты XY (tNavigator)", "press_gsp": "Давление по ГСП", "press_obj": "Давление по объекту",
          "depths": "Глубины и альтитуды"}


def config_file() -> Path:
    return Path(os.environ.get("GSP_MAPS_HOME") or Path.home() / ".gsp_maps") / "config.json"


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def detect_files(folder: str) -> Dict[str, str]:
    """Находит файлы в папке данных по именам (как в старом скрипте, плюс координаты XY)."""
    out: Dict[str, str] = {}
    if not folder or not os.path.isdir(folder):
        return out
    entries = sorted(os.listdir(folder))
    low = {e: e.lower() for e in entries}
    for e in entries:
        path, name, isdir = os.path.join(folder, e), low[e], os.path.isdir(os.path.join(folder, e))
        if isdir:
            if "замер" in name or "вод" in name:
                out.setdefault("water", path)
            continue
        ext = os.path.splitext(name)[1]
        if ext in (".xlsx", ".xlsm", ".xls") and "бд" in name and "расход" in name:
            out.setdefault("db", path)
        elif ext == ".txt" and ("period" in name or "период" in name):
            out.setdefault("periods", path)
        elif ext == ".txt" and "давление" in name and "гсп" in name:
            out.setdefault("press_gsp", path)
        elif ext == ".txt" and "давление" in name and "объект" in name:
            out.setdefault("press_obj", path)
        elif ext in (".xlsx", ".xlsm", ".xls") and "карта" in name:
            out.setdefault("map", path)
        elif ext in (".xlsx", ".xlsm", ".xls") and ("глубин" in name or "перфор" in name):
            out.setdefault("depths", path)
        elif ext in (".txt", ".csv", ".dat", ".xlsx", ".xls", ".inc") and ("xy" in name or "координат" in name or "tnav" in name or "навигатор" in name):
            out.setdefault("xy", path)
    return out


def water_files(spec: str) -> List[str]:
    out: List[str] = []
    for part in [p.strip() for p in (spec or "").splitlines() if p.strip()]:
        if os.path.isdir(part):
            out += [os.path.join(part, f) for f in sorted(os.listdir(part))
                    if f.lower().endswith((".xls", ".xlsx")) and not f.startswith("~$")]
        elif os.path.isfile(part):
            out.append(part)
    return out


class Project:
    def __init__(self) -> None:
        self.paths: Dict[str, str] = {k: "" for k in PATH_KEYS}
        self.results_dir = ""
        self.store: Optional[Store] = None
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
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        try:
            config_file().parent.mkdir(parents=True, exist_ok=True)
            config_file().write_text(json.dumps({"paths": self.paths, "results_dir": self.results_dir}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
        except OSError:
            pass

    def set_paths(self, paths: Dict[str, str], results_dir: Optional[str] = None) -> None:
        with self._lock:
            old_db = self.paths["db"]
            for k in PATH_KEYS:
                if k in paths:
                    self.paths[k] = str(paths[k] or "").strip().strip('"')
            if results_dir is not None:
                self.results_dir = results_dir.strip()
            if self.paths["db"] != old_db:
                self.store, self.state = None, "idle"
            self._save()

    def out_dir(self) -> Path:
        if self.results_dir:
            base = Path(self.results_dir)
        elif self.paths["db"]:
            base = Path(os.path.abspath(self.paths["db"])).parent / "Результаты карт ГСП"
        else:
            base = Path.home() / "Результаты карт ГСП"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # ---------- загрузка базы ----------
    def start_loading(self) -> None:
        with self._lock:
            if self.state == "loading" or not self.paths["db"]:
                return
            if self.store is not None and self.store.path == self.paths["db"]:
                self.state = "ready"
                return
            self.state, self.log = "loading", []
        threading.Thread(target=self._load_db, daemon=True).start()

    def _load_db(self) -> None:
        path = self.paths["db"]
        try:
            if not os.path.isfile(path):
                raise FileNotFoundError("Файл не найден: " + path)
            t0 = time.time()
            store = Store.open(path, lambda m: self.log.append(m))
            self.store = store
            self.log.append("Готово: ГСП — %d, строк — %d (%.1f с)" % (len(store.gsp_names), len(store.well), time.time() - t0))
            self.state = "ready"
        except Exception as e:  # показываем человеку, а не роняем сервер
            self.log.append("Ошибка: %s" % e)
            self.state = "error"

    # ---------- кэш по файлам ----------
    def _memo(self, key: Tuple, mt: float, make: Callable[[], object]):
        hit = self._cache.get(key)
        if hit is not None and hit[0] == mt:  # type: ignore[index]
            return hit[1]  # type: ignore[index]
        val = make()
        self._cache[key] = (mt, val)
        return val

    def periods(self):
        p = self.paths["periods"]
        return self._memo(("periods", p), _mtime(p), lambda: inputs.load_periods(p))

    def depths(self):
        p = self.paths["depths"]
        return self._memo(("depths", p), _mtime(p), lambda: inputs.load_perforations(p))

    def water(self):
        files = water_files(self.paths["water"])
        mt = sum(_mtime(f) for f in files) + len(files)
        return self._memo(("water", tuple(files)), mt, lambda: inputs.load_water(files))

    def pressure(self, which: str):
        p = self.paths["press_" + which]
        return self._memo(("press", p), _mtime(p), lambda: inputs.load_pressure(p, which == "gsp"))

    def grid(self, gsp: str):
        p = self.paths["map"]
        return self._memo(("grid", p, gsp), _mtime(p), lambda: wellmap.read_grid(p, gsp))

    def xy(self):
        p = self.paths["xy"]
        return self._memo(("xy", p), _mtime(p), lambda: wellmap.read_xy(p))

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
        xy: Dict[int, Tuple[float, float]] = {}
        if self.paths["xy"] and os.path.isfile(self.paths["xy"]):
            try:
                xy = self.xy()[0]
            except Exception:
                xy = {}
        out = {}
        for g in self.store.gsp_names:
            grid = any(g.lower() in sh for sh in sheets)
            has_xy = bool(xy) and any(w in xy for w in self.store.wells(g))
            out[g] = {"grid": grid, "xy": has_xy}
        return out

    def check(self) -> List[dict]:
        out = []
        for k in PATH_KEYS:
            p = self.paths[k]
            item = {"id": k, "label": LABELS[k], "path": p, "ok": False, "info": ""}
            if not p:
                item["info"] = "не задан"
            elif not os.path.exists(p):
                item["info"] = "не найден"
            else:
                try:
                    item["ok"], item["info"] = True, self._describe(k)
                except Exception as e:
                    item["info"] = "не читается: %s" % e
            out.append(item)
        return out

    def _describe(self, k: str) -> str:
        if k == "db":
            return "загружена: %d ГСП" % len(self.store.gsp_names) if self.store else "файл есть"
        if k == "periods":
            return "периодов: %d" % len(self.periods()[0])
        if k == "water":
            df = self.water()[0]
            return "замеров: %d, месяцев: %d" % (len(df), df["Метка_замера"].nunique() if len(df) else 0)
        if k == "map":
            return "листы: " + ", ".join(wellmap.list_sheets(self.paths["map"])[:6])
        if k == "xy":
            xy, warn = self.xy()
            return "скважин с XY: %d" % len(xy) + ("; " + warn[0] if warn else "")
        if k in ("press_gsp", "press_obj"):
            df, _ = self.pressure(k[6:])
            return "точек: %d" % len(df)
        d, a = self.depths()
        return "перфорации: %d, альтитуды: %d" % (len(d), len(a))

    # ---------- расчёты для интерфейса ----------
    def season_pressure(self, which: str) -> Dict[Tuple[int, str], float]:
        """Среднее давление за сезон: по месяцу замера (как add_directions_and_pressure)."""
        df, _ = self.pressure(which)
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
            v = self.season_pressure(which).get((kind, season))
            if v is not None:
                df[col] = v
        w = self.water()[0]
        if len(w):
            sk = [season_of(int(m), int(y)) for m, y in zip(w["Месяц"], w["Год"])]
            sel = w[[k == (season, KIND_NAMES[kind]) for k in sk]]
            for mark in sorted(sel["Метка_замера"].unique()):
                part = sel[sel["Метка_замера"] == mark].drop_duplicates("Скважина").set_index("Скважина")
                df["Водный_фактор_" + mark] = df["Скважина"].map(part["Водный_фактор"])
                df["Расход_воды_%s_лч" % mark] = df["Скважина"].map(part["Расход_воды_лч"])
        return df

    def layout_for(self, gsp: str, mode: str) -> dict:
        assert self.store is not None
        wells = self.store.wells(gsp)
        cells, dims, notes = {}, (0, 0), []
        if self.paths["map"] and os.path.isfile(self.paths["map"]) and mode in ("auto", "grid", "xy"):
            try:
                cells, dims, _ = self.grid(gsp)
            except KeyError as e:
                notes.append(str(e.args[0]))
            except Exception as e:
                notes.append("Карта-сетка не прочитана: %s" % e)
        xy: Dict[int, Tuple[float, float]] = {}
        if self.paths["xy"] and os.path.isfile(self.paths["xy"]) and mode in ("auto", "xy"):
            try:
                xy, w = self.xy()
                notes += w
            except Exception as e:
                notes.append("Файл XY не прочитан: %s" % e)
        res = wellmap.layout(wells, cells, dims, xy, mode)
        res["notes"] = notes + res["notes"]
        res["has_grid"], res["has_xy"] = bool(cells), any(w in xy for w in wells)
        return res

    def gsp_payload(self, gsp: str, mode: str = "auto") -> dict:
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
            df = self.pressure(which)[0]
            if len(df):
                ds = df["Дата"].values.astype("datetime64[D]").astype("int64")
                series[which] = {"days": ds.tolist(), "bar": df["Давление_бар"].tolist()}
        sp = {w: {"%s|%s" % (KIND_NAMES[k], s): v for (k, s), v in self.season_pressure(w).items()} for w in ("gsp", "obj")}
        warnings = list(self.water()[1]) + list(self.periods()[1])
        warnings += ["Давление ГСП: " + m for m in self.pressure("gsp")[1]] + ["Давление объекта: " + m for m in self.pressure("obj")[1]]
        dirs = {w: v["dir"] for w, v in lay["wells"].items()}
        tr = self.trends([self.season_frame(gsp, OTBOR, s, dirs) for s in st.seasons(gsp, OTBOR)])
        trends = tr.to_dict("records") if len(tr) else []
        return {"gsp": gsp, "wells": wells, "layout": lay, "seasons": seasons, "periods": periods, "water": water,
                "pressure": series, "seasonPressure": sp, "warnings": warnings, "trends": trends,
                "depths": {str(w): list(v) for w, v in depths.items() if w in set(wells)},
                "altitude": {str(w): v for w, v in alt.items() if w in set(wells)}}

    def season_payload(self, gsp: str, kind: str, season: str) -> dict:
        assert self.store is not None
        k = KIND_BY_NAME[kind]
        m = self.store.matrix(gsp, k, season)
        if m is None:
            return {"wells": [], "days": [], "flow": []}
        return {"wells": m["wells"].tolist(), "days": m["days"].tolist(),
                "flow": np.round(m["flow"], 1).tolist()}

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
                df = self.pressure(which)[0]
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
