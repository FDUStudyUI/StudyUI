"""Bounded JSON transport for complete tables; never executes serialized code."""

import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import numpy as np
import pandas as pd

from materials_quality.common import validate_table
from materials_quality.context import _typed
from materials_quality.science.table_contract import attach_contract, make_contract, read_contract

SCHEMA = "materials-batch/1"
TABLE_SCHEMA = "materials-batch-table/1"
MAX_ITEMS = 10000
MAX_CELLS = 2_000_000
MAX_ROWS = 1_000_000
MAX_COLUMNS = 10000
RESERVED = ("batch_item_id", "batch_label")


def _decode(value, depth=0):
    if depth > 32 or not isinstance(value, list) or not value or not isinstance(value[0], str):
        raise ValueError("invalid typed cell")
    tag, args = value[0], value[1:]
    if tag in {"pd.NA", "pd.NaT", "null"} and not args:
        return {"pd.NA": pd.NA, "pd.NaT": pd.NaT, "null": None}[tag]
    if len(args) != 1 and tag != "timedelta":
        raise ValueError("invalid typed cell arguments")
    arg = args[0] if args else None
    if tag == "str" and isinstance(arg, str):
        return arg
    if tag == "bool" and type(arg) is bool:
        return arg
    if tag == "int" and isinstance(arg, str) and re.fullmatch(r"[+-]?\d{1,4300}", arg):
        return int(arg)
    if tag == "float" and isinstance(arg, str):
        return float(arg) if arg in {"nan", "inf", "-inf"} else float.fromhex(arg)
    if tag in {"list", "tuple"} and isinstance(arg, list):
        result = [_decode(v, depth + 1) for v in arg]
        return tuple(result) if tag == "tuple" else result
    if tag == "dict" and isinstance(arg, dict) and all(isinstance(k, str) for k in arg):
        return {k: _decode(v, depth + 1) for k, v in arg.items()}
    if tag in {"Timestamp", "datetime", "date", "Decimal", "pd.Timedelta"} and isinstance(arg, str):
        return {
            "Timestamp": pd.Timestamp,
            "datetime": datetime.fromisoformat,
            "date": date.fromisoformat,
            "Decimal": Decimal,
            "pd.Timedelta": pd.Timedelta,
        }[tag](arg)
    if tag == "timedelta" and len(args) == 3 and all(type(v) is int for v in args):
        return timedelta(days=args[0], seconds=args[1], microseconds=args[2])
    if re.fullmatch(r"(?:datetime64|timedelta64)\[(?:Y|M|W|D|h|m|s|ms|us|ns|ps|fs|as)\]", tag):
        if isinstance(arg, str):
            return np.array(int(arg), dtype="int64").view(tag)[()]
    raise ValueError(f"unsupported or malformed typed cell: {tag}")


def _dtype(dtype):
    if isinstance(dtype, pd.CategoricalDtype):
        return {
            "name": "category",
            "ordered": dtype.ordered,
            "categories": [_typed(v) for v in dtype.categories],
            "categories_dtype": str(dtype.categories.dtype),
        }
    return {"name": str(dtype)}


def _restore_dtype(spec):
    if not isinstance(spec, dict) or not isinstance(spec.get("name"), str):
        raise ValueError("invalid table dtype")
    if spec["name"] == "category":
        if type(spec.get("ordered")) is not bool or not isinstance(spec.get("categories"), list):
            raise ValueError("invalid category dtype")
        values = [_decode(v) for v in spec["categories"]]
        categories = pd.Index(values, dtype=spec.get("categories_dtype", "object"))
        return pd.CategoricalDtype(categories=categories, ordered=spec["ordered"])
    # pandas' dtype registry constructs data types only; never import/evaluate a payload.
    try:
        return pd.api.types.pandas_dtype(spec["name"])
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported table dtype") from exc


def _pack_index(index):
    result = {"names": [_typed(n) for n in index.names]}
    if isinstance(index, pd.RangeIndex):
        return {**result, "kind": "range", "start": index.start, "stop": index.stop, "step": index.step}
    if isinstance(index, pd.MultiIndex):
        return {
            **result,
            "kind": "multi",
            "levels": [_pack_index(v) for v in index.levels],
            "codes": [v.tolist() for v in index.codes],
        }
    return {
        **result,
        "kind": "index",
        "dtype": _dtype(index.dtype),
        "values": [_typed(v) for v in index],
        "freq": getattr(index, "freqstr", None),
    }


