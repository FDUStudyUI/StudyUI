"""Read-only scientific file, database and paginated API ingestion.

Header and range indices are relative to the selected rectangle; page numbers
are one-based. Engines are imported only when the corresponding node is run.
"""

import csv
import importlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

import numpy as np
import pandas as pd

from materials_quality.science.contracts import NodeResult, artifact_path, read_path, require_table


def _decode(path, config):
    raw = path.read_bytes()
    encoding = config.get("encoding", "auto")
    if encoding != "auto":
        return raw.decode(encoding), encoding
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for candidate in ("utf-8", "gb18030"):
        try:
            return raw.decode(candidate), candidate
        except UnicodeDecodeError:
            pass
    try:
        from charset_normalizer import from_bytes

        match = from_bytes(raw).best()
        if match is not None:
            return str(match), match.encoding
    except ImportError:
        pass
    raise ValueError("cannot detect text encoding; provide config.encoding explicitly")


def _delimiter(text, config):
    delimiter = config.get("delimiter", "auto")
    if delimiter != "auto":
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            raise ValueError("delimiter must be one character or auto")
        return delimiter
    try:
        return csv.Sniffer().sniff(text[:65536], delimiters=",;\t|\u3000").delimiter
    except csv.Error:
        # A one-column file is valid, but inconsistent multi-column rows are not.
        return ","


def _rectangle(frame, selection):
    if not selection:
        return frame
    match = re.fullmatch(r"([A-Za-z]+)([1-9]\d*):([A-Za-z]+)([1-9]\d*)", str(selection))
    if not match:
        raise ValueError("range must be an Excel-style rectangle such as A2:C20")

    def column(letters):
        result = 0
        for letter in letters.upper():
            result = result * 26 + ord(letter) - ord("A") + 1
        return result - 1

    c0, r0, c1, r1 = column(match[1]), int(match[2]) - 1, column(match[3]), int(match[4])
    if c1 < c0 or r1 <= r0 or c1 >= frame.shape[1] or r1 > frame.shape[0]:
        raise ValueError("range is reversed or extends beyond the input data")
    return frame.iloc[r0:r1, c0 : c1 + 1].copy()


def _preserves_integer_precision(original, converted):
    """Numeric inference must not round integer source cells through a float."""
    for before, after in zip(original, converted, strict=True):
        integer = (
            isinstance(before, (int, np.integer))
            and not isinstance(before, (bool, np.bool_))
            or isinstance(before, str)
            and re.fullmatch(r"[+-]?\d+", before.strip())
        )
        if integer:
            try:
                if int(after) != int(before):
                    return False
            except (TypeError, ValueError, OverflowError):
                return False
    return True


def _schema_missing(value):
    return (
        value is None
        or value is pd.NA
        or value is pd.NaT
        or isinstance(value, (float, np.floating))
        and np.isnan(value)
        or isinstance(value, str)
        and not value.strip()
    )


def _integer_column(original, target):
    """Validate exact decimal integers and target bounds before constructing a dtype."""
    limits = np.iinfo(getattr(target, "numpy_dtype", target))
    values = []
    for value in original:
        if _schema_missing(value):
            values.append(pd.NA)
            continue
        if isinstance(value, (bool, np.bool_)):
            raise ValueError("integer dtype requires numeric values, not booleans")
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError("integer dtype requires finite exact integers") from exc
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError("integer dtype requires finite exact integers; fractions are rejected")
        if not limits.min <= number <= limits.max:
            raise ValueError("integer value lies outside the requested dtype range")
        values.append(int(number))
    # A list of exact Python ints plus pd.NA avoids any float intermediate.
    return pd.Series(values, index=original.index, dtype=target)


def _boolean_column(original, target):
    """Boolean schema accepts real booleans and canonical true/false words only."""
    values = []
    for value in original:
        if isinstance(value, (bool, np.bool_)):
            values.append(bool(value))
        elif isinstance(value, str) and value.strip().casefold() in {"true", "false"}:
            values.append(value.strip().casefold() == "true")
        elif not isinstance(value, str) and _schema_missing(value) and isinstance(target, pd.BooleanDtype):
            values.append(pd.NA)
        else:
            raise ValueError("boolean dtype requires booleans or canonical true/false strings")
    return pd.Series(values, index=original.index, dtype=target)


