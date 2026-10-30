"""Evidence-preserving PDF, raster OCR, grid and calibrated-curve extraction."""

from functools import lru_cache
from pathlib import Path
from threading import RLock

import numpy as np
import pandas as pd

from materials_quality.science.contracts import NodeResult, read_path, require_table
from materials_quality.science.io_nodes import (
    _pages,
    _safe_artifact,
    instrument_import,
    pdf_import,
    table_import,
    text_import,
)

_OCR_LOCK = RLock()


@lru_cache(maxsize=4)
def _ocr_engine(config_path=None):
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ValueError(
            "OCR requires rapidocr_onnxruntime with its ONNX detection/classification/recognition models"
        ) from exc
    if config_path and not Path(config_path).is_file():
        raise ValueError("ocr_config_path does not exist")
    try:
        return RapidOCR(config_path=config_path, intra_op_num_threads=1, inter_op_num_threads=1)
    except Exception as exc:
        raise ValueError(
            "OCR engine/model initialization failed; install RapidOCR ONNX models or supply ocr_config_path"
        ) from exc


def _bbox(polygon):
    points = np.asarray(polygon, dtype=float)
    return [
        float(points[:, 0].min()),
        float(points[:, 1].min()),
        float(points[:, 0].max()),
        float(points[:, 1].max()),
    ]


def _region(value, width, height):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("region must be [left, top, right, bottom] in source image pixels")
    numbers = np.asarray(value, dtype=float)
    if not np.isfinite(numbers).all() or any(float(number) != int(number) for number in numbers):
        raise ValueError("region coordinates must be finite integer pixels")
    left, top, right, bottom = map(int, value)
    if not 0 <= left < right <= width or not 0 <= top < bottom <= height:
        raise ValueError("region lies outside the input image or has zero area")
    return left, top, right, bottom


def _ocr_array(rgb, config, offset=(0, 0), region_id=0):
    engine = _ocr_engine(config.get("ocr_config_path"))
    score = float(config.get("text_score", 0.5))
    if not 0 <= score <= 1:
        raise ValueError("text_score must lie between zero and one")
    # RapidOCR 1.4.4 receives BGR ndarray; return_word_box exposes its CTC-derived
    # character/word polygons rather than invented equal-width token positions.
    with _OCR_LOCK:
        result, timings = engine(
            np.ascontiguousarray(rgb[:, :, ::-1]),
            return_word_box=True,
            text_score=score,
            box_thresh=float(config.get("box_thresh", 0.5)),
        )
    lines, words = [], []
    for line_id, record in enumerate(result or []):
        if len(record) < 3:
            raise ValueError("OCR engine returned an unexpected result schema")
        polygon = (np.asarray(record[0], dtype=float) + np.asarray(offset)).tolist()
        line = {
            "text": str(record[1]),
            "confidence": float(record[2]),
            "polygon": polygon,
            "bbox": _bbox(polygon),
            "region": region_id,
            "line": line_id,
        }
        lines.append(line)
        if len(record) >= 6:
            boxes, contents, confidences = record[3:6]
            for box, content, confidence in zip(boxes, contents, confidences, strict=False):
                polygon = (np.asarray(box, dtype=float) + np.asarray(offset)).tolist()
                words.append(
                    {
                        "text": str(content),
                        "confidence": float(confidence),
                        "polygon": polygon,
                        "bbox": _bbox(polygon),
                        "line": line_id,
                        "region": region_id,
                        "granularity": "character" if len(str(content)) == 1 else "word",
                        "position_method": "engine CTC alignment",
                    }
                )
    return lines, words, timings


