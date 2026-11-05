"""«Отчёты и файлы»: копирование по маске, распаковка архивов, копирование замеров по шаблонам (без окон и веба)."""
import importlib.util
import os
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name):
    path = ROOT / "pxg_base" / "modules" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


copy_mod = load("Копирование_файлов_по_маске")
unpack_mod = load("Распаковка_архивов")
pressure_mod = load("Копирование_замеров_давлений_по_шаблонам")


def make(path: Path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_extensions_and_groups():
    assert copy_mod.parse_extensions(" .DOCX; odt,docx ") == ["docx", "odt"]
    assert copy_mod.wanted_extensions("word", "") == copy_mod.GROUPS["word"]
    assert copy_mod.wanted_extensions("word", "pdf") == ["pdf"]
    assert copy_mod.wanted_extensions("", "") is None


def test_copy_by_group_from_subfolders_with_conflicts(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make(src / "a" / "отчёт.docx", "1")
    make(src / "b" / "c" / "отчёт.docx", "2")  # то же имя, другое содержимое → суффикс
    make(src / "b" / "таблица.xlsx", "3")
    make(src / "a" / "письмо.doc", "4")
    res = copy_mod.run(src, dst, copy_mod.wanted_extensions("word", ""), report_dir=tmp_path / "rep")
    names = sorted(p.name for p in dst.iterdir() if p.name != copy_mod.REPORT_NAME)
    assert names == ["отчёт.docx", "отчёт_1.docx", "письмо.doc"]
    assert res["found"] == 3 and len(res["copied"]) == 3
    assert (tmp_path / "rep" / copy_mod.REPORT_NAME).is_file()


def test_no_recursion_and_fragment_filter(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make(src / "Акт_сверки.pdf")
    make(src / "sub" / "акт_2024.pdf")
    make(src / "sub" / "письмо.pdf")
    copy_mod.run(src, dst, None, fragment="АКТ", recursive=False, report_dir=tmp_path / "rep")
    assert sorted(p.name for p in dst.iterdir()) == ["Акт_сверки.pdf"]
    copy_mod.run(src, dst, None, fragment="акт", recursive=True, report_dir=tmp_path / "rep")
    assert sorted(p.name for p in dst.iterdir() if p.name != copy_mod.REPORT_NAME) == ["Акт_сверки.pdf", "акт_2024.pdf"]


def test_one_per_name_keeps_more_important_extension(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make(src / "a" / "акт.pdf", "p")
    make(src / "a" / "акт.docx", "d")
    copy_mod.run(src, dst, ["pdf", "docx"], report_dir=tmp_path / "rep")
    assert [p.name for p in dst.iterdir()] == ["акт.pdf"]  # pdf раньше в списке, значит важнее
    res = copy_mod.run(src, tmp_path / "dst2", ["docx", "pdf"], one_per_name=True, report_dir=tmp_path / "rep")
    assert [p.name for p, _ in res["copied"]] == ["акт.docx"]


def test_identical_content_copied_once(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make(src / "1" / "x.txt", "same")
    make(src / "2" / "y.txt", "same")
    res = copy_mod.run(src, dst, ["txt"], report_dir=tmp_path / "rep")
    assert len(res["copied"]) == 1 and len(res["skipped"]) == 1


def test_dry_run_and_skip_destination(tmp_path):
    src = tmp_path / "src"
    dst = src / "копии"  # внутри источника: сами копии не должны попасть в список
    make(src / "f.pdf")
    res = copy_mod.run(src, dst, ["pdf"], dry_run=True, report_dir=tmp_path / "rep")
    assert res["found"] == 1 and not dst.exists()
    copy_mod.run(src, dst, ["pdf"], report_dir=tmp_path / "rep")
    again = copy_mod.run(src, dst, ["pdf"], report_dir=tmp_path / "rep")
    assert again["found"] == 1  # папка «копии» пропущена при обходе


def test_copy_main_refuses_empty_conditions(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    assert copy_mod.main(["--source=%s" % src, "--dest=%s" % (tmp_path / "d"), "--group=", "--extensions="]) == 1
    assert "Задайте хотя бы одно условие" in capsys.readouterr().out


def test_unpack_zip_and_tar_gz_and_delete(tmp_path):
    folder = tmp_path / "arch"
    folder.mkdir()
    with zipfile.ZipFile(folder / "данные.zip", "w") as z:
        z.writestr("sub/один.txt", "1")
    src = tmp_path / "t.txt"
    src.write_text("2", encoding="utf-8")
    with tarfile.open(folder / "пакет.tar.gz", "w:gz") as t:
        t.add(src, arcname="два.txt")
    found = unpack_mod.find_archives(folder)
    assert [p.name for p in found] == ["данные.zip", "пакет.tar.gz"]
    assert unpack_mod.folder_name("пакет.tar.gz") == "пакет"
    ok, msg, target = unpack_mod.unpack(folder / "данные.zip", delete=True)
    assert ok and (target / "sub" / "один.txt").read_text(encoding="utf-8") == "1"
    assert not (folder / "данные.zip").exists()
    ok, _, target = unpack_mod.unpack(folder / "пакет.tar.gz")
    assert ok and (target / "два.txt").exists() and (folder / "пакет.tar.gz").exists()


def test_unpack_broken_archive_leaves_no_empty_folder(tmp_path):
    bad = tmp_path / "битый.zip"
    bad.write_bytes(b"not a zip")
    ok, msg, target = unpack_mod.unpack(bad)
    assert not ok and "ошибка" in msg and not (tmp_path / "битый").exists()


def test_pressure_templates_by_year():
    assert pressure_mod.extract_year_from_path("/root/2016/набл.xlsx") == 2016
    assert pressure_mod.get_template_by_year(2016) == 1
    assert pressure_mod.get_template_by_year(2020) == 2
    assert pressure_mod.get_template_by_year(2025) == 3
    assert pressure_mod.get_template_by_year(2030) is None


# ---- Сравнение папок ----
cmp_mod = load("Сравнение_папок")


def _two_folders(tmp_path):
    a, b = tmp_path / "Папка А", tmp_path / "Папка Б"
    make(a / "общий.txt"); make(b / "ОБЩИЙ.TXT")
    make(a / "только_а.pdf"); make(a / "sub" / "отчёт_1.docx"); make(a / "~$лок.docx")
    make(b / "только_б.xlsx"); make(b / "deep" / "x" / "акт.pdf")
    return a, b


def _names(res):
    return sorted((s, p.name) for s, p, _ in res["copied"])


def test_cmp_masks_parse_and_match():
    assert cmp_mod.parse_masks("*.pdf, отчет*;\n~$*\n.docx") == ["*.pdf", "отчет*", "~$*", "*.docx"]
    assert cmp_mod.name_matches("Отчёт.PDF", ["*.pdf"]) and not cmp_mod.name_matches("Отчёт.PDF", ["*.pdf"], True)


def test_cmp_modes_and_case(tmp_path):
    a, b = _two_folders(tmp_path)
    both = cmp_mod.run(a, b, None, "both")
    assert ("A", "только_а.pdf") in _names(both) and ("B", "только_б.xlsx") in _names(both)
    assert all(n.lower() != "общий.txt" for _, n in _names(both))   # регистр не учитывается
    only_a = cmp_mod.run(a, b, None, "a")
    assert {s for s, _ in _names(only_a)} == {"A"}
    only_b = cmp_mod.run(a, b, None, "b", recursive=False)
    assert _names(only_b) == [("B", "только_б.xlsx")]   # вложенная папка не просматривается
    strict = cmp_mod.run(a, b, None, "a", case_sensitive=True)
    assert ("A", "общий.txt") in _names(strict)


def test_cmp_include_exclude(tmp_path):
    a, b = _two_folders(tmp_path)
    res = cmp_mod.run(a, b, None, "both", include=cmp_mod.parse_masks("*.pdf, *.docx"), exclude=cmp_mod.parse_masks("~$*"))
    assert _names(res) == [("A", "отчёт_1.docx"), ("A", "только_а.pdf"), ("B", "акт.pdf")]


def test_cmp_copy_no_overwrite_and_collisions(tmp_path):
    a, b, dest = tmp_path / "a", tmp_path / "b", tmp_path / "Итог"
    make(a / "1" / "акт.pdf", "A1"); make(a / "2" / "акт.pdf", "A2"); make(b / "акт2.pdf", "B")
    make(dest / "акт.pdf", "СТАРЫЙ")
    res = cmp_mod.run(a, b, dest, "both", dry_run=False)
    assert (dest / "акт.pdf").read_text(encoding="utf-8") == "СТАРЫЙ"          # не перезаписан
    copied = sorted(p.name for p in dest.iterdir())
    assert len(copied) == 4 and "акт2.pdf" in copied and "1_акт.pdf" in copied and "2_акт.pdf" in copied
    assert (a / "1" / "акт.pdf").exists() and not res["errors"]                 # оригиналы на месте


def test_cmp_dry_run_and_manual_exclusion(tmp_path):
    a, b, dest = tmp_path / "a", tmp_path / "b", tmp_path / "out"
    make(a / "x.pdf"); make(a / "y.pdf"); b.mkdir()
    preview = cmp_mod.run(a, b, dest, "a", dry_run=True)
    assert len(preview["copied"]) == 2 and not dest.exists()
    res = cmp_mod.run(a, b, dest, "a", skip_lines=["X.PDF"], dry_run=False)
    assert [p.name for p in dest.iterdir()] == ["y.pdf"] and res["skipped"][0][2] == "исключён вручную"
    res = cmp_mod.run(a, b, tmp_path / "o2", "a", skip_lines=[str(a / "y.pdf")], dry_run=False)
    assert [p.name for p in (tmp_path / "o2").iterdir()] == ["x.pdf"]


def test_cmp_dest_inside_source_ignored_and_report(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    make(a / "x.pdf"); b.mkdir()
    dest = a / "копии"
    cmp_mod.run(a, b, dest, "a", dry_run=False)
    again = cmp_mod.run(a, b, dest, "a", dry_run=True)
    assert [p.name for _, p, _ in again["copied"]] == ["x.pdf"]
    path = cmp_mod.write_report(again, a, b, dest, "a", True, tmp_path / "rep")
    assert path and path.exists() and path.name == "сравнение_папок.xlsx"


def test_cmp_main_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a, b, dest = tmp_path / "a", tmp_path / "b", tmp_path / "out"
    make(a / "x.pdf"); make(a / "y.tmp"); b.mkdir()
    base = ["--folder-a=%s" % a, "--folder-b=%s" % b, "--dest=%s" % dest, "--mode=a", "--exclude=*.tmp"]
    assert cmp_mod.main(base + ["--dry-run=да"]) == 0 and not dest.exists()
    assert cmp_mod.main(base + ["--dry-run=нет"]) == 0 and [p.name for p in dest.iterdir()] == ["x.pdf"]