def _headers(frame, config):
    header = config.get("header", 0)
    if header is None:
        names = config.get("names", [f"column_{i + 1}" for i in range(frame.shape[1])])
        result = frame.copy()
    else:
        if type(header) is not int or not 0 <= header < len(frame):
            raise ValueError("header must be a zero-based row within the selected range or null")
        names = frame.iloc[header].tolist()
        names = [str(value) if pd.notna(value) else f"column_{i + 1}" for i, value in enumerate(names)]
        result = frame.iloc[header + 1 :].copy()
    if len(names) != result.shape[1] or len(set(names)) != len(names):
        raise ValueError("column names must be unique and match the selected column count")
    result.columns = names
    result = result.reset_index(drop=True)
    identifiers = config.get("id_columns", [])
    requested = config.get("dtype", {})
    if (
        not isinstance(identifiers, list)
        or any(not isinstance(c, str) for c in identifiers)
        or len(set(identifiers)) != len(identifiers)
        or set(identifiers) - set(names)
    ):
        raise ValueError("id_columns must be a unique list of existing column names")
    if (
        not isinstance(requested, dict)
        or requested.keys() - set(names)
        or any(not isinstance(dtype, str) for dtype in requested.values())
    ):
        raise ValueError("dtype must map existing column names to explicit dtype strings")
    text_types = {"str", "string", "object"}
    schema = {}
    for name in result.columns:
        original = result[name]
        dtype = requested.get(name)
        if name in identifiers:
            if dtype is not None and dtype not in text_types:
                raise ValueError(f"identifier column {name!r} requires a text dtype")
            result[name] = original.astype("string")
            conversion = "explicit-identifier"
        elif dtype is not None:
            try:
                target = pd.api.types.pandas_dtype("string" if dtype == "str" else dtype)
                kind = getattr(target, "kind", None)
                if kind in {"i", "u"}:
                    converted = _integer_column(original, target)
                elif kind == "b":
                    converted = _boolean_column(original, target)
                else:
                    values = pd.to_numeric(original, errors="raise") if kind in {"f", "c"} else original
                    converted = values.astype(target)
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError(f"cannot apply dtype {dtype!r} to column {name!r}") from exc
            if not _preserves_integer_precision(original, converted):
                raise ValueError(f"dtype {dtype!r} loses exact integer precision in column {name!r}")
            result[name] = converted
            conversion = "explicit-dtype"
        elif original.map(
            lambda value: isinstance(value, str) and re.fullmatch(r"[+-]?0\d+", value.strip()) is not None
        ).any():
            conversion = "preserved-leading-zero"
        else:
            try:
                converted = pd.to_numeric(original, errors="raise")
            except (ValueError, TypeError, OverflowError):
                conversion = "preserved-source-cells"
            else:
                if _preserves_integer_precision(original, converted):
                    result[name] = converted
                    conversion = "inferred-numeric"
                else:
                    conversion = "preserved-integer-precision"
        schema[name] = {
            "dtype": str(result[name].dtype),
            "conversion": conversion,
            "role": "identifier" if name in identifiers else "data",
            "requested_dtype": dtype,
        }
    return result, schema