def image_ocr(table=None, *, config=None, data=None, tables=None):
    """Local ONNX OCR with automatic text regions or explicit raster rectangles."""
    from PIL import Image

    config = dict(config or {})
    path = read_path(config, data)
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    explicit = config.get("regions")
    if explicit is not None and (not isinstance(explicit, list) or not explicit):
        raise ValueError("regions must contain at least one rectangle")
    regions = explicit or [[0, 0, width, height]]
    lines, words, metadata = [], [], []
    for index, value in enumerate(regions):
        left, top, right, bottom = _region(value, width, height)
        new_lines, new_words, timings = _ocr_array(rgb[top:bottom, left:right], config, (left, top), index)
        lines.extend(new_lines)
        words.extend(new_words)
        metadata.append(
            {
                "id": index,
                "bbox": [left, top, right, bottom],
                "timings_seconds": timings,
                "source": "explicit" if explicit else "whole image",
            }
        )
    if not explicit:
        # Detected text-line regions are actual detector polygons, useful for
        # layouts without asserting semantic roles (title/table/figure).
        detected = [
            {"id": i, "bbox": line["bbox"], "polygon": line["polygon"], "source": "text detector"}
            for i, line in enumerate(lines)
        ]
    else:
        detected = metadata
    lines.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))
    return NodeResult(
        table=pd.DataFrame(lines, columns=["text", "confidence", "polygon", "bbox", "region", "line"]),
        data={
            "file_path": str(path),
            "engine": "rapidocr_onnxruntime",
            "coordinate_unit": "pixel",
            "text": "\n".join(line["text"] for line in lines),
            "lines": lines,
            "words": words,
            "regions": detected,
            "requests": metadata,
            "parameters": {
                key: config[key] for key in ("text_score", "box_thresh", "regions") if key in config
            },
        },
        warnings=[] if lines else ["OCR detected no text; no transcription was fabricated."],
    )


def pdf_text(table=None, *, config=None, data=None, tables=None):
    """Page/block order and source coordinates, with actual scanned-page OCR."""
    config = dict(config or {})
    method = config.get("method", "auto")
    if method not in {"native", "ocr", "auto"}:
        raise ValueError("PDF text method must be native, ocr or auto")
    imported = pdf_import(config={**config, "render_all": method == "ocr"}, data=data)
    records, pages, warnings = [], [], []
    for page in imported.data["pages"]:
        use_ocr = method == "ocr" or (method == "auto" and page["requires_ocr"])
        if use_ocr:
            recognized = image_ocr(config={**config, "path": page["image_path"]})
            scale = 72 / page["image_dpi"]
            blocks = [
                {
                    **line,
                    "bbox": [v * scale for v in line["bbox"]],
                    "polygon": [[x * scale, y * scale] for x, y in line["polygon"]],
                }
                for line in recognized.data["lines"]
            ]
            words = [
                {
                    **word,
                    "bbox": [v * scale for v in word["bbox"]],
                    "polygon": [[x * scale, y * scale] for x, y in word["polygon"]],
                }
                for word in recognized.data["words"]
            ]
            warnings.extend(recognized.warnings)
            extracted_text = recognized.data["text"]
        else:
            blocks, words, extracted_text = page["blocks"], [], page["text"]
            if page["requires_ocr"]:
                warnings.append(f"Page {page['page']} has no native text; use method=auto or ocr.")
        selected_method = "ocr" if use_ocr else "native"
        for block in blocks:
            records.append(
                {
                    "page": page["page"],
                    "text": block["text"],
                    "bbox": block["bbox"],
                    "method": selected_method,
                    "confidence": block.get("confidence"),
                    "source_file": imported.data["file_path"],
                }
            )
        pages.append(
            {
                "page": page["page"],
                "text": extracted_text,
                "blocks": blocks,
                "words": words,
                "method": selected_method,
                "width": page["width"],
                "height": page["height"],
            }
        )
    return NodeResult(
        table=pd.DataFrame(records, columns=["page", "text", "bbox", "method", "confidence", "source_file"]),
        data={
            "file_path": imported.data["file_path"],
            "text": "\n\n".join(p["text"] for p in pages),
            "pages": pages,
            "coordinate_unit": "PDF point (1/72 inch)",
            "method": method,
        },
        artifacts=imported.artifacts,
        warnings=warnings,
    )


def _frame_rows(rows, config):
    rows = [list(row) for row in rows if any(value not in (None, "") for value in row)]
    if not rows:
        return pd.DataFrame()
    if config.get("header", True):
        names = [str(value or f"column_{i + 1}").strip() for i, value in enumerate(rows[0])]
        # Duplicate or empty printed headers remain distinguishable, not lost.
        reserved, used, unique = set(names), set(), []
        for name in names:
            candidate, suffix = name, 2
            if candidate in used:
                while candidate in used or candidate in reserved:
                    candidate = f"{name}_{suffix}"
                    suffix += 1
            unique.append(candidate)
            used.add(candidate)
        return pd.DataFrame(rows[1:], columns=unique)
    return pd.DataFrame(rows, columns=[f"column_{i + 1}" for i in range(len(rows[0]))])


