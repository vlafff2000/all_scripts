"""«Преобразование таблиц ГДИ в базу»: полностью пустой числовой столбец (например «% КРУ» в базе из PDF-отчётов) не ломает очистку."""
import importlib
import os
import sys

import pytest

pd = pytest.importorskip("pandas")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

gdi = importlib.import_module("pxg_base.modules.Преобразование_исходных_таблиц_ГДИ_в_базу")


def test_clean_apostrophes_keeps_all_empty_numeric_columns():
    df = pd.DataFrame({"№скв": [37, None], "ГСП": [1, None], "a": [0.37, None], "% КРУ": [None, None],
                       "№ режима": [None, None], "Qгаза тыс.м3/сут": ["134,2", "270.6"], "метод исслед.": ["стац", None]})
    out = gdi.clean_apostrophes(df)
    assert out["% КРУ"].isna().all() and out["№ режима"].isna().all()
    assert out["Qгаза тыс.м3/сут"].tolist() == [134.2, 270.6]
    assert out["№скв"].iloc[0] == 37
