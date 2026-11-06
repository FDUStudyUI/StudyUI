"""Bounded pure-science DAGs with authenticated, process-local result reuse.

Dependencies are ordered: the first supplies the primary table and metadata;
all dependency tables are supplied to multi-table operations. An explicit
``input`` selects a named external input instead of the first dependency.
Re-running is always explicit. Failed steps are attempted once per run; no
scientific parameter, fitting window, or original input is modified implicitly.
"""

import hashlib
import hmac
import json
import math
import secrets
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
import pandas as pd

from . import catalog
from .contracts import NodeResult
from .table_contract import propagate_contract, read_contract, restore_contract_units

# Deliberately explicit. Catalog registration alone never grants permission.
# File import/export, plotting, LLM, network, model serialization, and recursive
# plan execution are excluded, even when a config might disable their effects.
PURE_OPERATIONS = {
    "preprocess.filter": "preprocessing:filter_rows",
    "preprocess.missing": "preprocessing:handle_missing",
    "preprocess.units": "preprocessing:convert_units",
    "preprocess.reshape": "preprocessing:reshape_table",
    "preprocess.merge": "preprocessing:merge_tables",
    "preprocess.normalize": "preprocessing:normalize_table",
    "materials.xrd": "materials:xrd",
    "materials.spectra": "materials:spectra",
    "materials.batch_spectra": "spectrum_batch:analyze_spectra",
    "materials.thermal": "materials:thermal",
    "materials.mechanics": "materials:mechanics",
    "stats.grouped": "statistics:grouped",
    "stats.correlation": "statistics:correlation",
    "stats.significance": "statistics:significance",
    "stats.multiple": "statistics:multiple",
}
IMPLEMENTATION_VERSION = "analysis-plan-v1"
_AUTH_KEY = secrets.token_bytes(32)
_SUCCESS = {"success", "reused"}


def _canonical(value):
    """Typed, deterministic representation; never pickle or execute user objects."""
    if value is None:
        return ["null"]
    if value is pd.NA:
        return ["pd.NA"]
    if value is pd.NaT:
        return ["pd.NaT"]
    if type(value) is NodeResult:
        return [
            "NodeResult",
            *[
                _canonical(getattr(value, name))
                for name in ("table", "data", "artifacts", "warnings", "features")
            ],
        ]
    if isinstance(value, pd.DataFrame):
        dtypes = [
            [str(dtype), _canonical(dtype.categories.tolist()), dtype.ordered]
            if isinstance(dtype, pd.CategoricalDtype)
            else [str(dtype)]
            for dtype in value.dtypes
        ]
        return [
            "DataFrame",
            _canonical(value.index),
            _canonical(value.columns),
            dtypes,
            _canonical(value.to_numpy(dtype=object).tolist()),
            _canonical(value.attrs),
        ]
    if isinstance(value, pd.Index):
        return [
            "Index",
            type(value).__name__,
            str(value.dtype),
            _canonical(list(value.names)),
            _canonical(value.tolist()),
        ]
    if isinstance(value, np.ndarray):
        return ["ndarray", str(value.dtype), list(value.shape), _canonical(value.tolist())]
    if isinstance(value, np.generic):
        return ["numpy", str(value.dtype), _canonical(value.item())]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return [type(value).__name__, value.isoformat()]
    if isinstance(value, (pd.Timedelta, timedelta)):
        return [type(value).__name__, str(value)]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        return ["float", value.hex()]
    if type(value) is str:
        return ["str", value]
    if type(value) in (list, tuple):
        return [type(value).__name__, [_canonical(item) for item in value]]
    if type(value) is dict:
        pairs = [(_canonical(k), _canonical(v)) for k, v in value.items()]
        pairs.sort(key=lambda item: json.dumps(item[0], ensure_ascii=True))
        return ["dict", pairs]
    raise ValueError(f"unsupported fingerprint value type: {type(value).__name__}")


