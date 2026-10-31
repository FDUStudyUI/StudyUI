"""Build small synthetic, openly reproducible IO/OCR calibration fixtures.

Run from the materials-quality package directory. No experimental results are
included: every sample name, intensity, table value and raster is synthetic.
"""

import json
import sqlite3
import zipfile
from pathlib import Path

import fitz
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


def main():
    root = Path(__file__).resolve().parent
    folder = root / "fixtures"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "samples.csv").write_text("sample,value\nA1,12\nB2,34\nC3,56\n", encoding="utf-8")
    (folder / "samples-gb18030.csv").write_bytes("样品;数值\n甲;12\n乙;34\n".encode("gb18030"))
    (folder / "lines.txt").write_text("SYNTHETIC experiment note\nTemperature: 25 C\n", encoding="utf-8")
    (folder / "fixed-width.txt").write_text("A10012\nB20034\n", encoding="utf-8")
    (folder / "spectrum.xy").write_text("# synthetic XY\n10 100\n20 200\n30 150\n", encoding="utf-8")
    (folder / "spectrum.jdx").write_text(
        "##TITLE=Synthetic spectrum\n##XYDATA=(XY..XY)\n10,100\n20,200\n30,150\n##END=\n", encoding="utf-8"
    )
    (folder / "vendor.raw").write_bytes(b"SYNTHETIC_VENDOR_DEMO\n10,100\n20,200\n")
    frame = pd.DataFrame({"sample": ["A1", "B2", "C3"], "value": [12, 34, 56]})
    with pd.ExcelWriter(folder / "samples.xlsx") as writer:
        frame.to_excel(writer, sheet_name="Experiment", index=False)
    with sqlite3.connect(folder / "samples.sqlite") as connection:
        frame.to_sql("samples", connection, if_exists="replace", index=False)
    with zipfile.ZipFile(folder / "spectrum.brml", "w") as archive:
        archive.writestr(
            "Experiment0/RawData0.xml",
            "<RawData><DataRoutes><DataRoute>"
            "<Datum>0,1,100,10,100</Datum><Datum>1,1,100,20,200</Datum>"
            "</DataRoute></DataRoutes></RawData>",
        )
    image = Image.new("RGB", (640, 300), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 32) if font_path.is_file() else ImageFont.load_default(size=32)
    for x in (20, 320, 620):
        draw.line((x, 20, x, 280), fill="black", width=3)
    for y in (20, 100, 190, 280):
        draw.line((20, y, 620, y), fill="black", width=3)
    for x, y, value in [
        (40, 40, "Sample"),
        (340, 40, "Value"),
        (40, 125, "A1"),
        (340, 125, "12"),
        (40, 215, "B2"),
        (340, 215, "34"),
    ]:
        draw.text((x, y), value, font=font, fill="black")
    image.save(folder / "table.png", dpi=(150, 150))
    document = fitz.open()
    page = document.new_page(width=640, height=300)
    page.insert_text((40, 30), "SYNTHETIC native table")
    for x in (40, 180, 320):
        page.draw_line((x, 50), (x, 210))
    for y in (50, 90, 130, 170, 210):
        page.draw_line((40, y), (320, y))
    for r, row in enumerate([("Sample", "Value"), ("A1", "12"), ("B2", "34"), ("C3", "56")]):
        for c, value in enumerate(row):
            page.insert_text((50 + 140 * c, 75 + 40 * r), value)
    document.save(folder / "native.pdf", deflate=True)
    document.close()
    document = fitz.open()
    document.new_page(width=640, height=300).insert_image(
        fitz.Rect(0, 0, 640, 300), filename=str(folder / "table.png")
    )
    document.save(folder / "scanned.pdf", deflate=True)
    document.close()
    curve = Image.new("RGB", (140, 140), "white")
    ImageDraw.Draw(curve).line((20, 120, 120, 20), fill=(255, 0, 0), width=1)
    curve.save(folder / "curve.png")
    prefix = "examples/science/io/fixtures/"
    operations = {
        "io.table_import": {
            "path": prefix + "samples.xlsx",
            "sheet": "Experiment",
            "header": 0,
            "range": "A1:B4",
        },
        "io.text_import": {
            "path": prefix + "fixed-width.txt",
            "method": "fixed_width",
            "widths": [2, 4],
            "names": ["sample", "value"],
        },
        "io.pdf_import": {"path": prefix + "scanned.pdf", "dpi": 150},
        "io.image_import": {"path": prefix + "table.png"},
        "io.instrument_import": {"path": prefix + "spectrum.jdx"},
        "io.database_import": {
            "path": prefix + "samples.sqlite",
            "method": "sqlite",
            "query": "SELECT * FROM samples WHERE value > :v",
            "parameters": {"v": 12},
        },
        "extract.pdf_text": {"path": prefix + "native.pdf", "method": "native", "pages": [1]},
        "extract.pdf_tables": {"path": prefix + "native.pdf", "method": "lines"},
        "extract.image_ocr": {"path": prefix + "table.png"},
        "extract.image_tables": {"path": prefix + "table.png"},
        "extract.chart_digitize": {
            "path": prefix + "curve.png",
            "color": [255, 0, 0],
            "color_tolerance": 5,
            "calibration": {"x": [[20, 0], [120, 10]], "y": [[120, 0], [20, 100]]},
        },
        "extract.convert_file": {"path": prefix + "samples.csv", "target": "csv"},
    }
    (root / "configs.json").write_text(json.dumps(operations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Built {len(list(folder.iterdir()))} SYNTHETIC fixtures and 12 operation configurations in {root}")


if __name__ == "__main__":
    main()
