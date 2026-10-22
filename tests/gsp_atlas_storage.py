"""Проект Газового Атласа для тестов «Карт ГСП»: manifest.json и снимок parquet в формате `atlas/engine/core/storage.py`.
Атлас не импортируется: файлы пишутся так, как их пишет Атлас, а Карты их только читают."""
import json
from pathlib import Path

import pandas as pd

PID = "a" * 32


def production(o: pd.DataFrame, z: pd.DataFrame) -> pd.DataFrame:
    """Таблицы «Отборы» и «Закачка» (как в БД_расходы.xlsx) → таблица `production` Атласа."""
    def part(df, kind):
        out = pd.DataFrame({"well": df["Скважина"].astype(int).astype(str), "date": pd.to_datetime(df["Дата"]),
                            "q": df["Суточный расход газа"].astype(float), "kind": kind, "group": df["Источник"]})
        out["season"] = df["Сезон"].to_numpy() if "Сезон" in df else ""
        out["year"] = df["Год"].astype(str).to_numpy() if "Год" in df else ""
        return out
    return pd.concat([part(o, "withdrawal"), part(z, "injection")], ignore_index=True)


def write_project(root: Path, tables: dict, *, name="Тест", settings=None, groups=None, pid=PID, revision=3, demo=False) -> Path:
    base = Path(root) / "projects" / pid
    snap = base / "snapshots" / ("s" * 32)
    snap.mkdir(parents=True, exist_ok=True)
    for key, frame in tables.items():
        frame.to_parquet(snap / (key + ".parquet"), index=False)
    manifest = {"id": pid, "name": name, "demo": demo, "revision": revision, "updated": "2026-10-21T06:00:00+00:00",
                "tables": {k: len(v) for k, v in tables.items()}, "snapshot": "s" * 32,
                "settings": settings or {}, "groups": groups or {}, "imports": []}
    (base / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return Path(root)
