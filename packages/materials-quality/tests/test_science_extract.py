"""Synthetic pages, raster tables and calibrated curves have known answers."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont


def _text_image(path, text="Sample 123"):
    image = Image.new("RGB", (800, 180), "white")
    font = ImageFont.truetype(font_manager.findfont("DejaVu Sans"), 48)
    ImageDraw.Draw(image).text((30, 45), text, fill="black", font=font)
    image.save(path)


def _table_image(path):
    image = Image.new("RGB", (640, 300), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_manager.findfont("DejaVu Sans"), 32)
    for x in [20, 320, 620]:
        draw.line((x, 20, x, 280), fill="black", width=3)
    for y in [20, 100, 190, 280]:
        draw.line((20, y, 620, y), fill="black", width=3)
    for x, y, text in [
        (40, 40, "Sample"),
        (340, 40, "Value"),
        (40, 125, "A1"),
        (340, 125, "12"),
        (40, 215, "B2"),
        (340, 215, "34"),
    ]:
        draw.text((x, y), text, fill="black", font=font)
    image.save(path)


def test_pdf_text_page_order_locations_and_selection(tmp_path):
    import fitz

    from materials_quality.science.extract_nodes import pdf_text

    source = tmp_path / "text.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 150), "Second paragraph")
    page.insert_text((50, 50), "First paragraph")
    doc.new_page().insert_text((50, 50), "Other page")
    doc.save(source)
    doc.close()
    result = pdf_text(config={"path": str(source), "pages": [1], "method": "native"})
    assert result.data["text"].index("First") < result.data["text"].index("Second")
    assert "Other page" not in result.data["text"]
    assert result.table["page"].tolist() == [1, 1]
    assert result.table.iloc[0]["bbox"][1] < result.table.iloc[1]["bbox"][1]


@pytest.mark.parametrize("method", ["lines", "text"])
def test_pdf_table_native_methods(tmp_path, method):
    import fitz

    from materials_quality.science.extract_nodes import pdf_tables

    source = tmp_path / "table.pdf"
    doc = fitz.open()
    page = doc.new_page()
    if method == "lines":
        for x in [40, 180, 320]:
            page.draw_line((x, 40), (x, 200))
        for y in [40, 80, 120, 160, 200]:
            page.draw_line((40, y), (320, y))
    for row, values in enumerate([("Sample", "Value"), ("A1", "12"), ("B2", "34"), ("C3", "56")]):
        for column, value in enumerate(values):
            page.insert_text((50 + column * 140, 65 + row * 40), value)
    doc.save(source)
    doc.close()
    result = pdf_tables(config={"path": str(source), "method": method})
    assert result.table["Sample"].dropna().tolist() == ["A1", "B2", "C3"]
    assert result.data["tables"][0]["page"] == 1
    assert len(result.data["tables"][0]["bbox"]) == 4
    assert result.data["tables"][0]["cells"]


def test_actual_ocr_text_locations_confidence_and_region(tmp_path):
    from materials_quality.science.extract_nodes import image_ocr

    source = tmp_path / "words.png"
    _text_image(source)
    result = image_ocr(config={"path": str(source), "regions": [[20, 20, 700, 160]]})
    assert "123" in result.data["text"]
    assert result.data["engine"] == "rapidocr_onnxruntime"
    assert result.data["regions"][0]["bbox"] == [20, 20, 700, 160]
    assert all(0 <= word["confidence"] <= 1 for word in result.data["words"])
    assert result.data["words"][0]["bbox"][0] >= 20
    assert result.data["words"][0]["granularity"] in {"word", "character"}


def test_image_table_cell_segmentation_real_ocr(tmp_path):
    from materials_quality.science.extract_nodes import image_tables

    source = tmp_path / "table.png"
    _table_image(source)
    result = image_tables(config={"path": str(source)})
    assert result.table.shape == (2, 2)
    assert str(result.table.iloc[0, 1]) == "12"
    assert str(result.table.iloc[1, 1]) == "34"
    cells = result.data["tables"][0]["cells"]
    assert len(cells) == 6
    assert cells[3]["row"] == 1 and cells[3]["column"] == 1
    assert cells[3]["bbox"][0] > 300


def test_scanned_pdf_text_and_table_ocr_fallback(tmp_path):
    import fitz

    from materials_quality.science.extract_nodes import pdf_tables, pdf_text

    image_path = tmp_path / "table.png"
    _table_image(image_path)
    source = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page(width=640, height=300).insert_image(fitz.Rect(0, 0, 640, 300), filename=str(image_path))
    doc.save(source)
    doc.close()
    text_result = pdf_text(
        config={"path": str(source), "method": "auto", "dpi": 150, "output_dir": str(tmp_path / "text")}
    )
    assert "Sample" in text_result.data["text"]
    assert text_result.table.iloc[0]["method"] == "ocr"
    table_result = pdf_tables(
        config={"path": str(source), "method": "auto", "dpi": 150, "output_dir": str(tmp_path / "tables")}
    )
    assert "12" in table_result.table.astype(str).values
    assert table_result.data["tables"][0]["method"] == "ocr"


def test_calibrated_curve_digitization_known_pixels(tmp_path):
    from materials_quality.science.extract_nodes import chart_digitize

    source = tmp_path / "curve.png"
    image = Image.new("RGB", (140, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.line((20, 120, 120, 20), fill=(255, 0, 0), width=1)
    image.save(source)
    calibration = {"x": [[20, 0], [120, 10]], "y": [[120, 0], [20, 100]]}
    result = chart_digitize(
        config={"path": str(source), "calibration": calibration, "color": [255, 0, 0], "color_tolerance": 5}
    )
    assert len(result.table) == 101
    assert result.table.iloc[0]["x"] == 0 and result.table.iloc[-1]["y"] == 100
    assert np.max(np.abs(result.table["y"] - result.table["x"] * 10)) < 1e-10
    with pytest.raises(ValueError, match="calibration"):
        chart_digitize(config={"path": str(source), "color": [255, 0, 0]})


def test_logarithmic_calibration_and_region(tmp_path):
    from materials_quality.science.extract_nodes import chart_digitize

    source = tmp_path / "curve.png"
    image = Image.new("RGB", (50, 50), "white")
    ImageDraw.Draw(image).line((10, 30, 30, 10), fill=(0, 0, 255))
    image.save(source)
    result = chart_digitize(
        config={
            "path": str(source),
            "color": [0, 0, 255],
            "calibration": {"x": [[10, 1], [30, 100]], "y": [[30, 0], [10, 20]], "x_scale": "log"},
            "region": [10, 10, 31, 31],
        }
    )
    middle = result.table[result.table["pixel_x"] == 20].iloc[0]
    assert middle["x"] == pytest.approx(10)


@pytest.mark.parametrize("target", ["csv", "txt", "png"])
def test_file_conversion_actual_readback_and_source_preservation(tmp_path, target):
    from materials_quality.science.extract_nodes import convert_file

    source = tmp_path / "input.csv"
    source.write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    original = source.read_bytes()
    result = convert_file(config={"path": str(source), "target": target, "output_dir": str(tmp_path / "out")})
    output = Path(result.artifacts[0])
    if target == "csv":
        assert pd.read_csv(output).to_dict("list") == {"x": [1, 3], "y": [2, 4]}
    elif target == "txt":
        assert "1\t2" in output.read_text(encoding="utf-8")
    else:
        with Image.open(output) as image:
            assert image.width > 10 and image.height > 10
    assert source.read_bytes() == original


def test_conversion_never_overwrites_input_even_with_overwrite_true(tmp_path):
    from materials_quality.science.extract_nodes import convert_file

    source = tmp_path / "converted.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    original = source.read_bytes()
    result = convert_file(
        config={
            "path": str(source),
            "target": "csv",
            "filename": "converted.csv",
            "output_dir": str(tmp_path),
            "overwrite": True,
        }
    )
    assert Path(result.artifacts[0]).resolve() != source.resolve()
    assert source.read_bytes() == original


def test_conversion_table_input_protects_explicit_source_path(tmp_path):
    from materials_quality.science.extract_nodes import convert_file

    source = tmp_path / "converted.csv"
    source.write_text("original raw file", encoding="utf-8")
    result = convert_file(
        pd.DataFrame({"x": [4]}),
        config={
            "path": str(source),
            "target": "csv",
            "filename": "converted.csv",
            "output_dir": str(tmp_path),
            "overwrite": True,
        },
    )
    assert source.read_text(encoding="utf-8") == "original raw file"
    assert pd.read_csv(result.artifacts[0])["x"].tolist() == [4]


def test_blank_image_ocr_does_not_invent_success(tmp_path):
    from materials_quality.science.extract_nodes import image_ocr

    source = tmp_path / "blank.png"
    Image.new("RGB", (300, 100), "white").save(source)
    result = image_ocr(config={"path": str(source)})
    assert result.table.empty and result.data["text"] == ""
    assert result.data["words"] == [] and result.warnings


def test_pdf_png_and_text_conversions_readback(tmp_path):
    import fitz

    from materials_quality.science.extract_nodes import convert_file

    source = tmp_path / "source.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Original scientific text")
    doc.save(source)
    doc.close()
    text = convert_file(config={"path": str(source), "target": "txt", "output_dir": str(tmp_path / "txt")})
    assert "Original scientific text" in Path(text.artifacts[0]).read_text(encoding="utf-8")
    png = convert_file(config={"path": str(source), "target": "png", "output_dir": str(tmp_path / "png")})
    with Image.open(png.artifacts[0]) as image:
        assert image.width > 500 and image.height > 500


def test_image_png_conversion_reads_actual_pixels(tmp_path):
    from materials_quality.science.extract_nodes import convert_file

    source = tmp_path / "source.bmp"
    Image.new("RGB", (30, 20), (10, 20, 30)).save(source)
    result = convert_file(config={"path": str(source), "target": "png", "output_dir": str(tmp_path / "png")})
    with Image.open(result.artifacts[0]) as image:
        assert image.getpixel((10, 10)) == (10, 20, 30)


def test_pdf_duplicate_headers_preserve_every_cell_with_existing_suffix(tmp_path):
    import fitz

    from materials_quality.science.extract_nodes import pdf_tables

    source = tmp_path / "duplicate-header.pdf"
    document = fitz.open()
    page = document.new_page()
    for x in [40, 180, 320, 460]:
        page.draw_line((x, 40), (x, 120))
    for y in [40, 80, 120]:
        page.draw_line((40, y), (460, y))
    for row, values in enumerate([["A", "A", "A_2"], ["first", "middle", "last"]]):
        for column, value in enumerate(values):
            page.insert_text((50 + column * 140, 65 + row * 40), value)
    document.save(source)
    document.close()
    result = pdf_tables(config={"path": str(source), "method": "lines"})
    assert result.table.columns.is_unique
    assert list(result.data["tables"][0]["records"][0].values()) == ["first", "middle", "last"]
    assert result.table.iloc[0].tolist() == ["first", "middle", "last"]


def test_shared_raster_table_parser_preserves_colliding_printed_headers():
    from materials_quality.science.extract_nodes import _frame_rows

    frame = _frame_rows([["A", "A", "A_2"], ["first", "middle", "last"]], {})
    assert frame.columns.is_unique
    assert list(frame.to_dict("records")[0].values()) == ["first", "middle", "last"]