def table_import(table=None, *, config=None, data=None, tables=None):
    """CSV/TSV or Excel sheet, zero-based header and A1 rectangle selection."""
    config = dict(config or {})
    from materials_quality.common import json_value

    path = read_path(config, data)
    metadata = {"file_path": str(path), "range": config.get("range"), "header": config.get("header", 0)}
    if path.suffix.lower() in {".xlsx", ".xls", ".xlsm", ".ods"}:
        sheet = config.get("sheet", 0)
        if not isinstance(sheet, (str, int)):
            raise ValueError("sheet must be a sheet name or zero-based index")
        # Preserve actual cell types and literal NA/N/A strings before selecting
        # the header. Pandas' default NA/type inference can destroy identifiers.
        with pd.ExcelFile(path) as workbook:
            metadata["sheet_names"] = list(workbook.sheet_names)
            frame = workbook.parse(sheet_name=sheet, header=None, dtype=object, keep_default_na=False)
        metadata["sheet"] = sheet
    else:
        text, encoding = _decode(path, config)
        delimiter = _delimiter(text, config)
        # csv.reader handles ragged note rows without silently shifting columns.
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        frame = pd.DataFrame(rows)
        metadata.update(encoding=encoding, delimiter=delimiter)
    frame, schema = _headers(_rectangle(frame, config.get("range")), config)
    return NodeResult(
        table=frame,
        data={
            **metadata,
            "rows": len(frame),
            "columns": frame.columns.tolist(),
            "source_rows": config.get("range") or "entire file",
            "schema": schema,
            "preview": json_value(frame.head(20).to_dict("records")),
            "preview_rows": min(20, len(frame)),
        },
    )


def text_import(table=None, *, config=None, data=None, tables=None):
    """Text line, delimited and explicit fixed-width parsing."""
    config = dict(config or {})
    path = read_path(config, data)
    text, encoding = _decode(path, config)
    method = config.get("method", "lines")
    if method == "delimited":
        return table_import(config={**config, "path": str(path)}, data=data)
    if method == "lines":
        lines = text.splitlines()
        frame = pd.DataFrame({"line_number": range(1, len(lines) + 1), "text": lines})
    elif method == "fixed_width":
        widths = config.get("widths")
        if not isinstance(widths, list) or not widths or any(type(w) is not int or w <= 0 for w in widths):
            raise ValueError("fixed_width requires a list of positive widths")
        names = config.get("names", [f"column_{i + 1}" for i in range(len(widths))])
        if len(names) != len(widths) or len(set(names)) != len(names):
            raise ValueError("names must match widths and be unique")
        frame = pd.read_fwf(
            io.StringIO(text),
            widths=widths,
            names=names,
            skiprows=config.get("skiprows", 0),
            dtype=config.get("dtype"),
        )
    else:
        raise ValueError("method must be lines, delimited or fixed_width")
    return NodeResult(
        table=frame,
        data={
            "file_path": str(path),
            "encoding": encoding,
            "method": method,
            "line_count": len(text.splitlines()),
            "parameters": config,
        },
    )


def _pages(document, config):
    pages = config.get("pages", list(range(1, len(document) + 1)))
    if (
        not isinstance(pages, list)
        or not pages
        or any(type(p) is not int or not 1 <= p <= len(document) for p in pages)
    ):
        raise ValueError("pages must be a nonempty list of valid one-based page numbers")
    return pages


def _safe_artifact(config, filename, source=None):
    output = artifact_path(config, filename)
    if source is not None and output.resolve() == Path(source).resolve():
        output = artifact_path({**config, "overwrite": False}, filename)
    return output


def pdf_import(table=None, *, config=None, data=None, tables=None):
    """Extract native PDF blocks and render pages without native text for OCR."""
    import fitz

    config = dict(config or {})
    path = read_path(config, data)
    dpi = int(config.get("dpi", 150))
    if not 36 <= dpi <= 1200:
        raise ValueError("dpi must be between 36 and 1200")
    pages, artifacts = [], []
    with fitz.open(path) as document:
        metadata = dict(document.metadata)
        for number in _pages(document, config):
            page = document[number - 1]
            blocks = [
                {"bbox": list(block[:4]), "text": block[4], "block_number": block[5]}
                for block in page.get_text("blocks", sort=True)
                if block[6] == 0
            ]
            text = page.get_text("text", sort=True)
            record = {
                "page": number,
                "width": page.rect.width,
                "height": page.rect.height,
                "coordinate_unit": "PDF point (1/72 inch)",
                "text": text,
                "blocks": blocks,
                "requires_ocr": not bool(text.strip()),
            }
            if record["requires_ocr"] or config.get("render_all", False):
                output = _safe_artifact(config, f"page-{number}.png", path)
                page.get_pixmap(dpi=dpi, alpha=False).save(output)
                record.update(image_path=str(output), image_dpi=dpi)
                artifacts.append(str(output))
            pages.append(record)
    return NodeResult(
        data={"file_path": str(path), "pages": pages, "metadata": metadata}, artifacts=artifacts
    )


