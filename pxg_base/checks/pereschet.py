"""Проверка исходников «Пересчёта давлений»: база замеров и справочники альтитуд и перфораций."""
from __future__ import annotations

from typing import Dict

from pxg_core import qc, пересчет_давлений as pc
from pxg_core.qc import Report
from pxg_base.webspec import lines_of  # noqa: F401


def check_recalc(values: Dict[str, str]) -> Report:
    rep = Report(title="Пересчёт давлений")
    db_path, refs_path = (values.get("db") or "").strip(), (values.get("refs") or "").strip()
    ok_db = qc.check_path(rep, db_path, "База давлений по замерам")
    ok_refs = qc.check_path(rep, refs_path, "Справочники")
    if not ok_db or not ok_refs:
        if not db_path or not refs_path:
            rep.error("FILE", "Нужны база давлений и книга со справочниками")
        return rep
    sheets = qc.excel_sheets(rep, db_path)
    if sheets is None:
        return rep
    if "Данные" not in sheets:
        rep.error("HEADER", "В базе нет листа «Данные» (нужен результат модуля «База давлений по замерам»)", file=db_path)
        return rep
    try:
        refs = pc.read_refs(refs_path)
    except Exception as e:
        rep.error("FILE", "Справочники не читаются: %s" % str(e)[:200], file=refs_path)
        return rep
    if not refs.altitude:
        rep.error("HEADER", "Нет листа «Альтитуды» со столбцами «Скважина, Z»", file=refs_path)
    if not refs.perf_mark:
        rep.error("HEADER", "Нет листа «Перфорации» с абсолютными отметками верха перфораций", file=refs_path)
    db = pc.read_measurements(db_path)
    rep.saw("%d замеров, альтитуд %d, отметок перфорации %d" % (len(db), len(refs.altitude), len(refs.perf_mark)))
    try:
        excluded = [int(x) for x in (values.get("excluded") or "").replace(";", ",").split(",") if x.strip()]
    except ValueError:
        rep.error("NUM", "«Скважины без пересчёта»: нужны номера через запятую", value=values.get("excluded"))
        excluded = list(pc.DEFAULT_EXCLUDED)
    wells = sorted(set(int(w) for w in db["Скважина"]))
    need = set()
    for w in wells:
        sub = db[db["Скважина"] == w]
        if w not in excluded and (sub["Уровень_жидкости"].notna().any() or sub["Избыточное_давление"].notna().any()):
            need.add(w)
    for w in sorted(need - set(refs.altitude)):
        rep.error("CROSS", "Нет альтитуды: давление скважины не пересчитывается", well=w, hint="Добавьте скважину на лист «Альтитуды»")
    for w in sorted((need & set(refs.altitude)) - set(refs.perf_mark)):
        rep.error("CROSS", "Нет отметки перфорации: давление скважины не пересчитывается", well=w,
                  hint="Добавьте отметку на лист «Перфорации» (Excel считал её нулём, здесь строка остаётся без давления)")
    levels = db["Уровень_жидкости"].dropna()
    if len(levels) and levels.gt(0).any() and levels.lt(0).any():
        rep.warn("UNIT", "Уровень жидкости с разными знаками (%d положительных, %d отрицательных)" % (
            int(levels.gt(0).sum()), int(levels.lt(0).sum())), hint="Знак выбирается в форме: «всегда ниже устья» или «как в отчёте»")
    both = db[db["Руст"].notna() & (db["Уровень_жидкости"].notna() | db["Избыточное_давление"].notna())]
    if len(both):
        rep.note("CROSS", "У %d замеров есть и Руст, и уровень или избыточное давление: пересчёта нет, берётся Рпл как есть" % len(both))
    no_p = db[db["Рпл"].isna() & (db["Уровень_жидкости"].notna() | db["Избыточное_давление"].notna() | db["Руст"].notna())]
    if len(no_p):
        rep.note("GAP", "%d замеров без пластового давления: пересчёт для них невозможен" % len(no_p))
    return rep
