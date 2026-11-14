"""Код комплекта выполняется внутри tNavigator разных версий: 19.x - Python 3.5, 21.3 - 3.6, новые версии - выше.
Модули, которые он импортирует, должны разбираться Python 3.5: без f-строк, аннотаций переменных, подчёркиваний в числах,
dataclasses и `from __future__ import annotations`."""
import ast
import io
import os
import re
import sys
import tokenize

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


def _sources():
    out = {m + '.py': open(os.path.join(PKG, m + '.py'), encoding='utf-8').read() for m in sorted(_closure())}
    out['kit_code.txt'] = open(os.path.join(PKG, 'kit_code.txt'), encoding='utf-8').read().replace('__PROJECT_DIR__', 'x')
    return out


def test_no_features_newer_than_python35_in_code_run_inside_tnavigator():
    for name, src in _sources().items():
        tree = ast.parse(src, feature_version=(3, 5))        # walrus, позиционные-only, async-ключевые слова и т. п.
        for n in ast.walk(tree):
            assert not isinstance(n, ast.JoinedStr), '%s: f-строка (Python 3.6+) в строке %d' % (name, n.lineno)
            assert not isinstance(n, ast.AnnAssign), '%s: аннотация переменной (3.6+) в строке %d, используйте type-комментарий' % (name, n.lineno)
            if isinstance(n, ast.ImportFrom):
                assert n.module not in ('__future__', 'dataclasses'), '%s: from %s import (нет в Python 3.5/3.6)' % (name, n.module)
            if isinstance(n, ast.Import):
                assert not any(a.name == 'dataclasses' for a in n.names), '%s: import dataclasses' % name
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            assert not (tok.type == tokenize.NUMBER and '_' in tok.string), '%s: подчёркивание в числе %s (3.6+)' % (name, tok.string)


def test_modules_import_with_eager_annotations():
    import importlib
    for m in ('snapshot', 'errors', 'tnav_api'):
        importlib.import_module('schedule_pxg.gdi_adapt.' + m)    # без отложенных аннотаций (как в 3.6) все имена должны существовать
