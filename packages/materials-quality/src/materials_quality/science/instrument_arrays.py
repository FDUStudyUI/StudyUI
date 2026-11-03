"""Read-only local HDF5, NetCDF and Zarr array inspection and explicit mapping.

Tree browsing reads bounded metadata, not signal arrays. Array/object/pickle
codecs, HDF5 soft/external links, virtual/external datasets and Zarr symlinks
are not followed. This is a bounded local reader, not a sandbox for native
scientific-library vulnerabilities. Zarr v3 metadata can be browsed; reading
v3 requires a compatible installed Zarr engine (Python >=3.11).
"""

import importlib
import json
import math
import os
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from materials_quality.common import json_value

from .contracts import NodeResult

FORMATS = {
    "h5": "hdf5",
    "hdf": "hdf5",
    "hdf5": "hdf5",
    "nc": "netcdf",
    "nc4": "netcdf",
    "netcdf": "netcdf",
    "zarr": "zarr",
}
DEFAULT_LIMITS = {
    "max_bytes": 256 * 1024**2,
    "max_rows": 2_000_000,
    "max_nodes": 2000,
    "max_depth": 16,
    "max_metadata_bytes": 1024**2,
    "max_file_bytes": 1024**3,
    "max_store_entries": 100_000,
}
TREE_COLUMNS = ["path", "kind", "shape", "dtype", "attrs", "readable", "blocked_reason", "chunks"]
SAFE_CODECS = {
    "blosc",
    "zlib",
    "gzip",
    "bz2",
    "lzma",
    "zstd",
    "lz4",
    "crc32",
    "adler32",
    "fletcher32",
    "astype",
    "delta",
    "shuffle",
    "bitround",
    "quantize",
    "fixedscaleoffset",
    "packbits",
    "bytes",
    "endian",
    "crc32c",
    "transpose",
    "sharding_indexed",
}


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise ValueError(
            f"This array format requires an optional dependency: python -m pip install {name}"
        ) from exc


def _limits(config):
    result = {}
    for key, default in DEFAULT_LIMITS.items():
        value = config.get(key, default)
        if type(value) is not int or value < 1:
            raise ValueError(f"{key} must be a positive integer")
        result[key] = value
    return result


def _source(path, config):
    if not isinstance(path, (str, Path)) or not str(path).strip() or "://" in str(path):
        raise ValueError("provide a local array file or Zarr directory path; remote stores are not opened")
    location = Path(path).expanduser()
    if location.is_symlink():
        raise ValueError("array source symlinks are blocked; select the actual local source")
    location = location.resolve()
    if not location.exists():
        raise ValueError(f"input array path does not exist: {location}")
    selected = config.get("format") or location.suffix.lower().lstrip(".")
    if selected not in FORMATS:
        raise ValueError("select format hdf5, netcdf or zarr for this local source")
    kind = FORMATS[selected]
    if (kind == "zarr") != location.is_dir():
        raise ValueError("Zarr requires a local directory; HDF5/NetCDF require a local file")
    limits = _limits(config)
    if location.is_file() and location.stat().st_size > limits["max_file_bytes"]:
        raise ValueError("array source exceeds max_file_bytes; export a smaller local subset")
    return location, kind, limits


def _path(value):
    if not isinstance(value, str) or not value.strip() or "\\" in value or "\x00" in value:
        raise ValueError("dataset path must be a nonempty slash-separated local tree path")
    parts = value.strip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("dataset paths cannot contain empty, dot or parent path components")
    return "/" + "/".join(parts)


def _small_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[:4096]
    if isinstance(value, str):
        return value[:4096]
    if isinstance(value, np.ndarray):
        if value.size > 256:
            return {"omitted": True, "shape": list(value.shape), "dtype": str(value.dtype)}
        return [_small_value(v) for v in value.tolist()] if value.ndim else _small_value(value.item())
    if isinstance(value, dict):
        return {str(k): _small_value(v) for k, v in list(value.items())[:64]}
    if isinstance(value, (list, tuple)):
        return [_small_value(v) for v in value[:256]]
    return json_value(value)


