"""Эталоны паритета: результаты старых скриптов «Создание schedule файла ТР» и `apps/schedule_tr`, снятые перед их удалением.

Хранятся как JSON с gzip в `tests/golden/`. Типы (таблицы, даты, словари с ключами-кортежами) возвращаются как были.
"""
import gzip
import json
import math
import os
from datetime import date, datetime

import numpy as np
import pandas as pd

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")


def enc(x):
    if isinstance(x, pd.DataFrame):
        return {"__df__": {"cols": [enc(c) for c in x.columns], "idx": [enc(i) for i in x.index],
                           "rows": [[enc(v) for v in r] for r in x.itertuples(index=False, name=None)],
                           "dt": [str(t) for t in x.dtypes]}}
    if isinstance(x, (pd.Timestamp, datetime)):
        return {"__ts__": pd.Timestamp(x).isoformat()}
    if isinstance(x, date):
        return {"__d__": x.isoformat()}
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return {"__f__": "nan"} if math.isnan(x) else x
    if isinstance(x, np.bool_):
        return bool(x)
    if x is pd.NaT:
        return {"__nat__": 1}
    if isinstance(x, tuple):
        return {"__t__": [enc(v) for v in x]}
    if isinstance(x, dict):
        return {"__m__": [[enc(k), enc(v)] for k, v in x.items()]}
    if isinstance(x, (list, set)):
        return [enc(v) for v in x]
    return x


def dec(x):
    if isinstance(x, list):
        return [dec(v) for v in x]
    if isinstance(x, dict):
        if "__df__" in x:
            d = x["__df__"]
            df = pd.DataFrame([[dec(v) for v in r] for r in d["rows"]], columns=[dec(c) for c in d["cols"]], index=[dec(i) for i in d["idx"]])
            for c, t in zip(df.columns, d["dt"]):
                if t.startswith("datetime64"):
                    df[c] = pd.to_datetime(df[c])
                elif t.startswith("float"):
                    df[c] = df[c].astype(float)
                elif t.startswith("int") and not df[c].isna().any():
                    df[c] = df[c].astype("int64")
            return df
        if "__ts__" in x:
            return pd.Timestamp(x["__ts__"])
        if "__d__" in x:
            return date.fromisoformat(x["__d__"])
        if "__f__" in x:
            return float("nan")
        if "__nat__" in x:
            return pd.NaT
        if "__t__" in x:
            return tuple(dec(v) for v in x["__t__"])
        if "__m__" in x:
            return {dec(k): dec(v) for k, v in x["__m__"]}
    return x


def save(key, value):
    os.makedirs(DIR, exist_ok=True)
    with gzip.open(os.path.join(DIR, key + ".json.gz"), "wt", encoding="utf-8") as f:
        json.dump(enc(value), f, ensure_ascii=False)


def golden(key):
    with gzip.open(os.path.join(DIR, key + ".json.gz"), "rt", encoding="utf-8") as f:
        return dec(json.load(f))
