"""Decimal-comma inputs must not be split on the decimal mark itself."""

from materials_quality.science.io_nodes import table_import


def test_single_column_mixed_notation_keeps_raw_cells(tmp_path):
    path = tmp_path / "ambiguous.csv"
    path.write_text("value\n1.234,56\n2,5\n", encoding="utf-8")

    result = table_import(config={"path": str(path), "decimal_separator": ","})

    assert result.table.columns.tolist() == ["value"]
    assert result.table["value"].tolist() == ["1.234,56", "2,5"]
    assert "decimal_comma_normalized_columns" not in result.data["header_diagnostics"]


def test_semicolon_delimited_decimal_comma_still_normalizes(tmp_path):
    path = tmp_path / "european.csv"
    path.write_text("time;stress\n0,1;12,34\n0,2;24,68\n", encoding="utf-8")

    result = table_import(config={"path": str(path), "decimal_separator": ","})

    assert result.table.to_dict("list") == {"time": [0.1, 0.2], "stress": [12.34, 24.68]}
    assert result.data["header_diagnostics"]["decimal_comma_normalized_columns"] == ["time", "stress"]
    assert result.data["delimiter"] == ";"


def test_default_decimal_point_comma_delimited_file_is_unchanged(tmp_path):
    path = tmp_path / "plain.csv"
    path.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")

    result = table_import(config={"path": str(path)})

    assert result.table.to_dict("list") == {"x": [1, 3], "y": [2, 4]}
    assert result.data["delimiter"] == ","