def _unpack_index(spec, size):
    if not isinstance(spec, dict) or not isinstance(spec.get("names"), list):
        raise ValueError("invalid table index")
    names = [_decode(v) for v in spec["names"]]
    kind = spec.get("kind")
    if kind == "range":
        if len(names) != 1 or any(type(spec.get(k)) is not int for k in ("start", "stop", "step")):
            raise ValueError("invalid range index")
        if not spec["step"] or len(range(spec["start"], spec["stop"], spec["step"])) != size:
            raise ValueError("table index length mismatch")
        return pd.RangeIndex(spec["start"], spec["stop"], spec["step"], name=names[0])
    if kind == "multi":
        levels, codes = spec.get("levels"), spec.get("codes")
        if (
            not isinstance(levels, list)
            or not isinstance(codes, list)
            or not len(levels) == len(codes) == len(names)
        ):
            raise ValueError("invalid multi index")
        if any(
            not isinstance(c, list) or len(c) != size or any(type(v) is not int for v in c) for c in codes
        ):
            raise ValueError("invalid multi index codes")
        level_indices = []
        for level in levels:
            if not isinstance(level, dict) or level.get("kind") not in {"range", "index"}:
                raise ValueError("invalid multi index level")
            length = (
                len(level.get("values", []))
                if level.get("kind") != "range"
                else len(range(level["start"], level["stop"], level["step"]))
            )
            if length > MAX_ROWS:
                raise ValueError("index size limit exceeded")
            level_indices.append(_unpack_index(level, length))
        return pd.MultiIndex(levels=level_indices, codes=codes, names=names, verify_integrity=True)
    values = spec.get("values")
    if kind != "index" or len(names) != 1 or not isinstance(values, list) or len(values) != size:
        raise ValueError("invalid index values or length")
    dtype = _restore_dtype(spec.get("dtype"))
    result = pd.Index([_decode(v) for v in values], dtype=dtype, name=names[0], tupleize_cols=False)
    if isinstance(result, (pd.DatetimeIndex, pd.TimedeltaIndex)) and spec.get("freq"):
        result.freq = spec["freq"]
    return result


def _shape(rows, columns):
    if rows > MAX_ROWS or columns > MAX_COLUMNS or rows * columns > MAX_CELLS:
        raise ValueError("table size limit exceeded")


def pack_table(frame):
    """Encode values as tagged JSON scalars, including exact IEEE float hex."""
    validate_table(frame)
    _shape(*frame.shape)
    result = {
        "schema_version": TABLE_SCHEMA,
        "columns": frame.columns.tolist(),
        "columns_name": _typed(frame.columns.name),
        "dtypes": [_dtype(d) for d in frame.dtypes],
        "index": _pack_index(frame.index),
        "attrs": _typed(frame.attrs),
        "data": [[_typed(v) for v in row] for row in frame.itertuples(index=False, name=None)],
    }
    contract = read_contract(frame)
    if contract is not None:
        result["contract"] = contract
    json.dumps(result, allow_nan=False)
    return result


def unpack_table(payload):
    """Decode the bounded, explicit type vocabulary; rejects malformed shapes."""
    if not isinstance(payload, dict) or payload.get("schema_version") != TABLE_SCHEMA:
        raise ValueError("invalid encoded table schema")
    columns, data, dtypes = payload.get("columns"), payload.get("data"), payload.get("dtypes")
    if not isinstance(columns, list) or not isinstance(data, list) or not isinstance(dtypes, list):
        raise ValueError("invalid encoded table fields")
    _shape(len(data), len(columns))
    if len(columns) != len(dtypes) or any(not isinstance(r, list) or len(r) != len(columns) for r in data):
        raise ValueError("encoded table shape mismatch")
    if any(not isinstance(c, str) or not c.strip() for c in columns) or len(set(columns)) != len(columns):
        raise ValueError("encoded table columns must be unique nonempty strings")
    index = _unpack_index(payload.get("index"), len(data))
    series = {
        name: pd.Series([_decode(row[i]) for row in data], dtype=_restore_dtype(dtypes[i]))
        for i, name in enumerate(columns)
    }
    result = pd.DataFrame(series, columns=columns)
    if not columns:
        result = pd.DataFrame(index=pd.RangeIndex(len(data)))
    result.index = index
    result.columns.name = _decode(payload.get("columns_name", ["null"]))
    attrs = _decode(payload.get("attrs", ["dict", {}]))
    if not isinstance(attrs, dict):
        raise ValueError("table attrs must be a dictionary")
    result.attrs = attrs
    cached_contract = read_contract(result)
    if "contract" in payload:
        explicit = payload["contract"]
        result = attach_contract(result, explicit)
        if cached_contract is not None and cached_contract != explicit:
            raise ValueError("table contract mismatch between attrs and transport")
    return result


def is_batch(value):
    value = getattr(value, "data", value)
    return isinstance(value, dict) and value.get("schema_version") == SCHEMA


def make_item(item_id, label, source, table=None, report=None):
    item = {
        "id": item_id,
        "label": label,
        "source": deepcopy(source),
        "table": None if table is None else pack_table(table),
        "report": deepcopy(report),
        "history": [],
        "status": "completed",
        "error": None,
    }
    _validate_item(item)
    return item