def fingerprint(value):
    payload = json.dumps(_canonical(value), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _implementation_fingerprint():
    # Read trusted installed implementation only, never paths from a workflow.
    # Hash helper modules too: a function-body digest alone misses helper changes.
    root = Path(__file__).resolve().parent
    paths = sorted(root.glob("*.py")) + [root.parent / "common.py", root.parent / "units.py"]
    sources = {
        str(path.relative_to(root.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
        if path.is_file()
    }
    versions = {}
    for package in ("numpy", "pandas", "scipy", "scikit-learn", "statsmodels", "pint"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "not-installed"
    return fingerprint({"version": IMPLEMENTATION_VERSION, "sources": sources, "libraries": versions})


@dataclass
class StepRecord:
    id: str
    operation: str
    status: str
    reason: str
    input_fingerprint: str = ""
    config_fingerprint: str = ""
    implementation_fingerprint: str = ""
    dependency_fingerprints: dict = field(default_factory=dict)
    fingerprint: str = ""
    result_fingerprint: str = ""
    elapsed: float = 0.0
    result: NodeResult | None = None
    diagnostics: dict = field(default_factory=dict)
    _signature: str = field(default="", repr=False)


@dataclass
class AnalysisRun:
    records: dict[str, StepRecord]
    execution_count: int
    reuse_count: int
    status: str


def _signature(record):
    payload = {name: value for name, value in vars(record).items() if name != "_signature"}
    return hmac.new(_AUTH_KEY, fingerprint(payload).encode("ascii"), hashlib.sha256).hexdigest()


def _valid_cache(record):
    if type(record) is not StepRecord or type(record.status) is not str or record.status not in _SUCCESS:
        return False
    try:
        return (
            type(record._signature) is str
            and hmac.compare_digest(record._signature, _signature(record))
            and record.result_fingerprint == fingerprint(record.result)
        )
    except (ValueError, TypeError, AttributeError, RecursionError):
        return False


class AnalysisPlanRunner:
    """Run at most max_executions calls over at most max_steps declared steps.

    This is a call-count budget, not an interrupting wall-clock timeout. Each
    scientific operation retains its own parameter/data-size limits. Previous
    state is an in-memory AnalysisRun capability, not a disk/cache interchange
    format. Do not accept or deserialize pickled state from an external source.
    """

    def __init__(self, *, max_steps=64, max_executions=64):
        for name, value in (("max_steps", max_steps), ("max_executions", max_executions)):
            if type(value) is not int or not 1 <= value <= 256:
                raise ValueError(f"{name} must be an integer from 1 to 256")
        self.max_steps = max_steps
        self.max_executions = max_executions

    def _validate(self, steps, inputs):
        if type(steps) is not list or not steps or len(steps) > self.max_steps:
            raise ValueError("steps must be a nonempty list within max_steps")
        if type(inputs) is not dict or any(type(k) is not str for k in inputs):
            raise ValueError("inputs must map names to DataFrame or NodeResult")
        normalized = {}
        for step in steps:
            if type(step) is not dict or set(step) - {
                "id",
                "operation",
                "config",
                "dependencies",
                "input",
                "source_output",
            }:
                raise ValueError("step requires id, operation, config, dependencies and optional input")
            name, operation = step.get("id"), step.get("operation")
            if type(name) is not str or not name.strip():
                raise ValueError("step id must be a nonempty string")
            if name in normalized:
                raise ValueError(f"duplicate step id: {name}")
            if type(operation) is not str or operation not in PURE_OPERATIONS:
                raise ValueError(f"not an allowed pure operation: {operation}")
            config, deps = step.get("config", {}), step.get("dependencies", [])
            if type(config) is not dict or type(deps) is not list or any(type(d) is not str for d in deps):
                raise ValueError("config must be a mapping; dependencies must be a list of step ids")
            if len(deps) != len(set(deps)):
                raise ValueError("duplicate dependencies are not allowed")
            source = step.get("input", "input" if not deps else None)
            if source is None and not deps:
                raise ValueError("root step requires a named input")
            if source is not None and (type(source) is not str or source not in inputs):
                raise ValueError(f"unknown input: {source}")
            source_output = step.get("source_output", "table")
            if type(source_output) is not str or source_output not in ("table", "features"):
                raise ValueError("source_output must be table or features")
            fingerprint(config)  # Reject executable/custom values before deepcopy can invoke their hooks.
            normalized[name] = {
                "id": name,
                "operation": operation,
                "config": deepcopy(config),
                "dependencies": list(deps),
                "input": source,
                "source_output": source_output,
            }
        for step in normalized.values():
            for dep in step["dependencies"]:
                if dep not in normalized:
                    raise ValueError(f"unknown dependency: {dep}")
        ordered, pending = [], dict(normalized)
        while pending:
            ready = [
                name
                for name, step in pending.items()
                if all(dep not in pending for dep in step["dependencies"])
            ]
            if not ready:
                raise ValueError("analysis plan contains a cycle")
            for name in ready:
                ordered.append(pending.pop(name))
        prepared = {}
        for name, source in inputs.items():
            if isinstance(source, pd.DataFrame):
                source = NodeResult(table=source)
            if type(source) is not NodeResult or source.artifacts:
                raise ValueError("pure inputs must be DataFrame or artifact-free NodeResult")
            fingerprint(source)
            prepared[name] = deepcopy(source)
            for output_name in ("table", "features"):
                frame = getattr(prepared[name], output_name)
                contract = read_contract(frame)
                if contract is not None:
                    setattr(prepared[name], output_name, restore_contract_units(frame, contract))
        return ordered, prepared

    def run(self, steps, inputs, previous=None):
        if previous is not None and type(previous) is not AnalysisRun:
            raise ValueError("previous must be a process-local AnalysisRun")
        if previous is not None and type(previous.records) is not dict:
            raise ValueError("previous must contain process-local records")
        ordered, sources = self._validate(steps, inputs)
        implementation = _implementation_fingerprint()
        resolved = {}
        # Preflight all catalog mappings before any scientific computation.
        for step in ordered:
            key = step["operation"]
            expected = "materials_quality.science." + PURE_OPERATIONS[key]
            if key == "materials.batch_spectra":
                module, function = expected.split(":")
                resolved[key] = getattr(import_module(module), function)
                continue
            entry = next((item for item in catalog.entries() if item["key"] == key), None)
            if entry is None:
                raise ValueError(f"pure operation is unavailable: {key}")
            if entry["function"] != expected:
                raise ValueError(f"pure operation mapping changed: {key}")
            resolved[key] = catalog.get(key)["callable"]
        records, invalidated = {}, set()
        executions = reused = 0
        for step in ordered:
            name, op, deps = step["id"], step["operation"], step["dependencies"]
            record = StepRecord(name, op, "blocked", "dependency_failed")
            record.config_fingerprint = fingerprint(step["config"])
            record.implementation_fingerprint = implementation
            record.dependency_fingerprints = {
                dep: fingerprint([records[dep].fingerprint, records[dep].result_fingerprint]) for dep in deps
            }
            unavailable = [dep for dep in deps if records[dep].status not in _SUCCESS]
            if unavailable:
                record.diagnostics = {"blocked_by": unavailable}
                records[name] = record
                continue
            primary = sources[step["input"]] if step["input"] is not None else records[deps[0]].result
            dependency_tables = [
                getattr(records[dep].result, step["source_output"])
                for dep in deps
                if getattr(records[dep].result, step["source_output"]) is not None
            ]
            if op == "preprocess.merge" and step["config"].get("method") == "specimen":
                dependency_tables = dependency_tables[1:] if step["input"] is None else dependency_tables
            record.input_fingerprint = fingerprint(primary)
            record.fingerprint = fingerprint(
                {
                    "operation": op,
                    "input": record.input_fingerprint,
                    "binding": step["input"],
                    "source_output": step["source_output"],
                    "config": record.config_fingerprint,
                    "implementation": implementation,
                    "dependencies": list(record.dependency_fingerprints.items()),
                }
            )
            old = previous.records.get(name) if previous else None
            record.reason = "no_previous_success"
            if old is not None and not _valid_cache(old):
                record.reason = (
                    "cache_integrity_mismatch"
                    if type(old) is not StepRecord
                    or old.status not in ("failed", "blocked", "budget_exceeded")
                    else "retry_previous_failure"
                )
                invalidated.add(name)
            elif old is not None:
                if old.fingerprint != record.fingerprint:
                    record.reason = "fingerprint_changed"
                elif any(dep in invalidated for dep in deps):
                    record.reason = "dependency_invalidated"
                else:
                    record.result = deepcopy(old.result)
                    record.result_fingerprint = old.result_fingerprint
                    record.diagnostics = deepcopy(old.diagnostics)
                    record.status, record.reason = "reused", "fingerprints_and_integrity_match"
                    record._signature = _signature(record)
                    records[name] = record
                    reused += 1
                    continue
            if any(dep in invalidated for dep in deps):
                invalidated.add(name)
            if executions >= self.max_executions:
                record.status, record.reason = "budget_exceeded", "execution_budget_exhausted"
                records[name] = record
                continue
            executions += 1
            started = time.perf_counter()
            try:
                selected = getattr(primary, step["source_output"])
                if selected is None:
                    raise ValueError(f"selected source_output {step['source_output']} is unavailable")
                if op == "materials.batch_spectra":
                    result = resolved[op](deepcopy(selected), config=deepcopy(step["config"]))
                else:
                    result = resolved[op](
                        deepcopy(selected),
                        config=deepcopy(step["config"]),
                        data=deepcopy(primary.data),
                        tables=deepcopy(dependency_tables),
                    )
                if type(result) is not NodeResult or result.artifacts:
                    raise ValueError("pure operation must return an artifact-free NodeResult")
                source_contract = read_contract(selected)
                if result.table is not None and source_contract is not None:
                    preserving = {
                        "preprocess.filter": "filter",
                        "preprocess.normalize": "normalize",
                        "preprocess.units": "units",
                        "stats.grouped": "grouped",
                    }
                    carried = result.table.attrs.get("contract")
                    if carried is None or carried == source_contract:
                        result.table = propagate_contract(
                            selected, result.table, preserving.get(op, op), step["config"]
                        )
                        for warning in result.table.attrs.get("contract_warnings", []):
                            if warning not in result.warnings:
                                result.warnings.append(warning)
                for output_name in ("table", "features"):
                    output = getattr(result, output_name)
                    contract = read_contract(output)
                    if contract is not None:
                        setattr(result, output_name, restore_contract_units(output, contract))
                record.result_fingerprint = fingerprint(result)
                record.result = deepcopy(result)
                record.diagnostics = {
                    "warnings": deepcopy(result.warnings),
                    "scientific": deepcopy(result.data),
                }
                record.status = "success"
                if result.data.get("execution_status") in {"failed", "partial_failed", "skipped"}:
                    record.status = "failed"
                    record.diagnostics["error_type"] = "ScientificExecutionFailure"
                    record.diagnostics["error"] = (
                        "Scientific operation reported " + result.data["execution_status"]
                    )
            except Exception as exc:
                record.status = "failed"
                record.diagnostics = {"error_type": type(exc).__name__, "error": str(exc)}
            record.elapsed = time.perf_counter() - started
            record._signature = _signature(record)
            records[name] = record
        status = "success" if all(r.status in _SUCCESS for r in records.values()) else "incomplete"
        return AnalysisRun(records, executions, reused, status)


def _json_value(value):
    """Readable JSON audit, distinct from the typed integrity representation."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.DataFrame):
        return _json_value(value.to_dict("records"))
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (pd.Timedelta, timedelta)):
        return str(value)
    if type(value) is float and not math.isfinite(value):
        return None
    if type(value) is dict:
        return {str(k): _json_value(v) for k, v in value.items()}
    if type(value) in (list, tuple):
        return [_json_value(item) for item in value]
    return value


def analysis_plan(table=None, *, config=None, data=None, tables=None):
    """Node adapter. Serialized reports never grant result-cache reuse rights.

    config.steps is the developer interface; a UI may build these steps from
    visual presets. Roots bind to 'input' or to 'table_1', 'table_2', ... .
    """
    config = dict(config or {})
    inputs = {"input": NodeResult(table=table, data=deepcopy(data or {}))}
    for position, frame in enumerate(tables or [], 1):
        inputs[f"table_{position}"] = frame
    run = AnalysisPlanRunner(
        max_steps=config.get("max_steps", 64), max_executions=config.get("max_executions", 64)
    ).run(config.get("steps"), inputs)
    rows, results = [], {}
    for name, record in run.records.items():
        rows.append(
            {
                "id": name,
                "operation": record.operation,
                "status": record.status,
                "reason": record.reason,
                "elapsed_seconds": record.elapsed,
                "fingerprint": record.fingerprint,
            }
        )
        results[name] = {
            "input_fingerprint": record.input_fingerprint,
            "config_fingerprint": record.config_fingerprint,
            "implementation_fingerprint": record.implementation_fingerprint,
            "dependency_fingerprints": record.dependency_fingerprints,
            "result_fingerprint": record.result_fingerprint,
            "diagnostics": _json_value(record.diagnostics),
            "table": _json_value(record.result.table) if record.result else None,
            "table_attrs": _json_value(record.result.table.attrs)
            if record.result and record.result.table is not None
            else None,
            "features": _json_value(record.result.features) if record.result else None,
        }
    depended_on = {dep for step in config["steps"] for dep in step.get("dependencies", [])}
    terminals = [r for name, r in run.records.items() if name not in depended_on]
    features = None
    if len(terminals) == 1 and terminals[0].status in _SUCCESS:
        result = terminals[0].result
        features = deepcopy(result.features if result.features is not None else result.table)
    return NodeResult(
        table=pd.DataFrame(rows),
        features=features,
        data={
            "status": run.status,
            "execution_count": run.execution_count,
            "reuse_count": run.reuse_count,
            "results": results,
            "cache_scope": "explicit process-local AnalysisRun only",
        },
        warnings=[]
        if run.status == "success"
        else ["Some steps failed, were blocked, or exceeded the call budget; inspect diagnostics."],
    )
