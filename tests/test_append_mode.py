"""Режим дополнения: результат дополнения совпадает с полной пересборкой."""
import os

import pandas as pd
import pytest

from pxg_core import append_mode as am

SCHEMA, VER = "s1", 1


def _write(folder, name, rows):
    p = os.path.join(folder, name)
    pd.DataFrame(rows, columns=["Скважина", "Дата", "Q"]).to_csv(p, index=False)
    return p


def _parse(path):
    return pd.read_csv(path)


def _files(folder):
    return sorted(os.path.join(folder, f) for f in os.listdir(folder))


def _build(folder, old=None, reg=None, **kw):
    return am.run(old, reg, _files(folder), str(folder), _parse, schema_version=SCHEMA, parse_version=VER, **kw)


def _norm(df):
    return df.sort_values(["Источник", "Скважина", "Дата"]).reset_index(drop=True)


def test_append_equals_full_rebuild(tmp_path):
    _write(tmp_path, "a.csv", [["1", "2026-01-01", 5], ["2", "2026-01-01", 6]])
    data, reg, _ = _build(tmp_path)
    _write(tmp_path, "b.csv", [["1", "2026-02-01", 7]])
    data2, reg2, plan = _build(tmp_path, data, reg)
    assert dict(zip(plan["Файл"], plan["Статус"])) == {"a.csv": am.SAME, "b.csv": am.NEW}
    full, _, _ = _build(tmp_path, rebuild=True)
    pd.testing.assert_frame_equal(_norm(data2), _norm(full))
    assert set(reg2.frame["Файл"]) == {"a.csv", "b.csv"}


def test_changed_file_is_replaced_and_unchanged_not_parsed(tmp_path):
    _write(tmp_path, "a.csv", [["1", "2026-01-01", 5]])
    _write(tmp_path, "b.csv", [["1", "2026-02-01", 7]])
    data, reg, _ = _build(tmp_path)
    _write(tmp_path, "a.csv", [["1", "2026-01-01", 99], ["3", "2026-01-02", 1]])
    calls = []
    data2, _, plan = am.run(data, reg, _files(tmp_path), str(tmp_path), lambda p: calls.append(p) or _parse(p),
                            schema_version=SCHEMA, parse_version=VER)
    assert [os.path.basename(c) for c in calls] == ["a.csv"]
    full, _, _ = _build(tmp_path, rebuild=True)
    pd.testing.assert_frame_equal(_norm(data2), _norm(full))


def test_missing_file_keeps_rows_unless_engineer_drops(tmp_path):
    _write(tmp_path, "a.csv", [["1", "2026-01-01", 5]])
    _write(tmp_path, "b.csv", [["1", "2026-02-01", 7]])
    data, reg, _ = _build(tmp_path)
    os.remove(tmp_path / "b.csv")
    kept, reg_k, plan = _build(tmp_path, data, reg)
    assert plan.set_index("Файл").loc["b.csv", "Статус"] == am.GONE and len(kept) == 2
    assert "b.csv" in set(reg_k.frame["Файл"])
    dropped, reg_d, _ = _build(tmp_path, data, reg, drop_missing=True)
    assert list(dropped["Источник"]) == ["a.csv"] and "b.csv" not in set(reg_d.frame["Файл"])


def test_engineer_decision_overrides(tmp_path):
    _write(tmp_path, "a.csv", [["1", "2026-01-01", 5]])
    data, reg, _ = _build(tmp_path)
    _, _, plan = _build(tmp_path, data, reg, decisions={"a.csv": am.PROCESS})
    assert am.to_process(plan) == [str(tmp_path / "a.csv")]
    assert "решение инженера" in plan.loc[0, "Причина"]


def test_plan_only_changes_nothing(tmp_path):
    _write(tmp_path, "a.csv", [["1", "2026-01-01", 5]])
    data, reg, plan = _build(tmp_path, plan_only=True)
    assert data is None and reg is None and plan.loc[0, "Статус"] == am.NEW


def test_old_version_requires_rebuild(tmp_path):
    _write(tmp_path, "a.csv", [["1", "2026-01-01", 5]])
    data, reg, _ = _build(tmp_path)
    reg.parse_version = 0
    with pytest.raises(ValueError, match="правила разбора"):
        _build(tmp_path, data, reg)
    data2, reg2, _ = _build(tmp_path, data, reg, rebuild=True)  # кнопка «Пересобрать полностью»
    assert reg2.parse_version == VER and len(data2) == 1


def test_registry_roundtrip_in_xlsx_and_backup(tmp_path):
    _write(tmp_path, "a.csv", [["1", "2026-01-01", 5]])
    data, reg, _ = _build(tmp_path)
    db = str(tmp_path.parent / (tmp_path.name + "_db.xlsx"))

    def write(p):
        with pd.ExcelWriter(p) as xw:
            data.to_excel(xw, sheet_name="Данные", index=False)
            for name, frame in reg.sheets().items():
                frame.to_excel(xw, sheet_name=name, index=False)
    am.atomic_write(db, write)
    back = am.backup(db)
    assert os.path.isfile(back) and not os.path.exists(db.replace(".xlsx", ".tmp.xlsx"))
    reg2 = am.Registry.read(db)
    assert reg2.parse_version == VER and reg2.schema_version == SCHEMA
    plan = am.make_plan(reg2, _files(tmp_path), str(tmp_path))
    assert list(plan["Статус"]) == [am.SAME]
    assert am.Registry.read(str(tmp_path / "a.csv")) is None  # не xlsx = старая база без реестра


def test_default_cache_dir_is_outside_results_and_separates_input_sets(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    a = am.cache_dir("mod", [str(tmp_path / "A")])
    assert a == am.cache_dir("mod", [str(tmp_path / "A")]) and a.startswith(str(tmp_path / "home"))
    assert a != am.cache_dir("mod", [str(tmp_path / "B")]) and a != am.cache_dir("other", [str(tmp_path / "A")])
    assert am.cache_dir("mod", [str(tmp_path / "A")], explicit="x") == "x"