def _attrs(obj, backend, limits):
    result = {}
    keys = obj.ncattrs() if backend == "netcdf" else obj.attrs
    for i, key in enumerate(keys):
        if i >= 64:
            result["_truncated"] = "additional attributes omitted"
            break
        if backend == "hdf5":
            attribute = obj.attrs.get_id(key)
            if (
                math.prod(attribute.shape) > 256
                or attribute.get_storage_size() > limits["max_metadata_bytes"]
            ):
                result[str(key)] = {"omitted": True, "shape": list(attribute.shape)}
                continue
        value = obj.getncattr(key) if backend == "netcdf" else obj.attrs[key]
        result[str(key)] = _small_value(value)
    return result


def _entry(path, obj, backend, limits, reason=None):
    shape = getattr(obj, "shape", None)
    dtype = np.dtype(obj.dtype) if shape is not None else None
    if dtype is not None and (dtype.hasobject or dtype.fields is not None or dtype.kind not in "fiuSU"):
        reason = reason or "object, variable-length, compound or non-real dtype is blocked"
    chunks = getattr(obj, "chunks", None)
    if backend == "netcdf" and shape is not None:
        chunks = obj.chunking()
        chunks = None if chunks == "contiguous" else chunks
    return {
        "path": path,
        "kind": "dataset" if shape is not None else "group",
        "shape": list(shape) if shape is not None else None,
        "dtype": str(dtype) if dtype else None,
        "attrs": _attrs(obj, backend, limits),
        "readable": shape is not None and reason is None,
        "blocked_reason": reason,
        "chunks": list(chunks) if chunks else None,
    }


def _hdf_inventory(root, library, limits):
    rows, datasets, seen = [], {}, set()

    def visit(group, path, depth):
        if depth > limits["max_depth"]:
            raise ValueError("HDF5 tree exceeds max_depth")
        if len(rows) >= limits["max_nodes"]:
            raise ValueError("HDF5 tree exceeds max_nodes")
        rows.append(_entry(path, group, "hdf5", limits))
        identity = hash(group.id)
        if identity in seen:
            rows[-1]["blocked_reason"] = "hard-link group alias or cycle not traversed"
            return
        seen.add(identity)
        for name in group:
            if len(rows) >= limits["max_nodes"]:
                raise ValueError("HDF5 tree exceeds max_nodes")
            key = path.rstrip("/") + "/" + name
            link = group.get(name, getlink=True)
            if not isinstance(link, library.HardLink):
                rows.append(
                    {
                        "path": key,
                        "kind": "link",
                        "shape": None,
                        "dtype": None,
                        "attrs": {},
                        "readable": False,
                        "blocked_reason": "soft/external link blocked",
                        "chunks": None,
                    }
                )
                continue
            obj = group[name]
            if isinstance(obj, library.Group):
                visit(obj, key, depth + 1)
            else:
                reason = (
                    "virtual/external dataset storage blocked" if obj.is_virtual or obj.external else None
                )
                rows.append(_entry(key, obj, "hdf5", limits, reason))
                datasets[key] = obj

    visit(root, "/", 0)
    return rows, datasets


def _netcdf_inventory(root, limits):
    rows, datasets = [], {}

    def visit(group, path, depth):
        if depth > limits["max_depth"] or len(rows) >= limits["max_nodes"]:
            raise ValueError("NetCDF tree exceeds max_depth/max_nodes")
        rows.append(_entry(path, group, "netcdf", limits))
        for name, obj in group.variables.items():
            if len(rows) >= limits["max_nodes"]:
                raise ValueError("NetCDF tree exceeds max_nodes")
            key = path.rstrip("/") + "/" + name
            record = _entry(key, obj, "netcdf", limits)
            record["dimensions"] = list(obj.dimensions)
            rows.append(record)
            datasets[key] = obj
        for name, child in group.groups.items():
            visit(child, path.rstrip("/") + "/" + name, depth + 1)

    visit(root, "/", 0)
    return rows, datasets