def image_import(table=None, *, config=None, data=None, tables=None):
    """Inspect actual raster format, dimensions, resolution and EXIF metadata."""
    from PIL import ExifTags, Image

    path = read_path(config or {}, data)
    with Image.open(path) as image:
        metadata = {str(ExifTags.TAGS.get(key, key)): str(value) for key, value in image.getexif().items()}
        info = {
            str(key): value if isinstance(value, (str, int, float, tuple, list)) else repr(value)
            for key, value in image.info.items()
        }
        result = {
            "file_path": str(path),
            "format": image.format,
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "dpi": image.info.get("dpi"),
            "frames": getattr(image, "n_frames", 1),
            "metadata": metadata,
            "info": info,
        }
    return NodeResult(data=result)


def _jcamp(path, config):
    text, encoding = _decode(path, config)
    metadata, lines, active = {}, [], False
    for line in text.splitlines():
        line = line.split("$$", 1)[0].strip()
        if line.startswith("##") and "=" in line:
            key, value = line[2:].split("=", 1)
            key = key.strip().upper().replace(" ", "")
            metadata[key] = value.strip()
            active = key in {"XYDATA", "XYPOINTS", "PEAKTABLE"}
        elif active and line:
            lines.append(line)
    if not lines:
        raise ValueError("JCAMP has no supported XYDATA/XYPOINTS/PEAKTABLE section")
    mode = metadata.get("XYDATA", metadata.get("XYPOINTS", metadata.get("PEAKTABLE", ""))).replace(" ", "")
    xf, yf = float(metadata.get("XFACTOR", 1)), float(metadata.get("YFACTOR", 1))
    points = []
    if "X++" in mode.upper():
        try:
            count = int(metadata["NPOINTS"])
            first, last = float(metadata["FIRSTX"]), float(metadata["LASTX"])
            step = float(metadata.get("DELTAX", (last - first) / (count - 1)))
        except (KeyError, ZeroDivisionError) as exc:
            raise ValueError(
                "JCAMP incremental XYDATA requires NPOINTS, FIRSTX, LASTX or explicit spacing"
            ) from exc
        for line in lines:
            tokens = re.split(r"[,;\s]+", line)
            try:
                numbers = [float(token) for token in tokens if token]
            except ValueError as exc:
                raise ValueError("compressed JCAMP requires an explicit converter/plugin") from exc
            points.extend((numbers[0] * xf + i * step, value * yf) for i, value in enumerate(numbers[1:]))
        if len(points) != count:
            raise ValueError("JCAMP NPOINTS does not match decoded data")
    else:
        for line in lines:
            try:
                numbers = [float(token) for token in re.split(r"[,;\s]+", line) if token]
            except ValueError as exc:
                raise ValueError("compressed JCAMP requires an explicit converter/plugin") from exc
            if len(numbers) % 2:
                raise ValueError("JCAMP XY pairs must contain an even number of values")
            points.extend((numbers[i] * xf, numbers[i + 1] * yf) for i in range(0, len(numbers), 2))
    return pd.DataFrame(points, columns=["x", "y"]), {"jcamp_metadata": metadata, "encoding": encoding}


