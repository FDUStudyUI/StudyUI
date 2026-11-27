"""Deterministic, read-only analysis tools for the StudyUI agent harness.

The canvas engine already owns a registry of validated science operations.  The
dialogue harness could only inspect file *structure*, so it could not answer
numeric questions about an authorized data file without building and running a
workflow.  These helpers expose the same deterministic operations (plus a
battery-cycle summary and a table-quality audit) as bounded tool results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Operations that only read their inputs and return derived results.  Import
# and export nodes are intentionally excluded: they create files or move data.
ALLOWED_OPERATIONS = frozenset(
    {
        "preprocess.filter",
        "preprocess.missing",
        "preprocess.units",
        "preprocess.reshape",
        "preprocess.merge",
        "preprocess.normalize",
        "materials.xrd",
        "materials.spectra",
        "materials.thermal",
        "materials.mechanics",
        "materials.sem_eds",
        "materials.microstructure",
        "materials.chemometrics",
        "stats.grouped",
        "stats.distribution",
        "stats.correlation",
        "stats.significance",
        "stats.multiple",
        "stats.regression",
        "stats.evaluate",
    }
)

MISSING_TOKENS = ("", "NA", "N/A", "na", "null", "None", "none", "-", "--")
MAX_INLINE_CSV_CHARS = 2_000_000
MAX_SUMMARY_COLUMNS = 40
MAX_RESULT_CHARS = 60_000


def _detect_text_delimiter(path: Path) -> str:
    """Detect common instrument-export delimiters without trusting the filename."""
    try:
        sample = path.read_text(encoding="utf-8-sig", errors="replace")[:65536]
    except OSError:
        return ","
    lines = [
        line
        for line in sample.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ][:20]
    if not lines:
        return ","
    counts = {
        ",": sum(line.count(",") for line in lines),
        ";": sum(line.count(";") for line in lines),
        "\t": sum(line.count("\t") for line in lines),
        "|": sum(line.count("|") for line in lines),
    }
    delimiter, count = max(counts.items(), key=lambda item: item[1])
    return delimiter if count else ","


def load_table_path(path: str | Path) -> pd.DataFrame:
    """Load a CSV/TSV/Excel table from an already-authorized path.

    Instrument exports often carry a leading comment line, a BOM, or a
    semicolon delimiter while still using a ``.csv`` suffix.  Read those
    deterministically instead of forcing the model into a blind retry loop.
    Excel files keep the normal workbook reader.
    """
    resolved = Path(path).expanduser()
    suffix = resolved.suffix.casefold()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(resolved)
    delimiter = "\t" if suffix in {".tsv", ".txt"} else _detect_text_delimiter(resolved)
    try:
        frame = pd.read_csv(
            resolved,
            sep=delimiter,
            comment="#",
            engine="python",
            encoding="utf-8-sig",
        )
    except (pd.errors.ParserError, UnicodeDecodeError):
        frame = pd.read_csv(resolved, sep=delimiter, comment="#", encoding="utf-8-sig")
    if frame.shape[1] == 1:
        # A quoted field can hide the real delimiter from a naive count; retry
        # with Python's sniffer only after the deterministic read failed.
        frame = pd.read_csv(
            resolved,
            sep=None,
            comment="#",
            engine="python",
            encoding="utf-8-sig",
        )
    return frame


def load_inline_table(text: str) -> pd.DataFrame:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("table_csv must be a nonempty CSV string")
    if len(text) > MAX_INLINE_CSV_CHARS:
        raise ValueError(f"table_csv exceeds {MAX_INLINE_CSV_CHARS} characters")
    import io

    return pd.read_csv(io.StringIO(text))


def _jsonable(value: Any) -> Any:
    from materials_quality.science_tools import _jsonable as convert

    return convert(value)


def _table_summary(frame: pd.DataFrame, columns: int = MAX_SUMMARY_COLUMNS) -> dict:
    """Aggregate the local table without returning measurement rows to the model."""
    numeric = frame.select_dtypes(include="number")
    summary = {}
    for column in list(numeric.columns)[:columns]:
        series = pd.to_numeric(numeric[column], errors="coerce").dropna()
        if series.empty:
            continue
        summary[str(column)] = {
            "count": int(series.count()),
            "min": float(series.min()),
            "max": float(series.max()),
            "mean": float(series.mean()),
        }
    return {
        "columns": [str(column) for column in frame.columns],
        "row_count": int(len(frame)),
        "numeric_summary": summary,
        "rows_returned": 0,
        "note": "Aggregate statistics only; raw measurement rows stay in the local tool.",
    }


def _bounded(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return payload
    # Keep the scalar data and drop previews before giving up the result.
    payload.pop("table", None)
    payload.pop("features", None)
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        payload["truncated"] = True
        return payload
    return {
        "operation": payload.get("operation"),
        "truncated": True,
        "chars": len(text),
        "note": "结果超过 60,000 字符；请缩小请求范围或改用具名摘要工具。",
        "data_keys": sorted(payload.get("data", {})) if isinstance(payload.get("data"), dict) else [],
    }


_COMPACT_DROP_KEYS = frozenset(
    {
        "transform",
        "fit_source_rows",
        "train_fingerprints",
        "test_fingerprints",
        "train_positions",
        "test_positions",
        "train_ids",
        "test_ids",
        "model_path",
        "manifest_path",
        "scaler_mean",
        "parameters",
        "preprocessing",
        "curve_convention",
        "last_measured_strain",
        "work_density_MJ_m3",
        "fit_intercept_MPa",
        "yield_offset_fraction",
        "fit_range_fraction",
        "fit_r_squared",
        "peak_detection",
        "fwhm_definition",
        "left_base_index",
        "right_base_index",
        "area_between_bases",
        "index",
        "onset_method",
        "tangent_slope",
        "baseline_level",
        "plateau_range",
        "plateau_rate_limit",
        "removed_positions",
        "retained_positions",
        "row_positions",
    }
)


def _compact_operation_data(data):
    if not isinstance(data, dict):
        return data
    compact = {key: value for key, value in data.items() if key not in _COMPACT_DROP_KEYS}
    if isinstance(compact.get("peaks"), list):
        compact["peaks"] = [
            {key: value for key, value in peak.items() if key not in _COMPACT_DROP_KEYS}
            for peak in compact["peaks"]
            if isinstance(peak, dict)
        ]
    if isinstance(compact.get("stages"), list):
        compact["stages"] = [
            {key: value for key, value in stage.items() if key not in _COMPACT_DROP_KEYS}
            for stage in compact["stages"]
            if isinstance(stage, dict)
        ]
    return compact


def _normalize_operation_config(operation: str, config: dict | None) -> tuple[dict, list[str]]:
    """Normalize common unit/split aliases and report every change to the model."""
    normalized = dict(config or {})
    notes: list[str] = []

    def key(value) -> str:
        return str(value).strip().casefold()

    if operation == "materials.thermal":
        if "kind" in normalized:
            alias = {
                "tg": "tg",
                "tga": "tg",
                "thermogravimetric": "tg",
                "thermogravimetry": "tg",
                "dsc": "dsc",
                "differential scanning calorimetry": "dsc",
            }.get(key(normalized["kind"]))
            if alias:
                normalized["kind"] = alias
            else:
                # The registered operation defaults to tg; an unrecognized kind is
                # safer to normalize than to fail and retry.
                notes.append(f"kind={normalized['kind']!r} is invalid; using tg")
                normalized["kind"] = "tg"
        x_units = {
            "c": "degC",
            "°c": "degC",
            "celsius": "degC",
            "degree celsius": "degC",
            "degc": "degC",
            "k": "K",
            "kelvin": "K",
            "s": "s",
            "min": "min",
        }
        y_units = {"percent": "%", "pct": "%", "%": "%", "mg": "mg", "g": "g"}
        if "x_unit" in normalized and key(normalized["x_unit"]) in x_units:
            normalized["x_unit"] = x_units[key(normalized["x_unit"])]
        if "y_unit" in normalized and key(normalized["y_unit"]) in y_units:
            normalized["y_unit"] = y_units[key(normalized["y_unit"])]
    elif operation == "materials.mechanics":
        strain_units = {
            "fraction": "fraction",
            "fractional": "fraction",
            "%": "%",
            "percent": "%",
            "percentage": "%",
        }
        stress_units = {"pa": "Pa", "kpa": "kPa", "mpa": "MPa", "gpa": "GPa"}
        if "strain_unit" in normalized and key(normalized["strain_unit"]) in strain_units:
            normalized["strain_unit"] = strain_units[key(normalized["strain_unit"])]
        if "stress_unit" in normalized and key(normalized["stress_unit"]) in stress_units:
            normalized["stress_unit"] = stress_units[key(normalized["stress_unit"])]
    elif operation == "materials.xrd":
        x_units = {
            "degree": "2theta_deg",
            "degrees": "2theta_deg",
            "2theta": "2theta_deg",
            "2-theta": "2theta_deg",
            "two_theta_deg": "2theta_deg",
        }
        if "x_unit" in normalized and key(normalized["x_unit"]) in x_units:
            normalized["x_unit"] = x_units[key(normalized["x_unit"])]
    elif operation == "stats.regression":
        if "features" not in normalized:
            for alias in ("feature", "x", "predictors", "feature_columns"):
                value = normalized.get(alias)
                if isinstance(value, str):
                    normalized["features"] = [value]
                    notes.append(f"features taken from {alias}")
                    break
                if isinstance(value, (list, tuple)) and value:
                    normalized["features"] = [str(item) for item in value]
                    notes.append(f"features taken from {alias}")
                    break
        if "target" not in normalized:
            for alias in ("y", "target_column", "response", "label"):
                if alias in normalized:
                    normalized["target"] = str(normalized[alias])
                    notes.append(f"target taken from {alias}")
                    break
        if "model_method" not in normalized and "model" in normalized:
            normalized["model_method"] = str(normalized["model"])
            notes.append("model_method taken from model")
        if "validation_split" in normalized:
            split = key(normalized["validation_split"])
            alias = {
                "random": "random",
                "chronological": "chronological_split",
                "chronological_split": "chronological_split",
                "temporal": "chronological_split",
                "time": "chronological_split",
                "blocked": "blocked_cv",
                "blocked_cv": "blocked_cv",
            }.get(split)
            if alias:
                normalized["validation_split"] = alias
            else:
                notes.append(f"validation_split={normalized['validation_split']!r} is invalid; using random")
                normalized["validation_split"] = "random"
        if (
            normalized.get("validation_split") == "chronological_split"
            and not normalized.get("time_column")
        ):
            notes.append("temporal validation requires time_column; using random")
            normalized["validation_split"] = "random"
    elif operation == "stats.significance":
        if "method" not in normalized and "test" in normalized:
            normalized["method"] = str(normalized["test"])
            notes.append("method taken from test")
        if "group" not in normalized:
            for alias in ("group_column", "group_by", "by", "grouping"):
                if alias in normalized:
                    normalized["group"] = str(normalized[alias])
                    notes.append(f"group taken from {alias}")
                    break
        if "groups" not in normalized and "group_order" in normalized:
            order = normalized["group_order"]
            if isinstance(order, (list, tuple)) and len(order) >= 2:
                normalized["groups"] = [str(item) for item in order]
                notes.append("groups taken from group_order; mean_difference = groups[0] - groups[1]")
        if "column" not in normalized:
            for alias in ("value", "value_column", "measure", "measure_column"):
                if alias in normalized:
                    normalized["column"] = str(normalized[alias])
                    notes.append(f"column taken from {alias}")
                    break
        if "column" not in normalized:
            columns = normalized.get("columns")
            if isinstance(columns, str):
                normalized["column"] = columns
                notes.append("column taken from columns")
            elif isinstance(columns, (list, tuple)) and len(columns) == 1:
                normalized["column"] = str(columns[0])
                notes.append("column taken from columns")
    elif operation == "stats.distribution":
        if "column" not in normalized and "columns" in normalized:
            columns = normalized.pop("columns")
            if isinstance(columns, str):
                normalized["column"] = columns
            elif isinstance(columns, (list, tuple)) and len(columns) == 1:
                normalized["column"] = str(columns[0])
            else:
                normalized["columns"] = columns
    return normalized, notes


def _apply_requested_preprocessing(
    table: pd.DataFrame, config: dict
) -> tuple[pd.DataFrame, list[str], dict]:
    """Apply explicit, auditable row cleanup before a statistics operation.

    The dialogue harness has no chained table node, so a model cannot easily
    hand a deduplicated frame to a test.  These opt-in flags perform only the
    requested deterministic cleanup and return counts; they never silently
    impute or drop data otherwise.
    """
    options = dict(config or {})
    notes: list[str] = []
    summary: dict = {"input_rows": int(len(table)), "input_columns": int(len(table.columns))}
    if options.pop("deduplicate", False) is True:
        before = len(table)
        table = table.drop_duplicates().reset_index(drop=True)
        summary["duplicate_rows_removed"] = int(before - len(table))
        notes.append(
            f"removed {summary['duplicate_rows_removed']} exact duplicate row(s) before the operation"
        )
    raw_missing = options.pop(
        "drop_missing",
        options.pop("drop_missing_columns", options.pop("drop_missing_rows", None)),
    )
    missing_subset = None
    if raw_missing is True:
        missing_subset = list(table.columns)
    elif isinstance(raw_missing, str):
        missing_subset = [raw_missing]
    elif isinstance(raw_missing, (list, tuple)):
        missing_subset = [str(column) for column in raw_missing]
    if missing_subset is not None:
        unknown = [column for column in missing_subset if column not in table.columns]
        if unknown:
            raise ValueError(
                f"drop_missing columns not found: {unknown}; available_columns={list(table.columns)}"
            )
        before = len(table)
        table = table.dropna(subset=missing_subset).reset_index(drop=True)
        summary["rows_with_missing_removed"] = int(before - len(table))
        notes.append(
            f"removed {summary['rows_with_missing_removed']} row(s) with missing values in "
            f"{missing_subset} before the operation"
        )
    raw_filters = options.pop("row_filters", options.pop("filters", None))
    if raw_filters is not None:
        if not isinstance(raw_filters, (list, tuple)):
            raise ValueError("row_filters must be a list of {column, op, value} objects")
        before = len(table)
        for raw_filter in raw_filters:
            if not isinstance(raw_filter, dict):
                raise ValueError("each row_filter must be an object")
            column = raw_filter.get("column")
            op = str(raw_filter.get("op") or raw_filter.get("operator") or "").casefold()
            value = raw_filter.get("value")
            if not isinstance(column, str) or column not in table.columns:
                raise ValueError(
                    f"row_filter column not found: {column!r}; available_columns={list(table.columns)}"
                )
            series = table[column]
            numeric = pd.to_numeric(series, errors="coerce")
            parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
            try:
                if op in {">=", "ge"}:
                    mask = numeric >= float(parsed)
                elif op in {">", "gt"}:
                    mask = numeric > float(parsed)
                elif op in {"<=", "le"}:
                    mask = numeric <= float(parsed)
                elif op in {"<", "lt"}:
                    mask = numeric < float(parsed)
                elif op in {"==", "=", "eq"}:
                    mask = series.astype(str) == str(value)
                elif op in {"!=", "ne"}:
                    mask = series.astype(str) != str(value)
                elif op in {"in", "not_in"}:
                    if not isinstance(value, (list, tuple)):
                        raise ValueError("row_filter in/not_in requires a list value")
                    allowed = {str(item) for item in value}
                    mask = series.astype(str).isin(allowed)
                    if op == "not_in":
                        mask = ~mask
                elif op in {"between", "range"}:
                    if not isinstance(value, (list, tuple)) or len(value) != 2:
                        raise ValueError("row_filter between requires [low, high]")
                    mask = (numeric >= float(value[0])) & (numeric <= float(value[1]))
                else:
                    raise ValueError(
                        f"unsupported row_filter op {op!r}; use >=, >, <=, <, ==, !=, in, not_in or between"
                    )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid row_filter for {column!r}: {exc}"
                ) from exc
            table = table[mask.fillna(False)].reset_index(drop=True)
        summary["rows_filtered_removed"] = int(before - len(table))
        notes.append(
            f"removed {summary['rows_filtered_removed']} row(s) with {len(raw_filters)} explicit row_filter(s)"
        )
    summary["output_rows"] = int(len(table))
    return table, notes, summary


def _regression_outlier_candidates(table: pd.DataFrame | None, config: dict) -> list[dict]:
    """Return a few large-residual rows for a one-feature OLS trend.

    This is an aggregate diagnostic, not a data dump: at most three rows, with
    the feature, target, fitted value and residual.  It gives the dialogue
    harness enough evidence to apply a scientific outlier guard without
    exposing the full measurement table.
    """
    if not isinstance(table, pd.DataFrame):
        return []
    features = config.get("features")
    target = config.get("target")
    if not isinstance(features, list) or len(features) != 1 or not isinstance(target, str):
        return []
    feature = str(features[0])
    if feature not in table.columns or target not in table.columns:
        return []
    values = pd.to_numeric(table[feature], errors="coerce")
    target_values = pd.to_numeric(table[target], errors="coerce")
    valid = values.notna() & target_values.notna()
    x = values[valid].to_numpy(dtype=float)
    y = target_values[valid].to_numpy(dtype=float)
    if len(x) < 5 or np.ptp(x) == 0:
        return []
    try:
        slope, intercept = np.polyfit(x, y, 1)
    except (TypeError, ValueError, np.linalg.LinAlgError):
        return []
    fitted = slope * x + intercept
    residual = y - fitted
    order = np.argsort(np.abs(residual))[::-1][:3]
    positions = np.flatnonzero(valid)
    id_column = config.get("id_column")
    candidates = []
    for index in order:
        row_position = int(positions[index])
        item = {
            "row_position": row_position,
            "x": float(x[index]),
            "observed": float(y[index]),
            "fitted": float(fitted[index]),
            "residual": float(residual[index]),
        }
        if isinstance(id_column, str) and id_column in table.columns:
            item["id"] = _jsonable(table.iloc[row_position][id_column])
        candidates.append(item)
    return candidates


def execute_operation(
    operation: str,
    *,
    table: pd.DataFrame | None = None,
    config: dict | None = None,
    data: dict | None = None,
    compact: bool = False,
) -> dict:
    """Run one allowlisted science operation and return a bounded JSON payload."""
    from materials_quality.science import catalog

    if operation not in ALLOWED_OPERATIONS:
        raise ValueError(
            f"operation {operation!r} is not available to the dialogue harness; "
            "use one of: " + ", ".join(sorted(ALLOWED_OPERATIONS))
        )
    item = catalog.get(operation)
    config, normalization_notes = _normalize_operation_config(operation, config)
    data = dict(data or {})
    columns = [str(column) for column in table.columns] if isinstance(table, pd.DataFrame) else []
    preprocessing_notes: list[str] = []
    preprocessing: dict = {}
    if isinstance(table, pd.DataFrame):
        table, preprocessing_notes, preprocessing = _apply_requested_preprocessing(table, config)
        columns = [str(column) for column in table.columns]
    try:
        result = item["callable"](table, config=config, data=data)
    except TypeError:
        # Some registered operations accept only table/config.  Preserve the
        # first signature's TypeError only when the fallback fails.
        try:
            result = item["callable"](table, config=config)
        except (ValueError, KeyError, TypeError) as inner:
            raise ValueError(
                f"{operation}: {inner}; available_columns={columns}; check the operation's "
                "required config fields and units."
            ) from inner
    except (ValueError, KeyError) as exc:
        raise ValueError(
            f"{operation}: {exc}; available_columns={columns}; check the operation's required "
            "config fields and units."
        ) from exc
    result_data = _jsonable(getattr(result, "data", result))
    if operation == "stats.regression" and isinstance(result_data, dict):
        candidates = _regression_outlier_candidates(table, config)
        if candidates:
            result_data["outlier_candidates"] = candidates
    payload = {
        "operation": operation,
        "title": item.get("title", ""),
        "data": _compact_operation_data(result_data) if compact else result_data,
        "warnings": _jsonable(getattr(result, "warnings", [])),
    }
    payload["config_normalizations"] = normalization_notes
    if preprocessing_notes:
        payload["preprocessing"] = {**preprocessing, "notes": preprocessing_notes}
    if compact:
        return _bounded(payload)
    payload["table"] = (
        _table_summary(getattr(result, "table", None))
        if isinstance(getattr(result, "table", None), pd.DataFrame)
        else None
    )
    features = getattr(result, "features", None)
    if isinstance(features, pd.DataFrame):
        payload["features"] = _table_summary(features)
    return _bounded(payload)


def _compact_cycle(row: dict) -> dict:
    keys = (
        "cell_id",
        "cycle",
        "discharge_capacity_mAh_g",
        "charge_capacity_mAh_g",
        "coulombic_efficiency_pct",
        "retention_pct",
        "status",
        "reason",
    )
    return {key: row.get(key) for key in keys}


def battery_summary(
    table: pd.DataFrame, config: dict | None = None, *, compact: bool = False
) -> dict:
    """Summarize per-cycle battery capacity, retention and Coulombic efficiency."""
    from materials_quality.science.battery import analyze_battery_cycles

    options = {
        "mode": "summary",
        "capacity_unit": "mAh",
        "cell_id": "cell_id",
        "cycle": "cycle",
        "discharge_capacity": "discharge_capacity",
        "charge_capacity": "charge_capacity",
        "calculate_efficiency": True,
        "baseline_cycle": 0,
    }
    options.update(config or {})
    frame = table.copy()

    def candidates_for(key: str) -> list[str]:
        lowered = {str(column).casefold(): str(column) for column in frame.columns}
        if key in {"discharge_capacity", "charge_capacity"}:
            if key == "discharge_capacity":
                return [
                    original
                    for lowered_name, original in lowered.items()
                    if "discharge" in lowered_name and "capacity" in lowered_name
                ]
            return [
                original
                for lowered_name, original in lowered.items()
                if "charge" in lowered_name
                and "discharge" not in lowered_name
                and "capacity" in lowered_name
            ]
        if key == "cell_id":
            exact = [
                lowered[name]
                for name in ("cell_id", "cell", "sample_id", "specimen_id")
                if name in lowered
            ]
            return exact or [
                original for lowered_name, original in lowered.items() if "cell" in lowered_name
            ]
        if key == "cycle":
            exact = [
                lowered[name]
                for name in ("cycle", "cycle_number", "cycle_index")
                if name in lowered
            ]
            return exact or [
                original for lowered_name, original in lowered.items() if "cycle" in lowered_name
            ]
        return []

    inferred: dict[str, str] = {}
    explicit_keys = set(config or {})
    for key in ("cell_id", "cycle", "discharge_capacity", "charge_capacity"):
        configured = str(options[key])
        if configured in frame.columns:
            continue
        # Never silently override a column the caller explicitly named.
        if key in explicit_keys:
            continue
        candidates = candidates_for(key)
        if len(candidates) == 1:
            options[key] = candidates[0]
            inferred[key] = candidates[0]
    if "capacity_unit" not in (config or {}):
        discharge_name = str(options["discharge_capacity"]).casefold()
        options["capacity_unit"] = "Ah" if "ah" in discharge_name and "mah" not in discharge_name else "mAh"
    unit_map = {"mah": "mAh", "ah": "Ah", "ma h": "mAh"}
    options["capacity_unit"] = unit_map.get(
        str(options["capacity_unit"]).casefold(), options["capacity_unit"]
    )
    cell_value = options.get("cell_value") or options.get("cell")
    if options["cell_id"] not in frame.columns:
        raw = str(options["cell_id"])
        candidates = [column for column in candidates_for("cell_id") if column in frame.columns]
        matches = [
            column for column in candidates if (frame[column].astype(str) == raw).any()
        ]
        if len(matches) == 1:
            options["cell_id"] = matches[0]
            cell_value = raw
            inferred["cell_id"] = matches[0]
    if cell_value is not None and options["cell_id"] in frame.columns:
        frame = frame[frame[options["cell_id"]].astype(str) == str(cell_value)].reset_index(drop=True)
    required = {
        "cell_id": str(options["cell_id"]),
        "cycle": str(options["cycle"]),
        "discharge_capacity": str(options["discharge_capacity"]),
        "charge_capacity": str(options["charge_capacity"]),
    }
    missing = {key: value for key, value in required.items() if value not in frame.columns}
    if missing:
        candidate_map = {key: candidates_for(key) for key in missing}
        raise ValueError(
            f"battery columns not found: {missing}; candidates={candidate_map}; "
            f"available_columns={list(frame.columns)}; pass config.cell_id, config.cycle, "
            "config.discharge_capacity and config.charge_capacity with the exact column names."
        )
    # The canonical operation reports Ah.  Keep the user's labels and units in
    # the summary so the dialogue never has to re-derive mAh from Ah silently.
    factor = {"Ah": 1.0, "mAh": 0.001}.get(str(options["capacity_unit"]))
    if factor is None:
        raise ValueError("capacity_unit must be Ah or mAh")
    result = analyze_battery_cycles(frame, config=options)
    cycles = result.data.get("cycles", [])
    valid = [row for row in cycles if row.get("status") == "valid"]
    for row in cycles:
        row["discharge_capacity_mAh_g"] = (
            None if row.get("discharge_capacity_ah") is None else row["discharge_capacity_ah"] * 1000.0
        )
        row["charge_capacity_mAh_g"] = (
            None if row.get("charge_capacity_ah") is None else row["charge_capacity_ah"] * 1000.0
        )
    efficiencies = [
        row["coulombic_efficiency_pct"]
        for row in valid[1:]
        if row.get("coulombic_efficiency_pct") is not None
    ]
    mean_efficiency = sum(efficiencies) / len(efficiencies) if efficiencies else None
    last = cycles[-1] if cycles else None
    first = cycles[0] if cycles else None
    cell_summaries: list[dict] = []
    if cell_value is None and "cell_id" in frame.columns:
        grouped: dict[str, list[dict]] = {}
        for row in cycles:
            grouped.setdefault(str(row.get("cell_id")), []).append(row)
        for cell_name, rows in grouped.items():
            cell_valid = [row for row in rows if row.get("status") == "valid"]
            cell_efficiencies = [
                row["coulombic_efficiency_pct"]
                for row in cell_valid[1:]
                if row.get("coulombic_efficiency_pct") is not None
            ]
            status_counts = {"valid": 0, "partial": 0, "invalid": 0}
            for row in rows:
                status = str(row.get("status") or "invalid")
                if status in status_counts:
                    status_counts[status] += 1
            cell_last = rows[-1] if rows else None
            cell_summaries.append(
                {
                    "cell_id": cell_name,
                    "counts": {**status_counts, "total": len(rows)},
                    "invalid_or_partial_rows": status_counts["invalid"] + status_counts["partial"],
                    "first_cycle": _compact_cycle(cell_valid[0]) if cell_valid else None,
                    "last_cycle": _compact_cycle(cell_last) if cell_last else None,
                    "retention_pct_at_last_cycle": cell_last.get("retention_pct") if cell_last else None,
                    "mean_coulombic_efficiency_pct_cycles_2_to_last": (
                        sum(cell_efficiencies) / len(cell_efficiencies) if cell_efficiencies else None
                    ),
                    "efficiency_cycle_count": len(cell_efficiencies),
                }
            )
    payload = {
        "operation": "materials.battery_cycles",
        "counts": result.data.get("counts"),
        "invalid_or_partial_rows": int(
            (result.data.get("counts") or {}).get("invalid", 0)
            + (result.data.get("counts") or {}).get("partial", 0)
        ),
        "invalid_rows": int(
            (result.data.get("counts") or {}).get("invalid", 0)
            + (result.data.get("counts") or {}).get("partial", 0)
        ),
        "invalid_rows_definition": "invalid plus partial capacity rows (missing or non-positive capacity)",
        "cell_count": result.data.get("cell_count"),
        "capacity_unit": options["capacity_unit"],
        "inferred_columns": inferred,
        "cell_filter": cell_value,
        "cell_summaries": cell_summaries,
        "first_cycle": _compact_cycle(first) if first else None,
        "last_cycle": _compact_cycle(last) if last else None,
        "retention_pct_at_last_cycle": last.get("retention_pct") if last else None,
        "mean_coulombic_efficiency_pct_cycles_2_to_last": mean_efficiency,
        "efficiency_cycle_count": len(efficiencies),
        "cycles_preview": [_compact_cycle(row) for row in cycles[:5]]
        + ([] if len(cycles) <= 10 else [{"omitted_cycles": len(cycles) - 10}])
        + [_compact_cycle(row) for row in cycles[-5:]]
        if len(cycles) > 5
        else [_compact_cycle(row) for row in cycles],
        "warnings": _jsonable(result.warnings),
    }
    if compact:
        payload.pop("cycles_preview", None)
    return _bounded(payload)


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def audit_table_quality(
    table: pd.DataFrame, config: dict | None = None, *, compact: bool = False
) -> dict:
    """Count missing cells, exact duplicate rows, negative values and range violations."""
    options = dict(config or {})
    missing_tokens = options.get("missing_tokens") or list(MISSING_TOKENS)
    missing_tokens = [str(token) for token in missing_tokens]
    frame = table.copy()
    missing_mask = frame.isna()
    for column in frame.columns:
        text = frame[column].astype("string")
        missing_mask[column] = missing_mask[column] | text.isin(missing_tokens)
    missing_by_column = {str(column): int(missing_mask[column].sum()) for column in frame.columns}
    raw_negative = options.get("negative_columns") or []
    if isinstance(raw_negative, str):
        raw_negative = [raw_negative]
    negative_columns = [str(column) for column in raw_negative]
    negative = {}
    for column in negative_columns:
        if column not in frame.columns:
            raise ValueError(f"negative_columns contains unknown column {column!r}")
        negative[column] = int((_numeric(frame, column) < 0).sum())
    raw_ranges = options.get("ranges") or {}
    ranges: dict[str, list] = {}
    if isinstance(raw_ranges, dict):
        for column, bounds in raw_ranges.items():
            if isinstance(bounds, dict):
                low = bounds.get("min", bounds.get("minimum", bounds.get("low")))
                high = bounds.get("max", bounds.get("maximum", bounds.get("high")))
            elif isinstance(bounds, (list, tuple)) and len(bounds) == 2:
                low, high = bounds
            else:
                raise ValueError("each range must be [minimum, maximum] or {min, max}")
            ranges[str(column)] = [low, high]
    elif isinstance(raw_ranges, list):
        for entry in raw_ranges:
            if isinstance(entry, dict):
                column = entry.get("column") or entry.get("name")
                low = entry.get("min", entry.get("minimum", entry.get("low")))
                high = entry.get("max", entry.get("maximum", entry.get("high")))
            elif isinstance(entry, (list, tuple)) and len(entry) == 3:
                column, low, high = entry
            else:
                raise ValueError(
                    "range list entries must be [column, minimum, maximum] or {column,min,max}"
                )
            if not column:
                raise ValueError("each range must name a column")
            ranges[str(column)] = [low, high]
    else:
        raise ValueError("ranges must map a column to [minimum, maximum]")
    out_of_range = {}
    for column, bounds in ranges.items():
        column = str(column)
        if column not in frame.columns:
            raise ValueError(f"ranges contains unknown column {column!r}")
        values = _numeric(frame, column)
        low, high = bounds
        below = 0 if low is None else int((values < float(low)).sum())
        above = 0 if high is None else int((values > float(high)).sum())
        out_of_range[column] = {"below": below, "above": above, "total": below + above}
    payload = {
        "operation": "table.quality_audit",
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "missing_cells": int(missing_mask.to_numpy().sum()),
        "missing_by_column": missing_by_column,
        "duplicate_rows": int(frame.duplicated().sum()),
        "negative_values": negative,
        "out_of_range": out_of_range,
        "assumptions": [
            "Missing means NaN or an explicitly supplied missing token.",
            "Duplicate rows are exact repeats of an earlier row across all columns.",
            "Range checks parse numeric values; non-numeric entries are not counted as violations.",
        ],
    }
    if compact:
        payload.pop("assumptions", None)
        payload.pop("missing_by_column", None)
    return payload
