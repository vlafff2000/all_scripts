from __future__ import annotations

import os
from pathlib import Path

import pytest

from pxg_core import desktop_shortcuts as ds

ICONS = Path(__file__).resolve().parent.parent / 'tools' / 'icons'


def test_every_app_has_png_and_ico():
    for icon, title, bat, sh in ds.APPS:
        assert (ICONS / (icon + '.png')).stat().st_size > 1000, icon
        assert (ICONS / (icon + '.ico')).stat().st_size > 1000, icon


@pytest.mark.skipif(os.name == 'nt', reason='.desktop-файлы создаются только на Linux')
def test_creates_desktop_files(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'share'))
    root = tmp_path / 'Ishodnye_dannye'
    (root / 'icons').mkdir(parents=True)
    for _, _, _, sh in ds.APPS:
        (root / sh).write_text('#!/bin/bash\n')
    made = ds.create(tmp_path / 'desk', root)
    assert 'Поисковик' in [t for t, _ in made] and (tmp_path / 'share' / 'applications' / 'pxg-poiskovik.desktop').exists()
    assert len(made) == len(ds.APPS)
    text = (tmp_path / 'desk' / 'ГДМ.desktop').read_text(encoding='utf-8')
    assert 'Terminal=true' in text and 'gdm.sh' in text and 'icons/gdm.png' in text
    assert ds.remove(tmp_path / 'desk') == len(ds.APPS)
    assert not (tmp_path / 'share' / 'applications' / 'pxg-poiskovik.desktop').exists()