def instrument_import(table=None, *, config=None, data=None, tables=None):
    """XY, uncompressed JCAMP and BRML; explicit plugin/command for vendor binaries."""
    config = dict(config or {})
    candidate = config.get("path") or config.get("file_path") or (data or {}).get("file_path")
    selected_format = config.get("format") or (
        Path(candidate).suffix.lower().lstrip(".") if candidate else ""
    )
    if selected_format in {"h5", "hdf", "hdf5", "nc", "nc4", "netcdf", "zarr"} and not (
        config.get("plugin") or config.get("converter")
    ):
        from .instrument_arrays import import_array

        return import_array(candidate, config)
    if config.get("mode", "read") != "read":
        raise ValueError("browse mode is available for HDF5, NetCDF and local Zarr arrays")
    path = read_path(config, data)
    method = config.get("format", path.suffix.lower().lstrip("."))
    extra, artifacts = {}, []
    if config.get("plugin"):
        target = str(config["plugin"])
        if ":" not in target:
            raise ValueError("plugin must be an importable module:function")
        module, function = target.rsplit(":", 1)
        with tempfile.TemporaryDirectory(prefix="studyui-instrument-") as staging:
            isolated = Path(staging) / path.name
            shutil.copy2(path, isolated)
            plugin_config = {**config, "path": str(isolated), "file_path": str(isolated)}
            converted = getattr(importlib.import_module(module), function)(isolated, plugin_config)
            if isinstance(converted, pd.DataFrame):
                frame = require_table(converted)
            elif isinstance(converted, (str, Path)):
                converted_path = Path(converted).resolve()
                if converted_path in {path, isolated.resolve()}:
                    raise ValueError("plugin must preserve input and return a separate converted file")
                frame = table_import(config={**config, "path": str(converted_path)}).table
                output = _safe_artifact(config, "instrument-converted.csv", path)
                frame.to_csv(output, index=False, encoding="utf-8-sig")
                artifacts.append(str(output))
            else:
                raise ValueError("instrument plugin must return a DataFrame or converted file path")
        extra["plugin"] = target
    elif config.get("converter"):
        command = config["converter"]
        if not isinstance(command, list) or not command or not all(isinstance(s, str) for s in command):
            raise ValueError("converter must be a command token list, without shell syntax")
        if not any("{input}" in token for token in command) or not any(
            "{output}" in token for token in command
        ):
            raise ValueError("converter command requires {input} and {output} placeholders")
        output = _safe_artifact(config, "instrument-converted.csv", path)
        with tempfile.TemporaryDirectory(prefix="studyui-instrument-") as staging:
            isolated = Path(staging) / path.name
            shutil.copy2(path, isolated)
            staged_output = Path(staging) / "new-converted-output.csv"
            tokens = [
                s.replace("{input}", str(isolated)).replace("{output}", str(staged_output)) for s in command
            ]
            try:
                subprocess.run(
                    tokens,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=float(config.get("timeout", 60)),
                    shell=False,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                raise ValueError(
                    "instrument converter failed; check executable, arguments and output format"
                ) from exc
            if not staged_output.is_file():
                raise ValueError("instrument converter did not create a new output file")
            frame = table_import(config={**config, "path": str(staged_output), "header": 0}).table
            frame.to_csv(output, index=False, encoding="utf-8-sig")
        artifacts.append(str(output))
        extra["converter"] = tokens
    elif method in {"jdx", "dx", "jcamp"}:
        frame, extra = _jcamp(path, config)
    elif method == "brml":
        if "x_index" not in config or "y_index" not in config:
            raise ValueError(
                "BRML requires explicit x_index/y_index from instrument schema; channel order varies"
            )
        xi, yi = config["x_index"], config["y_index"]
        if any(type(value) is not int or value < 0 for value in (xi, yi)):
            raise ValueError("BRML x_index/y_index must be nonnegative integers")
        rows, members = [], []
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if not re.search(r"RawData[^/]*\.xml$", member, re.I):
                    continue
                root = ElementTree.fromstring(archive.read(member))
                for datum in root.iter():
                    if datum.tag.rsplit("}", 1)[-1] == "Datum" and datum.text:
                        values = datum.text.split(",")
                        if max(xi, yi) >= len(values):
                            raise ValueError("BRML Datum has fewer columns than configured channel indices")
                        rows.append((float(values[xi]), float(values[yi]), member))
                members.append(member)
        if not rows:
            raise ValueError("BRML archive contains no RawData Datum points")
        frame = pd.DataFrame(rows, columns=["x", "y", "source_member"])
        extra.update(xml_members=members, x_index=xi, y_index=yi)
    elif method in {"xy", "xye", "csv", "txt", "dat"}:
        text, encoding = _decode(path, config)
        rows = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", ";"))
        ]
        try:
            values = [[float(value) for value in re.split(r"[,;\s]+", line)] for line in rows]
        except ValueError as exc:
            raise ValueError(
                "numeric XY files must contain numeric rows; use table_import for text headers"
            ) from exc
        if not values or min(map(len, values)) < 2 or len(set(map(len, values))) != 1:
            raise ValueError("XY files require consistent rows containing at least x and y")
        frame = pd.DataFrame(
            values, columns=["x", "y"] + [f"channel_{i}" for i in range(3, len(values[0]) + 1)]
        )
        extra["encoding"] = encoding
    else:
        raise ValueError(f"unsupported instrument format {method!r}; supply an explicit converter or plugin")
    numeric = frame.select_dtypes(include="number").to_numpy()
    if numeric.size and not np.isfinite(numeric).all():
        raise ValueError("instrument data contains non-finite numeric values")
    return NodeResult(
        table=frame.copy(deep=True),
        data={"file_path": str(path), "format": method, "rows": len(frame), **extra},
        artifacts=artifacts,
    )