def _cluster_positions(positions, distance=3):
    groups = []
    for number in sorted(positions):
        if groups and number - groups[-1][-1] <= distance:
            groups[-1].append(number)
        else:
            groups.append([number])
    return [int(round(float(np.mean(group)))) for group in groups]


def _grid_tables(rgb, config):
    import cv2

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(gray, int(config.get("line_threshold", 180)), 255, cv2.THRESH_BINARY_INV)
    height, width = gray.shape
    horizontal = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, width // 15), 1))
    )
    vertical = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, height // 15)))
    )
    joined = cv2.bitwise_or(horizontal, vertical)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(joined, connectivity=8)
    grids = []
    for label in range(1, count):
        left, top, box_width, box_height, area = map(int, stats[label])
        if box_width < int(config.get("min_table_width", 40)) or box_height < int(
            config.get("min_table_height", 30)
        ):
            continue
        if area < 100:
            continue
        hp = horizontal[top : top + box_height, left : left + box_width]
        vp = vertical[top : top + box_height, left : left + box_width]
        xs = _cluster_positions((np.flatnonzero((vp > 0).sum(axis=0) > box_height * 0.5) + left).tolist())
        ys = _cluster_positions((np.flatnonzero((hp > 0).sum(axis=1) > box_width * 0.5) + top).tolist())
        if len(xs) >= 2 and len(ys) >= 2:
            grids.append((xs, ys))
    return sorted(grids, key=lambda grid: (grid[1][0], grid[0][0]))


def image_tables(table=None, *, config=None, data=None, tables=None):
    """Detect ruled table regions, split grid cells, then OCR actual cell pixels.

    Explicit x_lines/y_lines may be provided when printed grid detection needs
    correction. Coordinates are always returned in the original image frame.
    """
    from PIL import Image

    config = dict(config or {})
    path = read_path(config, data)
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    left, top, right, bottom = _region(config.get("region", [0, 0, width, height]), width, height)
    crop = rgb[top:bottom, left:right]
    if "x_lines" in config or "y_lines" in config:
        if "x_lines" not in config or "y_lines" not in config:
            raise ValueError("explicit grid requires both x_lines and y_lines")
        xs, ys = config["x_lines"], config["y_lines"]
        if len(xs) < 2 or len(ys) < 2 or sorted(set(xs)) != xs or sorted(set(ys)) != ys:
            raise ValueError("grid lines must be strictly increasing coordinate lists")
        if not left <= xs[0] < xs[-1] < right or not top <= ys[0] < ys[-1] < bottom:
            raise ValueError("grid lines must lie within the source region")
        grids = [([x - left for x in xs], [y - top for y in ys])]
    else:
        grids = _grid_tables(crop, config)
    extracted, frames = [], []
    for table_id, (xs, ys) in enumerate(grids):
        rows, cells = [], []
        for row in range(len(ys) - 1):
            values = []
            for column in range(len(xs) - 1):
                x0, x1, y0, y1 = xs[column], xs[column + 1], ys[row], ys[row + 1]
                padding = min(4, max(1, (x1 - x0) // 8), max(1, (y1 - y0) // 8))
                cell_crop = crop[y0 + padding : y1 - padding, x0 + padding : x1 - padding]
                if not cell_crop.size:
                    raise ValueError("grid has cells too small to extract")
                # White border gives the detector a stable context on small cells.
                border = 12
                padded = np.pad(cell_crop, ((border, border), (border, border), (0, 0)), constant_values=255)
                lines, words, _timings = _ocr_array(
                    padded, config, (left + x0 + padding - border, top + y0 + padding - border), table_id
                )
                lines.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))
                text = " ".join(line["text"] for line in lines)
                confidence = float(np.mean([line["confidence"] for line in lines])) if lines else None
                values.append(text)
                cells.append(
                    {
                        "row": row,
                        "column": column,
                        "bbox": [left + x0, top + y0, left + x1, top + y1],
                        "text": text,
                        "confidence": confidence,
                        "lines": lines,
                        "words": words,
                    }
                )
            rows.append(values)
        frame = _frame_rows(rows, config)
        frames.append(frame)
        extracted.append(
            {
                "id": table_id,
                "bbox": [left + xs[0], top + ys[0], left + xs[-1], top + ys[-1]],
                "method": "grid+ocr",
                "rows": rows,
                "cells": cells,
                "columns": frame.columns.tolist(),
                "records": frame.to_dict("records"),
            }
        )
    output = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    return NodeResult(
        table=output,
        data={
            "file_path": str(path),
            "coordinate_unit": "pixel",
            "tables": extracted,
            "table_count": len(extracted),
            "region": [left, top, right, bottom],
        },
        warnings=[]
        if extracted
        else ["No ruled table detected; provide explicit x_lines/y_lines for a grid."],
    )


