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


def load_table_path(path: str | Path) -> pd.DataFrame:
    """Load a CSV/TSV/Excel table from an already-authorized path."""
    resolved = Path(path).expanduser()
    suffix = resolved.suffix.casefold()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(resolved)
    if suffix in {".tsv", ".txt"}:
        return pd.read_csv(resolved, sep="\t")
    return pd.read_csv(resolved)


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
    payload = {
        "operation": operation,
        "title": item.get("title", ""),
        "data": _compact_operation_data(_jsonable(getattr(result, "data", result)))
        if compact
        else _jsonable(getattr(result, "data", result)),
        "warnings": _jsonable(getattr(result, "warnings", [])),
    }
    payload["config_normalizations"] = normalization_notes
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
    payload = {
        "operation": "materials.battery_cycles",
        "counts": result.data.get("counts"),
        "cell_count": result.data.get("cell_count"),
        "capacity_unit": options["capacity_unit"],
        "inferred_columns": inferred,
        "cell_filter": cell_value,
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