def _field(value, path):
    if not path:
        return value
    for piece in path.split("."):
        if isinstance(value, dict):
            if piece not in value:
                raise ValueError(f"response is missing field path: {path}")
            value = value[piece]
        elif isinstance(value, list) and piece.isdigit() and int(piece) < len(value):
            value = value[int(piece)]
        else:
            raise ValueError(f"response is missing field path: {path}")
    return value


def _origin(url):
    parsed = urlparse(url)
    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


class _OriginRedirectHandler(HTTPRedirectHandler):
    def __init__(self, origin):
        super().__init__()
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urljoin(req.full_url, newurl)
        if _origin(destination) != self.origin:
            raise ValueError("REST redirect changed origin; no redirected request was sent")
        return super().redirect_request(req, fp, code, msg, headers, destination)


def _rest(config):
    url = config.get("url", "")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("REST url must be http or https")
    if parsed.username or parsed.password:
        raise ValueError("REST credentials belong in configured headers, not the URL")
    origin = _origin(url)
    opener = build_opener(_OriginRedirectHandler(origin))
    pagination = config.get("pagination", {})
    mode = pagination.get("mode", "page")
    if mode not in {"page", "offset", "next", "none"}:
        raise ValueError("pagination mode must be page, offset, next or none")
    limit = int(pagination.get("max_pages", 100))
    size = int(pagination.get("page_size", 100))
    if limit <= 0 or size <= 0:
        raise ValueError("pagination max_pages and page_size must be positive")
    records, pages, seen = [], 0, set()
    exhausted = False
    for index in range(limit):
        params = dict(parse_qsl(urlparse(url).query))
        params.update(config.get("params", {}))
        if mode == "page":
            params[pagination.get("page_param", "page")] = pagination.get("start", 1) + index
            params[pagination.get("size_param", "page_size")] = size
        elif mode == "offset":
            params[pagination.get("offset_param", "offset")] = pagination.get("start", 0) + index * size
            params[pagination.get("size_param", "limit")] = size
        request_url = urlunparse(urlparse(url)._replace(query=urlencode(params)))
        if request_url in seen:
            raise ValueError("REST pagination repeats a URL; check next link configuration")
        seen.add(request_url)
        request = Request(request_url, headers={"Accept": "application/json", **config.get("headers", {})})
        with opener.open(request, timeout=float(config.get("timeout", 20))) as response:
            # Guard cross-origin redirects as well as configured next-page links.
            if _origin(response.url) != origin:
                raise ValueError("REST redirect changed origin")
            payload = json.load(response)
        batch = _field(payload, config.get("records_path", ""))
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise ValueError("records_path must resolve to a list of objects")
        records.extend(batch)
        pages += 1
        if mode == "none" or not batch:
            exhausted = True
            break
        if mode == "next":
            next_link = _field(payload, pagination.get("next_path", "next"))
            if not next_link:
                exhausted = True
                break
            url = urljoin(url, str(next_link))
            if _origin(url) != origin:
                raise ValueError("REST next link changed origin")
    fields = config.get("fields")
    frame = (
        pd.DataFrame([{field: _field(record, field) for field in fields} for record in records])
        if fields
        else pd.json_normalize(records)
    )
    return NodeResult(
        table=frame,
        data={
            "url": config.get("url"),
            "pages_read": pages,
            "rows": len(frame),
            "pagination": pagination,
            "complete": exhausted,
        },
        warnings=[] if exhausted else ["Pagination reached max_pages; result is incomplete."],
    )