def _metadata(path, limits):
    if path.is_symlink():
        raise ValueError("Zarr metadata symlinks are blocked")
    if path.stat().st_size > limits["max_metadata_bytes"]:
        raise ValueError("Zarr metadata exceeds max_metadata_bytes")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"invalid Zarr JSON metadata: {path.name}") from exc
    if not isinstance(obj, dict):
        raise ValueError("Zarr metadata must be a JSON object")
    return obj


def _safe_codecs(value):
    if value is None:
        return True
    if isinstance(value, list):
        return all(_safe_codecs(v) for v in value)
    if not isinstance(value, dict) or value.get("id", value.get("name")) not in SAFE_CODECS:
        return False
    configuration = value.get("configuration", value)
    return all(_safe_codecs(configuration[k]) for k in ("codecs", "index_codecs") if k in configuration)


def _zarr_inventory(path, limits):
    rows, datasets, scanned = [], {}, 0

    def visit(directory, depth):
        nonlocal scanned
        if depth > limits["max_depth"]:
            raise ValueError("Zarr store exceeds max_depth")
        relative = directory.relative_to(path).as_posix()
        key = "/" if relative == "." else "/" + relative
        version3 = directory / "zarr.json"
        array_meta, group_meta = directory / ".zarray", directory / ".zgroup"
        metadata_file = version3 if version3.is_file() else array_meta if array_meta.is_file() else group_meta
        if metadata_file.is_file():
            if len(rows) >= limits["max_nodes"]:
                raise ValueError("Zarr tree exceeds max_nodes")
            obj = _metadata(metadata_file, limits)
            is_array = metadata_file == array_meta or obj.get("node_type") == "array"
            attrs_file = directory / ".zattrs"
            attrs = (
                obj.get("attributes", {})
                if metadata_file == version3
                else (_metadata(attrs_file, limits) if attrs_file.is_file() else {})
            )
            reason, dtype, chunks = None, None, None
            if is_array:
                try:
                    dtype = np.dtype(obj.get("dtype", obj.get("data_type")))
                except (ValueError, TypeError):
                    reason = "unsupported or object dtype blocked"
                if dtype is not None and (
                    dtype.hasobject or dtype.fields is not None or dtype.kind not in "fiuSU"
                ):
                    reason = "object/compound dtype blocked; pickle decoding is never used"
                if any(not _safe_codecs(obj.get(k)) for k in ("compressor", "filters", "codecs")):
                    reason = "unknown or unsafe codec blocked; pickle decoding is never used"
                if obj.get("storage_transformers"):
                    reason = "external storage transformers are blocked"
                chunks = obj.get(
                    "chunks", obj.get("chunk_grid", {}).get("configuration", {}).get("chunk_shape")
                )
                datasets[key] = directory
            rows.append(
                {
                    "path": key,
                    "kind": "dataset" if is_array else "group",
                    "shape": obj.get("shape") if is_array else None,
                    "dtype": str(dtype) if dtype else None,
                    "attrs": _small_value(attrs),
                    "readable": is_array and reason is None,
                    "blocked_reason": reason,
                    "chunks": chunks,
                    "zarr_format": obj.get("zarr_format", 2),
                }
            )
        with os.scandir(directory) as entries:
            for entry in entries:
                scanned += 1
                if scanned > limits["max_store_entries"]:
                    raise ValueError("Zarr store exceeds max_store_entries")
                if entry.is_symlink():
                    raise ValueError("Zarr store symlinks are blocked")
                if entry.is_dir(follow_symlinks=False):
                    visit(Path(entry.path), depth + 1)

    visit(path, 0)
    if not rows:
        raise ValueError("directory does not contain Zarr metadata")
    return rows, datasets