def pdf_tables(table=None, *, config=None, data=None, tables=None):
    """Native line/aligned-text table extraction with real raster OCR fallback."""
    import fitz

    config = dict(config or {})
    path = read_path(config, data)
    method = config.get("method", "auto")
    if method not in {"lines", "text", "ocr", "auto"}:
        raise ValueError("PDF table method must be lines, text, ocr or auto")
    frames, extracted, artifacts, warnings = [], [], [], []
    with fitz.open(path) as document:
        for number in _pages(document, config):
            page = document[number - 1]
            native = []
            methods = ["lines", "text"] if method == "auto" else [method]
            for strategy in methods:
                if strategy == "ocr":
                    continue
                finder = page.find_tables(
                    strategy=strategy,
                    clip=config.get("region"),
                    min_words_vertical=int(config.get("min_words_vertical", 3)),
                )
                for found in finder.tables:
                    rows = found.extract()
                    frame = _frame_rows(rows, config)
                    if frame.empty:
                        continue
                    cells = [
                        {
                            "row": r,
                            "column": c,
                            "bbox": list(box) if box else None,
                            "text": rows[r][c] if r < len(rows) and c < len(rows[r]) else None,
                        }
                        for r, row in enumerate(found.rows)
                        for c, box in enumerate(row.cells)
                    ]
                    native.append(
                        (
                            frame,
                            {
                                "page": number,
                                "bbox": list(found.bbox),
                                "method": strategy,
                                "rows": rows,
                                "cells": cells,
                                "columns": frame.columns.tolist(),
                                "records": frame.to_dict("records"),
                            },
                        )
                    )
                if native:
                    break
            if native:
                for frame, record in native:
                    frames.append(frame)
                    extracted.append(record)
            elif method in {"ocr", "auto"}:
                dpi = int(config.get("dpi", 150))
                if not 36 <= dpi <= 1200:
                    raise ValueError("dpi must be between 36 and 1200")
                output = _safe_artifact(config, f"table-page-{number}.png", path)
                page.get_pixmap(dpi=dpi, alpha=False).save(output)
                artifacts.append(str(output))
                scale = dpi / 72
                raster_config = {**config, "path": str(output)}
                if config.get("region"):
                    raster_config["region"] = [int(round(v * scale)) for v in config["region"]]
                recognized = image_tables(config=raster_config)
                warnings.extend(recognized.warnings)
                if not recognized.table.empty:
                    frames.append(recognized.table)
                for record in recognized.data["tables"]:
                    record.update(page=number, method="ocr", bbox=[v / scale for v in record["bbox"]])
                    for cell in record["cells"]:
                        cell["bbox"] = [v / scale for v in cell["bbox"]]
                        for collection in (cell["words"], cell["lines"]):
                            for token in collection:
                                token["bbox"] = [v / scale for v in token["bbox"]]
                                token["polygon"] = [[x / scale, y / scale] for x, y in token["polygon"]]
                    extracted.append(record)
    output = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if not extracted:
        warnings.append("No tables extracted; inspect the source or supply an explicit region/grid.")
    return NodeResult(
        table=output,
        data={
            "file_path": str(path),
            "coordinate_unit": "PDF point (1/72 inch)",
            "tables": extracted,
            "table_count": len(extracted),
            "method": method,
        },
        artifacts=artifacts,
        warnings=warnings,
    )


