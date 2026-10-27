import re

import pytest

from pxg_core import group_colors as gc


def test_palettes_have_exact_size_and_are_distinct():
    for n in range(2, 16):
        p = gc.palette_for(n)
        assert len(p) == n and len(set(p)) == n
        assert all(re.fullmatch(r'#[0-9A-Fa-f]{6}', c) for c in p)


def test_more_than_fifteen_groups_extends_palette():
    p = gc.palette_for(20)
    assert len(p) == 20 and len(set(c.lower() for c in p)) == 20 and p[:15] == list(gc.PALETTES[15])


def test_same_group_same_color_for_any_spelling_and_natural_order():
    colors = gc.group_colors(['ГСП-10', 'ГСП 2', 'гсп1', 'Без группы'], {})
    assert list(colors) == ['гсп1', 'ГСП 2', 'ГСП-10']
    again = gc.group_colors(['ГСП-1', 'ГСП-2', 'ГСП-10'], {})
    assert [colors[k] for k in colors] == list(again.values())
    assert gc.color_of('ГСП_2', colors) == colors['ГСП 2']
    assert gc.color_of('Без группы', colors) == gc.NO_GROUP_COLOR


def test_override_is_remembered_and_wins(tmp_path, monkeypatch):
    monkeypatch.setenv('PXG_HOME', str(tmp_path))
    gc.set_override('ГСП 1', '#112233')
    assert gc.group_colors(['ГСП-1', 'ГСП-2'])['ГСП-1'] == '#112233'
    gc.set_override('ГСП-1', None)
    assert gc.group_colors(['ГСП-1', 'ГСП-2'])['ГСП-1'] == gc.PALETTES[2][0]
    with pytest.raises(ValueError):
        gc.set_override('ГСП-1', 'red')


def test_chart_colors_do_not_depend_on_which_groups_are_on_the_chart():
    gc.set_known_groups([f'ГСП-{i}' for i in range(1, 10)])
    try:
        part = gc.colors_for(['ГСП 3', 'ГСП 7'])
        whole = gc.group_colors([f'ГСП-{i}' for i in range(1, 10)], {})
        assert part == {'ГСП 3': whole['ГСП-3'], 'ГСП 7': whole['ГСП-7']}
    finally:
        gc.set_known_groups([])


def test_typescript_palettes_match_python():
    from pathlib import Path
    ts = (Path(__file__).resolve().parent.parent / 'pxg_core' / 'web-ui' / 'groupColors.ts').read_text(encoding='utf-8')
    found = {int(n): tuple(re.findall(r"'(#[0-9A-Fa-f]{6})'", row))
             for n, row in re.findall(r'^\s+(\d+): \[(.*)\],$', ts, re.M)}
    assert found == {n: tuple(p) for n, p in gc.PALETTES.items()}


def test_routes_store_and_reset_colors(tmp_path, monkeypatch):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    monkeypatch.setenv('PXG_HOME', str(tmp_path))
    client = TestClient(Starlette(routes=gc.routes()))
    assert client.get('/api/group-colors').json() == {'overrides': {}}
    assert client.post('/api/group-colors', json={'group': 'ГСП 1', 'color': '#AABBCC'}).json() == {'overrides': {'гсп 1': '#aabbcc'}}
    assert client.post('/api/group-colors', json={'group': 'ГСП-2', 'color': 'red'}).status_code == 400
    assert client.post('/api/group-colors', json={'group': 'ГСП 1', 'color': None}).json() == {'overrides': {}}
    client.post('/api/group-colors', json={'group': 'ГСП 3', 'color': '#010203'})
    assert client.post('/api/group-colors', json={'group': '*', 'color': None}).json() == {'overrides': {}}
