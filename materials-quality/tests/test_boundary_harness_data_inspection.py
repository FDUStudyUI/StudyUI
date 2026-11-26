"""Boundary tests: text encoding and unparsable table files fail cleanly."""

import pytest

from materials_quality.agent.data_inspection import authorized_file, inspect_file


def _inspect(path):
    return inspect_file(authorized_file(str(path), f"请分析 {path}"))


def test_utf16_unicode_text_export_is_decoded_as_table(tmp_path):
    path = tmp_path / "export.txt"
    path.write_bytes("time\tvalue\n1\t2\n3\t4\n".encode("utf-16"))

    result = _inspect(path)

    assert result["encoding"].startswith("utf-16")
    assert result["delimiter"] == "\t"
    assert result["rows"] == 3
    assert result["numeric_blocks"]
    assert result["first_row_text_labels"][0]["label"] == "time"


def test_binary_file_with_data_suffix_raises_value_error(tmp_path):
    path = tmp_path / "binary.csv"
    path.write_bytes(b"\x00\x01\x02\x03binary\x00data")

    with pytest.raises(ValueError):
        _inspect(path)


def test_structurally_invalid_xlsx_container_raises_value_error(tmp_path):
    import zipfile

    path = tmp_path / "broken.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("dummy.txt", "x")

    with pytest.raises(ValueError, match="Excel"):
        _inspect(path)


def test_non_zip_xlsx_raises_value_error(tmp_path):
    path = tmp_path / "not-a-zip.xlsx"
    path.write_bytes(b"not a zip archive")

    with pytest.raises(ValueError, match="Excel"):
        _inspect(path)


def test_legacy_xls_suffix_is_rejected_cleanly(tmp_path):
    path = tmp_path / "legacy.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0binary-xls")

    with pytest.raises(ValueError):
        _inspect(path)
