"""Read-only whole-file and complete-specimen batch sources."""

import glob
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from materials_quality.common import missing, validate_table
from materials_quality.context import _typed, table_fingerprint
from materials_quality.science.io_nodes import table_import

from .packet import MAX_ITEMS, make_batch, make_item

DEFAULT_MAX_ITEMS = 2000
DEFAULT_MAX_BYTES = 268435456


def _limits(max_items, max_bytes=DEFAULT_MAX_BYTES):
    if type(max_items) is not int or not 1 <= max_items <= MAX_ITEMS:
        raise ValueError(f"max_items must be between 1 and {MAX_ITEMS}")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")


def _paths(value):
    if value is None or value == "":
        return []
    if isinstance(value, (str, Path)):
        value = [value]
    if not isinstance(value, list) or any(
        not isinstance(p, (str, Path)) or not str(p).strip() for p in value
    ):
        raise ValueError("file paths must be a list of nonempty paths")
    result = []
    for raw in value:
        path = Path(raw).expanduser()
        if path.exists() or not glob.has_magic(str(path)):
            result.append(path.resolve())
            continue
        matches = []
        for match in glob.iglob(str(path), recursive=True):
            if Path(match).is_file():
                matches.append(Path(match).resolve())
                if len(matches) + len(result) > MAX_ITEMS:
                    raise ValueError("glob file count exceeds max_items limit")
        if not matches:
            raise ValueError(f"glob 未匹配到文件：{raw}")
        result.extend(sorted(matches))
    return result


def validate_rename_columns(mapping):
    mapping = {} if mapping is None else deepcopy(mapping)
    if not isinstance(mapping, dict) or any(
        not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
        for k, v in mapping.items()
    ):
        raise ValueError("rename_columns must map nonempty original names to nonempty standard names")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("rename_columns targets must be unique")
    return mapping


def _rename(frame, mapping):
    absent = mapping.keys() - set(frame.columns)
    if absent:
        raise ValueError(f"rename_columns source columns missing: {sorted(absent)}")
    names = [mapping.get(c, c) for c in frame.columns]
    if len(set(names)) != len(names):
        raise ValueError("rename_columns creates a column collision")
    result = frame.rename(columns=mapping).copy(deep=True)
    result.attrs = deepcopy(frame.attrs)
    if "units" in result.attrs:
        result.attrs["units"] = {mapping.get(c, c): u for c, u in result.attrs["units"].items()}
    return result


def _hash_file(path, max_bytes):
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"file size exceeds max_bytes limit ({max_bytes})")
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            read += len(block)
            if read > max_bytes:
                raise ValueError("file grew beyond max_bytes limit while reading")
            digest.update(block)
    return digest.hexdigest()


def _identity(path):
    return "file_" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:24]


def files_batch(
    paths,
    *,
    on_error="continue",
    max_items=DEFAULT_MAX_ITEMS,
    max_bytes=DEFAULT_MAX_BYTES,
    rename_columns=None,
):
    _limits(max_items, max_bytes)
    if on_error not in {"continue", "stop"}:
        raise ValueError("on_error must be continue or stop")
    paths = _paths(paths)
    if not paths:
        raise ValueError("select at least one source file")
    if len(paths) > max_items:
        raise ValueError("file count exceeds max_items limit")
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate source file paths are ambiguous")
    mapping = validate_rename_columns(rename_columns)
    items, stopped = [], False
    for path in paths:
        source = {"source_name": path.name, "file_path": str(path)}
        item = make_item(_identity(path), path.name, source, report={"file_path": str(path)})
        if stopped:
            item.update(
                status="skipped", error={"stage": "source", "message": "stopped after previous error"}
            )
        else:
            try:
                if not path.is_file():
                    raise ValueError(f"source file is missing or not a regular file: {path}")
                item["source"]["source_sha256"] = _hash_file(path, max_bytes)
            except (OSError, ValueError) as exc:
                item.update(
                    status="failed",
                    error={"stage": "source", "message": str(exc), "type": type(exc).__name__},
                )
                stopped = on_error == "stop"
        items.append(item)
    packet = make_batch(items, on_error=on_error)
    packet["rename_columns"] = mapping
    return packet


