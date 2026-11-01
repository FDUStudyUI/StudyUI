"""Shared operation contract; no dependency on the Langflow runtime."""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from materials_quality.common import select_columns, validate_table


@dataclass
class NodeResult:
    table: pd.DataFrame | None = None
    data: dict = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    features: pd.DataFrame | None = None


def require_table(table, columns=None, min_rows=1):
    validate_table(table)
    if type(min_rows) is not int or min_rows < 0:
        raise ValueError("min_rows must be a nonnegative integer")
    if len(table) < min_rows:
        raise ValueError(f"at least {min_rows} rows are required")
    if columns is not None:
        select_columns(table, columns)
    return table.copy(deep=True)


def numeric_matrix(table, columns):
    frame = require_table(table, columns)
    selected = select_columns(frame, columns)
    if any(frame[c].map(lambda x: isinstance(x, (bool, np.bool_))).any() for c in selected):
        raise ValueError("boolean values require an explicit numeric conversion")
    try:
        values = frame[selected].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("selected columns must contain finite numeric values") from exc
    if not np.isfinite(values).all():
        raise ValueError("selected columns contain missing or non-finite values")
    return values


def read_path(config, data=None):
    config = config or {}
    path = config.get("path") or config.get("file_path")
    if not path and isinstance(data, dict):
        path = data.get("file_path")
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise ValueError("provide config.path or an upstream file_path")
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"input file does not exist: {resolved}")
    return resolved


def artifact_path(config, filename):
    config = config or {}
    if not isinstance(filename, str) or Path(filename).name != filename or filename in {"", ".", ".."}:
        raise ValueError("artifact filename must be a simple file name")
    directory = config.get("output_dir")
    directory = Path(directory).expanduser() if directory else Path(tempfile.mkdtemp(prefix="studyui-"))
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    if target.exists() and not config.get("overwrite", False):
        target = target.with_name(f"{target.stem}-{uuid4().hex[:10]}{target.suffix}")
    return target