@contextmanager
def _opened(path, config):
    path, kind, limits = _source(path, config)
    if kind == "hdf5":
        library = _optional("h5py")
        with library.File(path, "r") as root:
            rows, datasets = _hdf_inventory(root, library, limits)
            yield path, kind, limits, rows, datasets
    elif kind == "netcdf":
        library = _optional("netCDF4")
        with path.open("rb") as stream:
            hdf_signature = stream.read(8) == b"\x89HDF\r\n\x1a\n"
        if hdf_signature:
            hdf = _optional("h5py")
            with hdf.File(path, "r") as root:
                checked, _ = _hdf_inventory(root, hdf, limits)
                if any(
                    row["kind"] == "link"
                    or row["blocked_reason"] == "virtual/external dataset storage blocked"
                    for row in checked
                ):
                    raise ValueError("NetCDF HDF5 links or external storage are blocked")
        # The documented memory API also handles Windows Unicode paths that the
        # native netCDF-C filename API cannot open. Bound source allocation first.
        if path.stat().st_size > limits["max_bytes"]:
            raise ValueError("NetCDF in-memory source exceeds max_bytes; export a smaller subset")
        with library.Dataset("local-array.nc", memory=path.read_bytes()) as root:
            root.set_auto_maskandscale(False)
            rows, datasets = _netcdf_inventory(root, limits)
            yield path, kind, limits, rows, datasets
    else:
        rows, datasets = _zarr_inventory(path, limits)
        yield path, kind, limits, rows, datasets


def _tree_data(path, kind, rows):
    return {
        "file_path": str(path),
        "format": kind,
        "mode": "browse",
        "tree": rows,
        "dataset_paths": [row["path"] for row in rows if row["readable"]],
        "root_attrs": next((row["attrs"] for row in rows if row["path"] == "/"), {}),
    }


def inspect_array_tree(path, config=None):
    """Return bounded real local paths/shapes/dtypes/attrs, without signal reads."""
    with _opened(path, dict(config or {})) as (source, kind, _, rows, _datasets):
        return NodeResult(table=pd.DataFrame(rows, columns=TREE_COLUMNS), data=_tree_data(source, kind, rows))


def _checked(key, rows, limits, *, numeric=True):
    name = _path(key)
    record = next((row for row in rows if row["path"] == name), None)
    if record is None:
        raise ValueError(f"dataset path not found: {name}")
    if not record["readable"]:
        raise ValueError(f"dataset {name} is blocked: {record['blocked_reason']}")
    if record["kind"] != "dataset":
        raise ValueError(f"path is not a readable dataset: {name}")
    shape = record["shape"]
    if not isinstance(shape, (list, tuple)) or any(type(n) is not int or n < 1 for n in shape):
        raise ValueError("dataset dimensions must be nonempty positive integer sizes")
    dtype = np.dtype(record["dtype"])
    if numeric and dtype.kind not in "fiu":
        raise ValueError("signal and coordinate arrays must have a real numeric dtype")
    size = math.prod(shape)
    cost = size * max(dtype.itemsize, 8)
    if size > limits["max_rows"] or cost > limits["max_bytes"]:
        raise ValueError("selected dataset exceeds max_rows/max_bytes before allocation")
    chunks = record["chunks"]
    if chunks and math.prod(chunks) * max(dtype.itemsize, 8) > limits["max_bytes"]:
        raise ValueError("dataset chunk exceeds max_bytes before decompression")
    return name, record, cost


def _read(name, record, datasets, kind, config, *, decode_numeric=True):
    obj = datasets[name]
    if kind == "zarr":
        library = _optional("zarr")
        if record.get("zarr_format", 2) == 3 and int(library.__version__.split(".")[0]) < 3:
            raise ValueError("Zarr v3 reading requires Python >=3.11 and python -m pip install 'zarr>=3'")
        obj = library.open_array(str(obj), mode="r")
    values = np.asarray(obj[...])
    if kind == "netcdf" and values.dtype.kind in "fiu" and decode_numeric:
        attrs = record["attrs"]
        values = values.astype(float)
        for key in ("_FillValue", "missing_value"):
            if key in attrs and np.isscalar(attrs[key]):
                values[values == attrs[key]] = np.nan
        if config.get("decode_cf", True):
            values = values * float(attrs.get("scale_factor", 1)) + float(attrs.get("add_offset", 0))
    return values


