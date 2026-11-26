"""Declared and undetected text encodings must not corrupt column identity."""

from materials_quality.science.io_nodes import table_import


def test_explicit_utf8_encoding_does_not_keep_byte_order_mark_in_header(tmp_path):
    path = tmp_path / "explicit-bom.csv"
    path.write_bytes("sample_id,value\nS1,1\n".encode("utf-8-sig"))

    result = table_import(config={"path": str(path), "encoding": "utf-8"})

    assert result.table.columns.tolist() == ["sample_id", "value"]
    assert result.table["sample_id"].tolist() == ["S1"]


def test_bomless_utf16le_source_is_detected_instead_of_nul_split_garbage(tmp_path):
    path = tmp_path / "utf16le.csv"
    path.write_bytes("sample_id,value\nS1,1\nS2,2\n".encode("utf-16-le"))

    result = table_import(config={"path": str(path)})

    assert result.table.columns.tolist() == ["sample_id", "value"]
    assert result.table.to_dict("list") == {"sample_id": ["S1", "S2"], "value": [1, 2]}
    assert result.data["encoding"] == "utf-16-le"


def test_bomless_utf16be_source_is_detected(tmp_path):
    path = tmp_path / "utf16be.tsv"
    path.write_bytes("sample_id\tvalue\nS1\t1\n".encode("utf-16-be"))

    result = table_import(config={"path": str(path)})

    assert result.table.columns.tolist() == ["sample_id", "value"]
    assert result.table["sample_id"].tolist() == ["S1"]
