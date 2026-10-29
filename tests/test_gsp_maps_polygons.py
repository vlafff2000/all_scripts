"""Многоугольники Карт: разбор текстового файла «имя X Y» / «X Y»."""
from gsp_maps.polygons import parse_polygon_lines


def test_blank_line_separates_polygons_without_names():
    polys, warn = parse_polygon_lines(["100 200", "110 200", "110 210", "", "1 2", "3 4", "5 6"])
    assert [p["name"] for p in polys] == ["Многоугольник 1", "Многоугольник 2"]
    assert polys[0]["pts"] == [[100, 200], [110, 200], [110, 210]]
    assert warn == []


def test_named_rows_group_into_polygons_and_header_is_skipped():
    lines = ["X Y", "Контур A 100 200", "Контур A 110 200", "Контур A 110 210", "Контур B 1 2", "Контур B 3,5 4", "Контур B 5 6"]
    polys, _ = parse_polygon_lines(lines)
    assert [p["name"] for p in polys] == ["Контур A", "Контур B"]
    assert polys[1]["pts"][1] == [3.5, 4.0]


def test_name_line_starts_polygon_and_short_polygon_is_warned():
    polys, warn = parse_polygon_lines(["Участок 1", "0 0", "1 0", "1 1", "Участок 2", "0 0", "1 1"])
    assert [p["name"] for p in polys] == ["Участок 1"]
    assert any("Участок 2" in w for w in warn)


def test_empty_file_gives_warning():
    polys, warn = parse_polygon_lines([])
    assert polys == [] and warn