def _snr(y, x, bounds, identifiers):
    if bounds is None:
        return [], "not calculated without an explicitly declared noise_range"
    bounds = np.asarray(bounds, dtype=float)
    if bounds.shape != (2,) or not np.isfinite(bounds).all() or bounds[0] >= bounds[1]:
        raise ValueError("noise_range requires finite increasing bounds in source x units")
    chosen = (x >= bounds[0]) & (x <= bounds[1])
    if chosen.sum() < 2:
        raise ValueError("noise_range must contain at least two observed coordinate points")
    output = []
    for identifier, signal in zip(identifiers, y, strict=True):
        noise = signal[chosen]
        noise = noise[np.isfinite(noise)]
        sigma = float(np.std(noise, ddof=1)) if len(noise) > 1 else np.nan
        finite = signal[np.isfinite(signal)]
        snr = float(np.max(np.abs(finite)) / sigma) if sigma > 0 and len(finite) else None
        output.append(
            {
                "curve_id": identifier,
                "snr": snr,
                "noise_std": sigma if np.isfinite(sigma) else None,
                "noise_points": len(noise),
                "status": "estimated" if snr is not None else "unavailable",
            }
        )
    return output, "max(abs(processed signal)) / sample standard deviation in caller-declared noise_range"


def import_array(path, config=None):
    """Map selected 1D/2D arrays to long curves; 2D orientation is always explicit."""
    config = dict(config or {})
    mode = config.get("mode", "read")
    if mode == "browse":
        return inspect_array_tree(path, config)
    if mode != "read":
        raise ValueError("array mode must be browse or read")
    with _opened(path, config) as (source, kind, limits, rows, datasets):
        signal = _checked(config.get("dataset_path"), rows, limits)
        axis = _checked(config.get("x_axis_path"), rows, limits)
        shape = signal[1]["shape"]
        if len(shape) not in {1, 2}:
            raise ValueError("selected signal must be 1D or 2D; select/export a lower-dimensional dataset")
        spectral_axis = 0 if len(shape) == 1 else config.get("spectrum_axis")
        if type(spectral_axis) is not int or spectral_axis not in range(len(shape)):
            raise ValueError("2D arrays require explicit spectrum_axis=0 or 1; orientation is never inferred")
        n_points = shape[spectral_axis]
        n_curves = 1 if len(shape) == 1 else shape[1 - spectral_axis]
        if axis[1]["shape"] != [n_points]:
            raise ValueError("x_axis_path must be a 1D axis matching the explicit spectral dimension length")
        chosen = {"signal": signal, "axis": axis}
        if len(shape) == 2:
            chosen["identifiers"] = _checked(config.get("group_axis_path"), rows, limits, numeric=False)
            if chosen["identifiers"][1]["shape"] != [n_curves]:
                raise ValueError("group_axis_path must be a 1D identifier axis matching the other dimension")
        for name in ("background", "reference"):
            if config.get(name + "_path"):
                value = _checked(config[name + "_path"], rows, limits)
                if value[1]["shape"] not in ([n_points], shape):
                    raise ValueError(f"{name} must match the signal shape or the 1D spectral axis")
                signal_unit = signal[1]["attrs"].get("units")
                other_unit = value[1]["attrs"].get("units")
                if signal_unit and other_unit and signal_unit != other_unit:
                    raise ValueError(
                        f"{name} units must match signal units; convert explicitly before importing"
                    )
                chosen[name] = value
        estimated_bytes = sum(record[2] for record in chosen.values()) + n_curves * n_points * 48
        if kind == "netcdf":
            estimated_bytes += source.stat().st_size
        if estimated_bytes > limits["max_bytes"]:
            raise ValueError("combined arrays and long-table output exceed max_bytes before allocation")
        loaded = {
            name: _read(value[0], value[1], datasets, kind, config, decode_numeric=name != "identifiers")
            for name, value in chosen.items()
        }
        x = loaded["axis"].astype(float)
        if not np.isfinite(x).all() or len(np.unique(x)) != len(x):
            raise ValueError("spectral axis must contain finite unique coordinates")
        y = loaded["signal"].astype(float)
        y = y.reshape(1, -1) if len(shape) == 1 else np.moveaxis(y, spectral_axis, -1)
        identifiers = loaded.get("identifiers", np.array([config.get("curve_id", "0")]))
        identifiers = [
            bytes(value).decode("utf-8")
            if isinstance(value, (bytes, np.bytes_))
            else value.item()
            if isinstance(value, np.generic)
            else value
            for value in identifiers
        ]
        if (
            any(pd.isna(value) or not str(value).strip() for value in identifiers)
            or len(set(map(str, identifiers))) != n_curves
        ):
            raise ValueError("group_axis_path identifiers must be nonmissing and unique")
        raw = y.copy()
        base = loaded.get("background", np.zeros(n_points))
        if base.ndim == 2:
            base = np.moveaxis(base, spectral_axis, -1)
        y = y - base
        invalid = ~np.isfinite(y)
        normalization = "signal-background" if "background" in loaded else "none"
        if "reference" in loaded:
            reference = loaded["reference"]
            if reference.ndim == 2:
                reference = np.moveaxis(reference, spectral_axis, -1)
            denominator = reference - base
            floor = config.get("reference_floor", 0.0)
            if isinstance(floor, bool) or not np.isfinite(float(floor)) or float(floor) < 0:
                raise ValueError("reference_floor must be a finite nonnegative number")
            invalid |= ~np.isfinite(denominator) | (denominator <= float(floor))
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                y = np.divide(y, denominator)
            normalization = (
                "(signal-background)/(reference-background)" if "background" in loaded else "signal/reference"
            )
        invalid |= ~np.isfinite(y)
        y[invalid] = np.nan
        frame = pd.DataFrame(
            {
                "curve_id": np.repeat(np.array(identifiers, dtype=object), n_points),
                "x": np.tile(x, n_curves),
                "y": y.ravel(),
            }
        )
        if normalization != "none" or invalid.any():
            frame["raw_y"], frame["invalid_channel"] = raw.ravel(), invalid.ravel()
        units = {}
        for column, value in (("x", axis[1]["attrs"].get("units")), ("y", signal[1]["attrs"].get("units"))):
            if isinstance(value, str) and value.strip():
                units[column] = value
        if "reference" in loaded:
            if "y" in units:
                units["raw_y"] = units["y"]
            units["y"] = "dimensionless"
        elif "raw_y" in frame and "y" in units:
            units["raw_y"] = units["y"]
        frame.attrs["units"] = units
        snr, definition = _snr(y, x, config.get("noise_range"), identifiers)
        details = {
            **_tree_data(source, kind, rows),
            "mode": "read",
            "rows": len(frame),
            "selected_dataset": signal[1],
            "x_axis": axis[1],
            "spectrum_axis": spectral_axis,
            "group_axis_path": config.get("group_axis_path"),
            "normalization": normalization,
            "invalid_channel_count": int(invalid.sum()),
            "snr": snr,
            "snr_definition": definition,
            "decode_cf": config.get("decode_cf", True) if kind == "netcdf" else None,
            "estimated_allocation_bytes": estimated_bytes,
        }
        warnings = (
            [
                "SNR uses the caller-declared noise window; "
                "a spectral feature in that window biases the estimate."
            ]
            if snr
            else []
        )
        if invalid.any():
            warnings.append(
                "Invalid/missing signal or nonpositive reference channels remain missing "
                "and are explicitly flagged."
            )
        return NodeResult(table=frame, data=json_value(details), warnings=warnings)