def _axis_calibration(calibration, axis):
    pairs = calibration.get(axis)
    if not isinstance(pairs, list) or np.asarray(pairs).shape != (2, 2):
        raise ValueError(f"calibration.{axis} requires [[pixel0,value0],[pixel1,value1]]")
    values = np.asarray(pairs, dtype=float)
    if not np.isfinite(values).all() or values[0, 0] == values[1, 0] or values[0, 1] == values[1, 1]:
        raise ValueError(f"calibration.{axis} needs two distinct finite pixels and values")
    scale = calibration.get(f"{axis}_scale", "linear")
    if scale not in {"linear", "log"}:
        raise ValueError("axis scale must be linear or log")
    if scale == "log" and np.min(values[:, 1]) <= 0:
        raise ValueError("log calibration values must be positive")
    transformed = np.log10(values[:, 1]) if scale == "log" else values[:, 1]

    def convert(pixels):
        interpolated = transformed[0] + (pixels - values[0, 0]) * (transformed[1] - transformed[0]) / (
            values[1, 0] - values[0, 0]
        )
        return np.power(10.0, interpolated) if scale == "log" else interpolated

    return convert


def chart_digitize(table=None, *, config=None, data=None, tables=None):
    """Digitize a selected curve color using explicit linear/log axis calibration."""
    from PIL import Image

    config = dict(config or {})
    path = read_path(config, data)
    calibration = config.get("calibration")
    if not isinstance(calibration, dict):
        raise ValueError("chart digitization requires explicit x and y calibration")
    x_axis, y_axis = _axis_calibration(calibration, "x"), _axis_calibration(calibration, "y")
    color = np.asarray(config.get("color", []), dtype=float)
    if color.shape != (3,) or not np.isfinite(color).all() or np.any((color < 0) | (color > 255)):
        raise ValueError("provide curve color as [red, green, blue] in the range 0..255")
    tolerance = float(config.get("color_tolerance", 40))
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("color_tolerance must be finite and nonnegative")
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=float)
    height, width = rgb.shape[:2]
    left, top, right, bottom = _region(config.get("region", [0, 0, width, height]), width, height)
    selected = np.linalg.norm(rgb[top:bottom, left:right] - color, axis=2) <= tolerance
    points = []
    step = config.get("pixel_step", 1)
    if type(step) is not int or step < 1:
        raise ValueError("pixel_step must be a positive integer")
    for column in range(0, selected.shape[1], step):
        rows = np.flatnonzero(selected[:, column]) + top
        if len(rows):
            points.append((column + left, float(np.median(rows)), len(rows), float(np.ptp(rows))))
    if not points:
        raise ValueError("no curve pixels match the selected color and region")
    frame = pd.DataFrame(points, columns=["pixel_x", "pixel_y", "pixel_count", "pixel_y_spread"])
    frame.insert(0, "x", x_axis(frame["pixel_x"].to_numpy()))
    frame.insert(1, "y", y_axis(frame["pixel_y"].to_numpy()))
    warnings = []
    if (frame["pixel_y_spread"] > float(config.get("max_thickness", 10))).any():
        warnings.append(
            "Several matching curve pixels occur at the same x; median y may combine curves/markers. "
            "Refine color/region."
        )
    return NodeResult(
        table=frame,
        data={
            "file_path": str(path),
            "calibration": calibration,
            "color": color.tolist(),
            "color_tolerance": tolerance,
            "region": [left, top, right, bottom],
            "aggregation": "median y per pixel column",
            "source_coordinate_unit": "pixel",
            "points": len(frame),
        },
        warnings=warnings,
    )


def _table_png(frame, output):
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=16)
    rows = [list(map(str, frame.columns))] + [
        [str(value) for value in row] for row in frame.itertuples(index=False, name=None)
    ]
    if not len(frame.columns):
        raise ValueError("cannot rasterize a table with no columns")
    measuring = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    widths = [
        max(80, max(int(measuring.textlength(row[column], font=font)) + 24 for row in rows))
        for column in range(len(frame.columns))
    ]
    width, height = sum(widths) + 1, len(rows) * 32 + 1
    if width * height > 50_000_000:
        raise ValueError("table raster exceeds 50 megapixels; select a smaller data range")
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for r, row in enumerate(rows):
        left = 0
        for c, value in enumerate(row):
            draw.rectangle(
                (left, r * 32, left + widths[c], (r + 1) * 32),
                outline="gray",
                fill="#e8edf5" if r == 0 else "white",
            )
            draw.text((left + 8, r * 32 + 6), value, fill="black", font=font)
            left += widths[c]
    image.save(output, format="PNG")


