"""Проверка исходников «Базы ГДИ из PDF-отчётов»: папка с отчётами «Мониторинг ГДИС», разбор тот же, что у модуля."""
from __future__ import annotations

from typing import Dict

from pxg_core import гдис_карта as kart
from pxg_core import гдис_pdf as pdf
from pxg_core import qc
from pxg_core.qc import Report


def check_gdis(values: Dict[str, str]) -> Report:
    rep = Report(title="База ГДИ из PDF-отчётов")
    folder = (values.get("folder") or "").strip()
    if not qc.check_path(rep, folder, "Папка с PDF-отчётами", "folder"):
        if not folder:
            rep.error("FILE", "Не указана папка с PDF-отчётами")
        return rep
    for key, label in (("db", "Прежняя база"), ("groups", "Таблица «скважина → ГСП»")):
        if (values.get(key) or "").strip():
            qc.check_path(rep, values[key].strip(), label)
    files = pdf.find_reports(folder)
    if not files:
        rep.note("FILE", "В папке нет PDF-файлов", file=folder)
        return rep
    scans = [pdf.scan_report(f) for f in files]
    templates = {sc.fingerprint for sc in scans if not sc.error}
    wells = set()
    for sc in scans:
        if sc.error:
            rep.warn("GDI", sc.error, file=sc.file)
            continue
        mapping, _src = kart.effective(sc, kart.load_saved(sc.fingerprint, (values.get("mapping") or "").strip()))
        s = kart.build_study(sc, mapping, sc.fingerprint)
        wells.add(s.well)
        for field, text in s.issues:
            rep.warn("GDI", "%s: %s" % (field, text), file=s.file)
    rep.saw("%d отчёт(ов), %d скважин, шаблонов отчёта: %d" % (len(files), len(wells - {""}), len(templates)))
    return rep