def _query(config):
    query = config.get("query", "")
    if not isinstance(query, str) or not re.match(r"^\s*(SELECT|WITH)\b", query, flags=re.I):
        raise ValueError("read-only queries must start with SELECT or WITH")
    if ";" in query.rstrip().rstrip(";"):
        raise ValueError("read-only query must contain a single SQL statement")
    # Fail closed for common writable CTEs, extension loads and file exports.
    forbidden = (
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|REPLACE|VACUUM|PRAGMA|COPY|INTO|"
        r"load_extension)\b"
    )
    if re.search(forbidden, query, flags=re.I):
        raise ValueError("read-only SELECT query contains a forbidden write or extension operation")
    return query


def database_import(table=None, *, config=None, data=None, tables=None):
    """Read-only SQLite/SQLAlchemy SELECT or configurable REST pagination."""
    config = dict(config or {})
    method = config.get("method", "sqlite")
    if method == "rest":
        return _rest(config)
    query = _query(config)
    if method == "sqlite":
        path = read_path(config, data)
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            frame = pd.read_sql_query(query, connection, params=config.get("parameters", {}))
        source = str(path)
    elif method == "sqlalchemy":
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url

        url = make_url(config.get("url", ""))
        if url.get_backend_name() == "sqlite":
            if not url.database or url.database == ":memory:":
                raise ValueError("read-only SQLAlchemy SQLite requires an existing database file")
            path = Path(url.database).resolve()
            if not path.is_file():
                raise ValueError("read-only database does not exist")
            url = url.set(
                database="file:" + path.as_posix(), query={**url.query, "mode": "ro", "uri": "true"}
            )
        engine = create_engine(url)
        try:
            with engine.connect() as connection, connection.begin():
                dialect = engine.dialect.name
                if dialect == "sqlite":
                    connection.exec_driver_sql("PRAGMA query_only=ON")
                elif dialect in {"postgresql", "mysql", "mariadb"}:
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                else:
                    raise ValueError(
                        f"read-only transactions unsupported for dialect {dialect}; use a read-only connector"
                    )
                frame = pd.read_sql_query(text(query), connection, params=config.get("parameters", {}))
        finally:
            engine.dispose()
        source = url.render_as_string(hide_password=True)
    else:
        raise ValueError("database method must be sqlite, sqlalchemy or rest")
    fields = config.get("fields")
    if fields:
        if not isinstance(fields, list) or any(field not in frame for field in fields):
            raise ValueError("fields must be a list of existing result columns")
        frame = frame.loc[:, fields].copy()
    return NodeResult(
        table=frame,
        data={
            "source": source,
            "method": method,
            "query": query,
            "parameters": config.get("parameters", {}),
            "rows": len(frame),
            "read_only": True,
        },
    )


CATALOG = [
    {
        "key": f"io.{key}",
        "title": title,
        "function": f"materials_quality.science.io_nodes:{key}",
        "category": "数据接入",
        "requirement": title,
        "table_input": False,
        "data_input": True,
        "tables_input": False,
        "default_config": defaults,
    }
    for key, title, defaults in [
        ("table_import", "表格文件导入", {"path": "", "header": 0, "delimiter": "auto"}),
        ("text_import", "文本文件导入", {"path": "", "method": "lines"}),
        ("pdf_import", "PDF 文件导入", {"path": "", "dpi": 150}),
        ("image_import", "图片文件导入", {"path": ""}),
        ("instrument_import", "仪器文件导入", {"path": "", "mode": "read"}),
        ("database_import", "数据库接入", {"method": "sqlite", "path": "", "query": "SELECT * FROM samples"}),
    ]
]
