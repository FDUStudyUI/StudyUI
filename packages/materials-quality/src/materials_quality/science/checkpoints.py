"""Project-local checkpoints for deterministic scientific calculations.

Only declared pure operations participate. Files, plots, network requests and
model calls always execute. Parquet stores tables; typed JSON stores scientific
metadata. Cache keys bind inputs, parameters, implementation and dependencies.
"""

import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from filelock import FileLock

from .analysis_plan import PURE_OPERATIONS, _canonical, _implementation_fingerprint, fingerprint
from .contracts import NodeResult

_scope = ContextVar("scientific_checkpoints", default=None)


@contextmanager
def checkpoint_scope(root):
    root = Path(root).resolve()
    if os.name == "nt" and not str(root).startswith("\\\\?\\"):
        value = str(root)
        root = Path("\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value)
    state = {"root": root, "implementation": _implementation_fingerprint(), "records": []}
    token = _scope.set(state)
    try:
        yield state["records"]
    finally:
        _scope.reset(token)


def _decode(value):
    kind, *body = value
    if kind == "null":
        return None
    if kind in {"pd.NA", "pd.NaT"}:
        return pd.NA if kind == "pd.NA" else pd.NaT
    if kind in {"str", "bool"}:
        return body[0]
    if kind == "int":
        return int(body[0])
    if kind == "float":
        return float.fromhex(body[0])
    if kind in {"list", "tuple"}:
        items = [_decode(v) for v in body[0]]
        return items if kind == "list" else tuple(items)
    if kind == "dict":
        return {_decode(k): _decode(v) for k, v in body[0]}
    if kind == "numpy":
        return np.array(_decode(body[1]), dtype=body[0])[()]
    if kind == "ndarray":
        return np.array(_decode(body[2]), dtype=body[0]).reshape(body[1])
    if kind in {"Timestamp", "datetime", "date"}:
        return {"Timestamp": pd.Timestamp, "datetime": datetime.fromisoformat, "date": date.fromisoformat}[
            kind
        ](body[0])
    if kind in {"Timedelta", "timedelta"}:
        delta = pd.Timedelta(body[0])
        return delta if kind == "Timedelta" else timedelta(seconds=delta.total_seconds())
    raise ValueError(f"Unsupported checkpoint metadata: {kind}")


def _save(directory, key, result):
    document = {
        "version": 1,
        "key": key,
        "result_fingerprint": fingerprint(result),
        "data": _canonical(result.data),
        "warnings": _canonical(result.warnings),
        "tables": {},
    }
    for name in ("table", "features"):
        frame = getattr(result, name)
        if frame is None:
            continue
        plain = frame.copy()
        plain.attrs = {}
        raw = plain.to_parquet(index=None)
        digest = hashlib.sha256(raw).hexdigest()
        path = directory / (name + "-" + digest[:16] + ".parquet")
        path.write_bytes(raw)
        document["tables"][name] = {
            "file": path.name,
            "sha256": digest,
            "attrs": _canonical(frame.attrs),
        }
    temporary = directory / (uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(document, ensure_ascii=True), encoding="utf-8")
        os.replace(temporary, directory / "result.json")
    finally:
        temporary.unlink(missing_ok=True)


def _load(directory, key):
    document = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if document["version"] != 1 or document["key"] != key:
        raise ValueError("Checkpoint identity changed")
    frames = {}
    for name, entry in document["tables"].items():
        if name not in {"table", "features"} or Path(entry["file"]).name != entry["file"]:
            raise ValueError("Invalid checkpoint table")
        path = directory / entry["file"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("Checkpoint table checksum changed")
        frames[name] = pd.read_parquet(BytesIO(raw))
        frames[name].attrs = _decode(entry["attrs"])
    result = NodeResult(**frames, data=_decode(document["data"]), warnings=_decode(document["warnings"]))
    if fingerprint(result) != document["result_fingerprint"]:
        raise ValueError("Checkpoint result changed")
    return result


def invoke(operation, table, config, data, tables, compute, *, dependencies=None):
    state = _scope.get()
    if state is None or operation not in PURE_OPERATIONS:
        return compute(), None
    record = {"operation": operation, "status": "computed"}
    try:
        key = fingerprint([operation, table, config, data, tables, dependencies, state["implementation"]])
        record["key"] = key
        directory = state["root"] / key
        directory.mkdir(parents=True, exist_ok=True)
        with FileLock(str(directory / ".lock"), timeout=10):
            try:
                result = _load(directory, key)
            except FileNotFoundError:
                record["reason"] = "new_inputs_or_parameters"
            except (OSError, ValueError, KeyError, TypeError):
                record["reason"] = "checkpoint_changed_recomputed"
            else:
                record["status"] = "reused"
                state["records"].append(record)
                return result, record
    except (OSError, ValueError, ImportError):
        record.update(status="unavailable", reason="checkpoint_storage_or_type_unavailable")
        directory = None
    result = compute()
    # Partial batch results remain visible but never masquerade as a successful checkpoint.
    complete = result.data.get("execution_status", "completed") in {"completed", "success"}
    if directory is not None and not result.artifacts and complete:
        try:
            with FileLock(str(directory / ".lock"), timeout=10):
                _save(directory, key, result)
        except (OSError, ValueError, TypeError, ImportError):
            record.update(status="unavailable", reason="checkpoint_storage_or_type_unavailable")
    elif not complete:
        record["status"] = "incomplete_not_saved"
    state["records"].append(record)
    return result, record
