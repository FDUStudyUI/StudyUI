"""Boundary: malformed or hostile files must fail with actionable ValueError.

Each case is a plausible user mistake (wrong file picked, truncated copy,
oversized embedded cell) that previously escaped as an opaque third-party
exception or was silently decoded as the wrong encoding.
"""

import pytest
from PIL import Image

from materials_quality.science.extract_nodes import (
    convert_file,
    image_ocr,
    image_tables,
    pdf_tables,
)
from materials_quality.science.io_nodes import (
    image_import,
    instrument_import,
    pdf_import,
    table_import,
)


def test_nul_byte_text_file_is_not_misdetected_as_utf16(tmp_path):
    path = tmp_path / "nul.csv"
    path.write_bytes(b"a,b\n1\x00x,2\n")

    with pytest.raises(ValueError, match="NUL|encoding|delimit|parse"):
        table_import(config={"path": str(path)})


def test_one_megabyte_cell_is_imported_not_rejected_by_csv_field_limit(tmp_path):
    cell = "x" * 1_000_000
    path = tmp_path / "huge.csv"
    path.write_text("v\n" + cell + "\n", encoding="utf-8")

    result = table_import(config={"path": str(path)})

    assert result.table["v"].iloc[0] == cell


def test_truncated_utf16_file_raises_clean_error(tmp_path):
    path = tmp_path / "odd.csv"
    path.write_bytes(b"v\x00a\x00l")

    with pytest.raises(ValueError):
        table_import(config={"path": str(path)})


def test_empty_and_corrupt_pdf_raise_clean_error(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4 garbage")

    for path in (empty, corrupt):
        with pytest.raises(ValueError, match="PDF"):
            pdf_import(config={"path": str(path)})
        with pytest.raises(ValueError, match="PDF"):
            pdf_tables(config={"path": str(path)})


def test_encrypted_pdf_raises_clean_error(tmp_path):
    import fitz

    path = tmp_path / "locked.pdf"
    document = fitz.open()
    document.new_page().insert_text((40, 40), "confidential")
    document.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    document.close()

    with pytest.raises(ValueError, match="encrypt|password|PDF"):
        pdf_import(config={"path": str(path)})


def test_corrupt_raster_raises_clean_error_in_every_image_node(tmp_path):
    path = tmp_path / "fake.png"
    path.write_bytes(b"not an image")

    with pytest.raises(ValueError, match="image|decode"):
        image_import(data={"file_path": str(path)})
    with pytest.raises(ValueError, match="image|decode"):
        image_ocr(config={"path": str(path)})
    with pytest.raises(ValueError, match="image|decode"):
        image_tables(config={"path": str(path)})
    with pytest.raises(ValueError, match="image|decode"):
        convert_file(config={"path": str(path), "target": "png", "output_dir": str(tmp_path / "out")})


def test_fractional_explicit_grid_lines_raise_value_error(tmp_path):
    path = tmp_path / "table.png"
    Image.new("RGB", (64, 64), "white").save(path)

    with pytest.raises(ValueError, match="grid|integer"):
        image_tables(config={"path": str(path), "x_lines": [0.5, 10.0], "y_lines": [0.5, 10.0]})


def test_corrupt_hdf5_like_file_raises_clean_error(tmp_path):
    path = tmp_path / "broken.h5"
    path.write_bytes(b"not hdf5")

    with pytest.raises(ValueError):
        instrument_import(config={"path": str(path)})


def test_missing_instrument_plugin_module_raises_value_error(tmp_path):
    path = tmp_path / "sample.raw"
    path.write_bytes(b"vendor binary")

    with pytest.raises(ValueError, match="plugin"):
        instrument_import(config={"path": str(path), "plugin": "definitely_missing_module:convert"})