def _validate_item(item):
    required = {"id", "label", "source", "table", "report", "history", "status", "error"}
    if not isinstance(item, dict) or not required <= item.keys():
        raise ValueError("incomplete batch item")
    if any(not isinstance(item[k], str) or not item[k].strip() for k in ("id", "label")):
        raise ValueError("batch item id and label must be nonempty strings")
    if not isinstance(item["source"], dict) or not isinstance(item["history"], list):
        raise ValueError("invalid item source/history")
    if item["report"] is not None and not isinstance(item["report"], dict):
        raise ValueError("item report must be a dictionary or None")
    if any(not isinstance(v, dict) for v in item["history"]):
        raise ValueError("item history must contain reports")
    if item["status"] not in {"completed", "failed", "skipped"}:
        raise ValueError("invalid batch item status")
    error = item["error"]
    if error is not None and (
        not isinstance(error, dict)
        or any(not isinstance(error.get(k), str) or not error[k].strip() for k in ("stage", "message"))
    ):
        raise ValueError("item error must contain stage and message")
    if item["status"] == "failed" and error is None:
        raise ValueError("failed batch item requires an error")
    if item["status"] == "completed" and error is not None:
        raise ValueError("completed batch item cannot have a technical error")
    source = item["source"]
    if "source_sha256" in source and not re.fullmatch(r"[0-9a-f]{64}", str(source["source_sha256"])):
        raise ValueError("invalid source_sha256")
    if item["table"] is not None:
        unpack_table(item["table"])


def _summary(items):
    counts = {
        "total": len(items),
        **{s: sum(i["status"] == s for i in items) for s in ("completed", "failed", "skipped")},
    }
    review = sum(bool(i.get("needs_review")) for i in items)
    if review:
        counts["needs_review"] = review
    if counts["failed"] or counts["skipped"]:
        status = "partial_failed" if counts["completed"] else "failed"
    else:
        status = "needs_review" if review else "completed"
    return counts, status


def make_batch(items, batch_id=None, on_error="continue"):
    items = deepcopy(items)
    if not isinstance(items, list):
        raise ValueError("batch items must be a list")
    for item in items:
        _validate_item(item)
    counts, status = _summary(items)
    result = {
        "schema_version": SCHEMA,
        "batch_id": str(uuid4()) if batch_id is None else batch_id,
        "items": items,
        "on_error": on_error,
        "counts": counts,
        "execution_status": status,
    }
    validate_batch(result)
    return result


def validate_batch(packet):
    if not is_batch(packet) or not isinstance(packet, dict):
        raise ValueError("invalid batch schema")
    if not isinstance(packet.get("batch_id"), str) or not packet["batch_id"].strip():
        raise ValueError("batch_id must be a nonempty string")
    if packet.get("on_error") not in {"continue", "stop"}:
        raise ValueError("on_error must be continue or stop")
    items = packet.get("items")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError("batch item limit exceeded or invalid items")
    for item in items:
        _validate_item(item)
    if len({i["id"] for i in items}) != len(items):
        raise ValueError("batch item ids must be unique")
    counts, status = _summary(items)
    if packet.get("counts") != counts:
        raise ValueError("batch counts disagree with item statuses")
    if packet.get("execution_status") != status:
        raise ValueError("batch execution_status disagrees with item statuses")
    try:
        json.dumps(packet, allow_nan=False)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("batch must be finite JSON serializable") from exc
    return packet


def combined_table(packet):
    """Collect completed tables with explicit specimen metadata, preserving order."""
    validate_batch(packet)
    frames = []
    units = {}
    for item in packet["items"]:
        if item["status"] != "completed" or item["table"] is None:
            continue
        frame = unpack_table(item["table"])
        for name, expected in zip(RESERVED, (item["id"], item["label"]), strict=True):
            if (
                name in frame
                and not frame[name].map(lambda v, e=expected: isinstance(v, str) and v == e).all()
            ):
                raise ValueError(f"reserved metadata collision: {name}")
            frame[name] = expected
        for name, unit in frame.attrs.get("units", {}).items():
            if name in units and units[name] != unit:
                raise ValueError(f"cannot combine conflicting units for {name}")
            units[name] = unit
        frames.append(frame)
    if not frames:
        return None
    result = pd.concat(frames, ignore_index=True, sort=False)
    # pandas may inherit attrs from the first frame. A concat is a new table and
    # must never silently retain one source's declarations or independence.
    result.attrs.pop("contract", None)
    if units:
        result.attrs["units"] = units
    contracts = [read_contract(frame) for frame in frames]
    if any(contract is not None for contract in contracts):
        fields = ("granularity", "roles", "experimental_design", "aggregation", "units_state")
        first = contracts[0]
        compatible = first is not None and all(
            contract is not None and all(contract[field] == first[field] for field in fields)
            for contract in contracts
        )
        provenance = [{"operation": "concat", "contract_sha256": contract["contract_sha256"]}
                      for contract in contracts if contract is not None]
        if compatible:
            try:
                result = attach_contract(result, make_contract(
                    result, granularity=first["granularity"], roles=first["roles"],
                    experimental_design=first["experimental_design"], aggregation=first["aggregation"],
                    derived_from=provenance, units_state=first["units_state"],
                ))
            except ValueError:
                compatible = False
        if not compatible:
            result.attrs["contract_provenance"] = provenance
            result.attrs["contract_warnings"] = [
                "Contract cleared: concatenated tables have conflicting or undeclared semantics."
            ]
    return result
