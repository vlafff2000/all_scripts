"""Код комплекта выполняется внутри tNavigator 21.3 (Python 3.6): модули, которые он импортирует, не должны требовать 3.7+."""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(os.path.dirname(HERE), 'schedule_pxg', 'gdi_adapt')
sys.path.insert(0, os.path.dirname(HERE))


def _closure():
    """Модули комплекта, которые тянет code.py: tnav_api -> errors, snapshot."""
    code = open(os.path.join(PKG, 'kit_code.txt'), encoding='utf-8').read()
    mods = set(re.findall(r'from pi_dfac(?:\.(\w+))? import', code)) | set(re.findall(r'from pi_dfac import (\w+)', code))
    todo, seen = {m for m in mods if m}, set()
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        tree = ast.parse(open(os.path.join(PKG, m + '.py'), encoding='utf-8').read())
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.level == 1 and n.module:
                todo.add(n.module)
    return seen | {'__init__'}


def test_closure_found():
    assert {'tnav_api', 'snapshot', 'errors'} <= _closure()


def test_no_python37_features_in_modules_run_inside_tnavigator():
    for m in sorted(_closure()):
        src = open(os.path.join(PKG, m + '.py'), encoding='utf-8').read()
        tree = ast.parse(src, feature_version=(3, 6))        # walrus, позиционные-only и т. п. здесь упадут
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                assert n.module not in ('__future__', 'dataclasses'), '%s.py: from %s import (нет в Python 3.6)' % (m, n.module)
            if isinstance(n, ast.Import):
                assert not any(a.name == 'dataclasses' for a in n.names), '%s.py: import dataclasses' % m


def test_modules_import_with_eager_annotations():
    import importlib
    for m in ('snapshot', 'errors', 'tnav_api'):
        importlib.import_module('schedule_pxg.gdi_adapt.' + m)    # без отложенных аннотаций (как в 3.6) все имена должны существовать
