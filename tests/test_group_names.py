"""Единая схема имён групп (аудит объединения, пункт 8): Карты и Атлас сравнивают группы одинаково.

Тот же список случаев есть в gas_atlas/tests/atlas/test_group_names.py: менять только вместе.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gsp_maps.store import gsp_key  # noqa: E402

# (название из одного файла, название из другого, одна ли это группа)
CASES = [
    ('ГСП-1', 'ГСП 1', True),
    ('ГСП_4', 'гсп 4', True),
    ('ГСП4', 'ГСП 4', True),
    ('СП-2', 'СП 2', True),
    ('ГСП 1', 'ГСП 2', False),
    ('ГСП 1', 'ГСП 10', False),
]


@pytest.mark.parametrize('a, b, same', CASES)
def test_group_names_compare_the_same_way(a, b, same):
    assert (gsp_key(a) == gsp_key(b)) is same
