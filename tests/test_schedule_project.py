"""Проект «Скедул ПХГ»: скважины и синонимы, дерево групп, наборы, JSON-хранение."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_pxg.project import Project  # noqa: E402


def make():
    p = Project("Тест", group_level=2)
    p.add_group("УКПГ-1")
    p.add_group("ГСП-1", "УКПГ-1")
    p.add_group("Куст-А", "ГСП-1")
    p.add_well("101", synonyms=["101-Н", "Скв.101"], group="Куст-А")
    p.add_well("102", group="ГСП-1")
    p.add_well("900", well_type="наблюдательная")
    return p


def test_resolve_synonym_case_insensitive():
    p = make()
    assert p.resolve(" скв.101 ") == "101" and p.resolve("102") == "102" and p.resolve("нет") is None


def test_duplicate_synonym_rejected():
    p = make()
    with pytest.raises(ValueError):
        p.add_well("103", synonyms=["101-Н"])


def test_tree_levels_and_wells_of():
    p = make()
    assert p.path("Куст-А") == ["УКПГ-1", "ГСП-1", "Куст-А"]
    assert p.group_at_level("101") == "ГСП-1" and p.group_at_level("102") == "ГСП-1"
    assert sorted(p.wells_of("УКПГ-1")) == ["101", "102"]
    assert p.wells_without_group() == ["900"]


def test_group_cycle_and_unknown_parent():
    p = make()
    with pytest.raises(ValueError):
        p.add_group("X", "нет")
    with pytest.raises(ValueError):
        p.add_group("УКПГ-1", "Куст-А")


def test_sets_and_roundtrip(tmp_path):
    p = make()
    p.set_set("новые", ["101", "900"])
    with pytest.raises(ValueError):
        p.set_set("плохой", ["999"])
    p.save(str(tmp_path))
    q = Project.load(str(tmp_path))
    assert (q.name, q.group_level, q.wells, q.groups, q.well_group, q.sets) == (
        p.name, p.group_level, p.wells, p.groups, p.well_group, p.sets)