def grouped_batch(
    table,
    sample_column,
    *,
    source=None,
    on_error="continue",
    max_items=DEFAULT_MAX_ITEMS,
    rename_columns=None,
):
    _limits(max_items)
    validate_table(table)
    if not isinstance(sample_column, str) or not sample_column.strip() or sample_column not in table.columns:
        raise ValueError("sample_column must select an existing sample/group column")
    if table.empty:
        raise ValueError("sample/group table cannot be empty")
    keys = table[sample_column]
    if keys.map(lambda v: missing(v)).any():
        raise ValueError("sample/group identifiers cannot be missing or blank")
    # Distinct typed keys that share a display label (1 and '1') are ambiguous.
    labels, typed_keys, groups = {}, {}, []
    for position, key in enumerate(keys):
        identity = json.dumps(_typed(key), sort_keys=True, ensure_ascii=False, allow_nan=False)
        label = str(key)
        if label in labels and labels[label] != identity:
            raise ValueError("ambiguous sample/group identifiers have the same display label")
        labels[label] = identity
        if identity not in typed_keys:
            if len(groups) >= max_items:
                raise ValueError("sample/group count exceeds max_items limit")
            typed_keys[identity] = len(groups)
            groups.append((identity, label, []))
        groups[typed_keys[identity]][2].append(position)
    mapping = validate_rename_columns(rename_columns)
    renamed = _rename(table, mapping)
    source = deepcopy(source or {"source_name": "input_table", "source_sha256": table_fingerprint(table)})
    items = []
    for identity, label, positions in groups:
        item_source = {
            **source,
            "sample_column": sample_column,
            "sample_key": _typed(keys.iloc[positions[0]]),
        }
        frame = renamed.iloc[positions].copy(deep=True)
        frame.attrs = deepcopy(renamed.attrs)
        item_id = "group_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        items.append(make_item(item_id, label, item_source, frame))
    packet = make_batch(items, on_error=on_error)
    packet["rename_columns"] = {}
    return packet


def source_batch(
    *,
    source_mode="files",
    source_files=None,
    file_paths=None,
    input_table=None,
    sample_column="",
    rename_columns=None,
    on_error="continue",
    max_items=DEFAULT_MAX_ITEMS,
    max_bytes=DEFAULT_MAX_BYTES,
    group_from="none",
    group_separator="_",
):
    _limits(max_items, max_bytes)
    paths = _paths(source_files) + _paths(file_paths)
    if source_mode == "files":
        if input_table is not None:
            raise ValueError("files mode cannot accept input_table; choose grouped mode")
        output = files_batch(
            paths, on_error=on_error, max_items=max_items, max_bytes=max_bytes, rename_columns=rename_columns
        )
        if group_from not in {"none", "parent", "filename_prefix"}:
            raise ValueError("group_from must be none, parent or filename_prefix")
        if group_from == "filename_prefix" and not group_separator:
            raise ValueError("filename group separator must be nonempty")
        if group_from != "none":
            for item in output["items"]:
                path = Path(item["source"]["file_path"])
                item["source"]["group"] = (
                    path.parent.name if group_from == "parent" else path.stem.split(group_separator, 1)[0]
                )
        return output
    if source_mode != "grouped":
        raise ValueError("source_mode must be files or grouped")
    if input_table is not None and paths:
        raise ValueError("grouped mode accepts either input_table or one uploaded table file")
    source = None
    if input_table is None:
        if len(paths) != 1:
            raise ValueError("grouped mode requires one table file or input_table")
        path = paths[0]
        digest = _hash_file(path, max_bytes)
        input_table = table_import(config={"path": str(path)}).table
        source = {"source_name": path.name, "file_path": str(path), "source_sha256": digest}
    return grouped_batch(
        input_table,
        sample_column,
        source=source,
        on_error=on_error,
        max_items=max_items,
        rename_columns=rename_columns,
    )


def source_fingerprint(parameters):
    """Live content signature for multiple output calls, including edited files."""
    parameters = dict(parameters)
    max_items = parameters.get("max_items", DEFAULT_MAX_ITEMS)
    _limits(max_items, parameters.get("max_bytes", DEFAULT_MAX_BYTES))
    paths = _paths(parameters.get("source_files")) + _paths(parameters.get("file_paths"))
    if len(paths) > max_items:
        raise ValueError("file count exceeds max_items limit")
    table = parameters.pop("input_table", None)
    parameters["table_sha256"] = None if table is None else table_fingerprint(table)
    snapshots = []
    for path in paths:
        try:
            snapshot = _hash_file(path, parameters.get("max_bytes", DEFAULT_MAX_BYTES))
        except (OSError, ValueError) as exc:
            snapshot = f"{type(exc).__name__}:{exc}"
        snapshots.append([str(path), snapshot])
    parameters["source_files"] = []
    parameters["file_paths"] = snapshots
    return hashlib.sha256(
        json.dumps(parameters, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()