def convert_file(table=None, *, config=None, data=None, tables=None):
    """Parse the source then export CSV, UTF-8 TXT or PNG without touching it."""
    from PIL import Image

    config = dict(config or {})
    target = str(config.get("target", "csv")).lower().lstrip(".")
    if target not in {"csv", "txt", "png"}:
        raise ValueError("target must be csv, txt or png")
    source = read_path(config, data) if table is None else None
    protected_source = source
    if table is not None and (
        config.get("path") or config.get("file_path") or isinstance(data, dict) and data.get("file_path")
    ):
        protected_source = read_path(config, data)
    output = _safe_artifact(config, config.get("filename", f"converted.{target}"), protected_source)
    if output.suffix.lower() != f".{target}":
        raise ValueError("filename extension must match target")
    artifacts, warnings = [], []
    frame, text = require_table(table, min_rows=0) if table is not None else None, None
    parser = "table input"
    if source is not None:
        suffix = source.suffix.lower()
        if suffix == ".pdf":
            if target == "png":
                imported = pdf_import(config={**config, "render_all": True}, data=data)
                return NodeResult(
                    data={
                        "file_path": str(source),
                        "parser": "PDF page rendering",
                        "target": target,
                        "pages": imported.data["pages"],
                    },
                    artifacts=imported.artifacts,
                )
            extracted = (
                pdf_tables(config=config, data=data)
                if target == "csv"
                else pdf_text(config=config, data=data)
            )
            frame, text = extracted.table, extracted.data.get("text")
            warnings.extend(extracted.warnings)
            parser = "PDF table extraction" if target == "csv" else "PDF text extraction"
        elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
            if target == "png":
                with Image.open(source) as image:
                    image.convert("RGB").save(output, format="PNG")
                return NodeResult(
                    data={"file_path": str(source), "target": target, "parser": "Pillow raster decode"},
                    artifacts=[str(output)],
                )
            extracted = (
                image_tables(config=config, data=data)
                if target == "csv"
                else image_ocr(config=config, data=data)
            )
            frame, text = extracted.table, extracted.data.get("text")
            warnings.extend(extracted.warnings)
            parser = "image grid OCR" if target == "csv" else "image text OCR"
        elif suffix in {".xy", ".xye", ".jdx", ".dx", ".jcamp", ".brml", ".raw"}:
            extracted = instrument_import(config=config, data=data)
            frame = extracted.table
            parser = "instrument parser"
        elif suffix == ".txt" and config.get("method") in {"lines", "fixed_width"}:
            extracted = text_import(config=config, data=data)
            frame = extracted.table
            parser = "text parser"
        else:
            frame = table_import(config=config, data=data).table
            parser = "table parser"
    if target == "csv":
        if frame is None or frame.empty:
            raise ValueError(
                "source parser extracted no tabular rows; cannot claim a successful CSV conversion"
            )
        frame.to_csv(output, index=False, encoding="utf-8-sig")
    elif target == "txt":
        if text is None:
            text = frame.to_csv(index=False, sep="\t")
        output.write_text(text, encoding="utf-8")
    else:
        _table_png(frame, output)
    artifacts.append(str(output))
    return NodeResult(
        table=frame.copy(deep=True) if frame is not None else None,
        data={
            "file_path": str(source) if source else None,
            "target": target,
            "parser": parser,
            "rows": len(frame) if frame is not None else None,
            "output_path": str(output),
        },
        artifacts=artifacts,
        warnings=warnings,
    )


CATALOG = [
    {
        "key": f"extract.{key}",
        "title": title,
        "function": f"materials_quality.science.extract_nodes:{key}",
        "category": "内容提取",
        "requirement": title,
        "table_input": key == "convert_file",
        "data_input": True,
        "tables_input": False,
        "default_config": defaults,
    }
    for key, title, defaults in [
        ("pdf_text", "PDF 文本提取", {"path": "", "method": "auto"}),
        ("pdf_tables", "PDF 表格提取", {"path": "", "method": "auto"}),
        ("image_ocr", "图片文字识别", {"path": "", "text_score": 0.5}),
        ("image_tables", "图片表格提取", {"path": "", "header": True}),
        ("chart_digitize", "图表数据提取", {"path": "", "calibration": {}, "color": [255, 0, 0]}),
        ("convert_file", "文件格式转换", {"path": "", "target": "csv"}),
    ]
]
