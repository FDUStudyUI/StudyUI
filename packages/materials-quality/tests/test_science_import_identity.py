"""Scientific identifiers and literal source cells survive table ingestion."""

import hashlib

import pandas as pd
import pytest

from materials_quality.science.io_nodes import table_import, text_import


def test_default_delimited_import_preserves_zero_padded_identity_and_raw_file(tmp_path):
    path = tmp_path / "identity.tsv"
    raw = "sample_id\tvalue\n001\t1.5\n01\t2.5\n1\t3.5\n".encode()
    path.write_bytes(raw)
    result = text_import(config={"path": str(path), "method": "delimited"})
    assert result.table.to_dict("list") == {"sample_id": ["001", "01", "1"], "value": [1.5, 2.5, 3.5]}
    assert result.data["schema"]["sample_id"]["conversion"] == "preserved-leading-zero"
    assert result.data["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result.data["source_bytes"] == len(raw)
    assert path.read_bytes() == raw


def test_identifiers_and_explicit_text_schema_are_applied_before_numeric_inference(tmp_path):
    path = tmp_path / "text.csv"
    path.write_text("sample_id,batch,value\n1,10,2\n2,20,3\n", encoding="utf-8")
    result = table_import(
        config={"path": str(path), "id_columns": ["sample_id"], "dtype": {"batch": "string"}}
    )
    assert result.table.to_dict("list") == {"sample_id": ["1", "2"], "batch": ["10", "20"], "value": [2, 3]}
    assert result.data["schema"]["sample_id"]["role"] == "identifier"
    assert result.data["schema"]["batch"]["requested_dtype"] == "string"


def test_explicit_decimal_comma_normalizes_numeric_columns_and_preserves_source(tmp_path):
    path = tmp_path / "measurements.lis"
    raw = "time\tstress\n0,10\t12,34\n0,20\t24,68\n".encode("cp1252")
    path.write_bytes(raw)

    result = table_import(
        config={
            "path": str(path),
            "encoding": "cp1252",
            "delimiter": "\t",
            "decimal_separator": ",",
        }
    )

    assert result.table.to_dict("list") == {"time": [0.1, 0.2], "stress": [12.34, 24.68]}
    assert result.data["header_diagnostics"]["decimal_comma_normalized_columns"] == ["time", "stress"]
    assert result.data["decimal_separator"] == ","
    assert path.read_bytes() == raw


def test_decimal_comma_does_not_guess_mixed_thousands_and_decimal_notation(tmp_path):
    path = tmp_path / "ambiguous.csv"
    path.write_text("value\n1.234,56\n2,5\n", encoding="utf-8")

    result = table_import(config={"path": str(path), "decimal_separator": ","})

    assert result.table["value"].tolist() == ["1.234,56", "2,5"]
    assert "decimal_comma_normalized_columns" not in result.data["header_diagnostics"]


def test_table_import_reports_exact_raw_source_hash_and_byte_size(tmp_path):
    path = tmp_path / "original.xy"
    raw = b"angle,intensity\n5.0,17\n5.1,18\n"
    path.write_bytes(raw)

    result = table_import(config={"path": str(path)})

    assert result.data["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result.data["source_bytes"] == len(raw)
    assert path.read_bytes() == raw


def test_excel_retains_literal_na_text_and_native_numeric_cells(tmp_path):
    path = tmp_path / "source.xlsx"
    pd.DataFrame({"code": ["NA", "N/A", "001"], "value": [1, 2, 3]}).to_excel(path, index=False)
    result = table_import(config={"path": str(path)})
    assert result.table["code"].tolist() == ["NA", "N/A", "001"]
    assert result.table["value"].tolist() == [1, 2, 3]
    assert pd.api.types.is_numeric_dtype(result.table["value"])


def test_large_integer_with_missing_cell_is_never_rounded_through_float(tmp_path):
    path = tmp_path / "exact.csv"
    path.write_text("serial,value\n9007199254740993,1\n,2\n", encoding="utf-8")
    result = table_import(config={"path": str(path)})
    assert result.table["serial"].tolist() == ["9007199254740993", ""]
    assert result.data["schema"]["serial"]["conversion"] == "preserved-integer-precision"
    with pytest.raises(ValueError, match="precision|exact"):
        table_import(config={"path": str(path), "dtype": {"serial": "float64"}})


@pytest.mark.parametrize(
    "config",
    [
        {"id_columns": "code"},
        {"id_columns": ["missing"]},
        {"dtype": {"missing": "string"}},
        {"dtype": {"code": "invalid-dtype"}},
        {"id_columns": ["code"], "dtype": {"code": "int64"}},
    ],
)
def test_invalid_or_conflicting_import_schema_is_rejected(tmp_path, config):
    path = tmp_path / "source.csv"
    path.write_text("code,value\n001,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dtype|column|schema"):
        table_import(config={"path": str(path), **config})


@pytest.mark.parametrize(
    "value,dtype",
    [
        ("1.75", "int64"),
        ("-1.75", "Int64"),
        ("128", "int8"),
        ("256", "uint8"),
        ("-1", "uint8"),
        ("Infinity", "int64"),
    ],
)
def test_integer_schema_rejects_fractional_nonfinite_and_out_of_range_values(tmp_path, value, dtype):
    path = tmp_path / "integer.csv"
    path.write_text(f"value\n{value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="integer|range|dtype"):
        table_import(config={"path": str(path), "dtype": {"value": dtype}})


def test_nullable_integer_schema_preserves_large_values_without_float_intermediate(tmp_path):
    path = tmp_path / "integer.csv"
    path.write_text("value,id\n9007199254740993,1\n,2\n-1.0,3\n1e2,4\n", encoding="utf-8")
    result = table_import(config={"path": str(path), "dtype": {"value": "Int64"}})
    assert result.table["value"].iloc[0] == 9007199254740993
    assert pd.isna(result.table["value"].iloc[1])
    assert result.table["value"].iloc[2:].tolist() == [-1, 100]


@pytest.mark.parametrize("dtype", ["bool", "boolean"])
def test_boolean_schema_parses_canonical_words_without_python_truthiness(tmp_path, dtype):
    path = tmp_path / "boolean.csv"
    path.write_text("flag\nFalse\nTrue\nfalse\nTRUE\n", encoding="utf-8")
    result = table_import(config={"path": str(path), "dtype": {"flag": dtype}})
    assert result.table["flag"].tolist() == [False, True, False, True]


@pytest.mark.parametrize("value", ["yes", "0", "1", ""])
def test_boolean_schema_rejects_noncanonical_truthy_or_empty_strings(tmp_path, value):
    path = tmp_path / "boolean.csv"
    path.write_text(f"flag,id\n{value},1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="boolean|dtype"):
        table_import(config={"path": str(path), "dtype": {"flag": "bool"}})


def test_boolean_schema_accepts_native_excel_booleans(tmp_path):
    path = tmp_path / "boolean.xlsx"
    pd.DataFrame({"flag": [False, True]}).to_excel(path, index=False)
    result = table_import(config={"path": str(path), "dtype": {"flag": "bool"}})
    assert result.table["flag"].tolist() == [False, True]
