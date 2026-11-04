"""Per-cell capacity and retention from cycle summaries or phase-labeled current traces."""

import math
from itertools import groupby

import numpy as np
import pandas as pd

from materials_quality.common import json_value, numeric
from materials_quality.units import _unit

from .contracts import NodeResult, require_table
from .table_contract import attach_contract, make_contract, read_contract, restore_contract_units

CAPACITY_TO_AH = {"Ah": 1.0, "mAh": 0.001}
TIME_TO_H = {"ms": 1 / 3_600_000, "s": 1 / 3600, "min": 1 / 60, "h": 1.0}
CURRENT_TO_A = {"A": 1.0, "mA": 0.001}
DISCHARGE_SIGN = {"discharge_negative": -1, "discharge_positive": 1}
OUTPUT_UNITS = {
    "discharge_capacity_ah": "Ah",
    "charge_capacity_ah": "Ah",
    "baseline_capacity_ah": "Ah",
    "retention_pct": "%",
    "coulombic_efficiency_pct": "%",
}


def _choice(config, field, choices):
    value = config.get(field)
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{field} must explicitly be one of {', '.join(choices)}")
    return choices[value]


def _cycle_number(value):
    try:
        number = numeric(value)
        if 1 <= number <= np.iinfo(np.int64).max and number == number.to_integral_value():
            return int(number)
    except (ValueError, ArithmeticError):
        pass
    raise ValueError("cycle identifiers must be positive integers")


def _valid_cell(value):
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (bool, np.bool_)):
        return False
    return isinstance(value, (int, np.integer)) or (
        isinstance(value, (float, np.floating)) and math.isfinite(value)
    )


def _check_units(frame, declared):
    contract = read_contract(frame)
    if contract is not None:
        restore_contract_units(frame, contract, declared)
        return
    incoming = frame.attrs.get("units", {})
    if not isinstance(incoming, dict):
        raise ValueError("table units must be a mapping")
    for column, unit in declared.items():
        if column in incoming and _unit(incoming[column]) != _unit(unit):
            raise ValueError(f"conflicting units for {column}: {incoming[column]!r} and {unit!r}")


def _capacity(value, factor):
    try:
        capacity = float(numeric(value)) * factor
    except (ValueError, ArithmeticError):
        return None
    return capacity if math.isfinite(capacity) and capacity > 0 else None


def _summary_capacities(block, discharge_column, charge_column, factor):
    if len(block) != 1:
        return None, None, ["duplicate summary rows for this cell and cycle"]
    row = block.iloc[0]
    discharge = _capacity(row[discharge_column], factor)
    charge = _capacity(row[charge_column], factor) if charge_column else None
    reasons = []
    if discharge is None:
        reasons.append("discharge capacity must be finite and positive")
    if charge_column and charge is None:
        reasons.append("charge capacity must be finite and positive")
    return discharge, charge, reasons


def _real_values(values):
    parsed = []
    for value in values:
        if isinstance(value, (complex, np.complexfloating)):
            if value.imag != 0:
                raise ValueError("time and current must be real")
            # Pandas can promote the entire column after one malformed complex value.
            value = value.real
        try:
            parsed.append(float(numeric(value)))
        except (ValueError, ArithmeticError) as exc:
            raise ValueError("time and current must be finite numeric values") from exc
    result = np.asarray(parsed, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError("time and current must be finite numeric values")
    return result


def _integrate_phase(samples, time_column, current_column, time_factor, current_factor, sign, tolerance):
    if len(samples) < 2:
        raise ValueError("requires at least two samples per contiguous run")
    time, current = _real_values(samples[time_column]), _real_values(samples[current_column])
    with np.errstate(over="ignore", invalid="ignore"):
        step_hours = np.diff(time) * time_factor
        current_a = current * (current_factor * sign)
        if np.any(step_hours <= 0) or not np.isfinite(step_hours).all():
            raise ValueError("requires strictly increasing finite elapsed time within each contiguous run")
        if np.any(current_a < -tolerance):
            raise ValueError("current sign disagrees with the declared phase")
        capacity = np.dot(step_hours, current_a[:-1] / 2 + current_a[1:] / 2)
    if not math.isfinite(capacity):
        raise ValueError("integrated capacity must be finite")
    return float(capacity)


def _raw_capacities(block, columns, factors, tolerance, efficiency):
    time_column, current_column, phase_column = columns
    time_factor, current_factor, discharge_sign = factors
    phases = block[phase_column].astype("string").str.strip().str.lower()
    if not phases.isin(["charge", "discharge", "rest"]).all():
        return None, None, ["phase must be charge, discharge or rest"]
    runs = [(phase, sum(1 for _ in rows)) for phase, rows in groupby(phases)]
    totals = {}
    failed = set()
    reasons = []
    start = 0
    for phase, length in runs:
        samples = block.iloc[start : start + length]
        start += length
        if phase == "rest":
            continue
        sign = discharge_sign if phase == "discharge" else -discharge_sign
        try:
            capacity = _integrate_phase(
                samples, time_column, current_column, time_factor, current_factor, sign, tolerance
            )
            totals[phase] = totals.get(phase, 0.0) + capacity
        except ValueError as exc:
            failed.add(phase)
            reasons.append(f"{phase}: {exc}")
    for phase in ("discharge", "charge"):
        capacity = totals.get(phase, 0.0)
        if phase in failed:
            totals.pop(phase, None)
        elif capacity <= 0 or not math.isfinite(capacity):
            totals.pop(phase, None)
            if phase == "discharge" or phase in phases.values or efficiency:
                reasons.append(f"{phase} phase capacity is missing or nonpositive")
    if efficiency and totals.keys() >= {"charge", "discharge"}:
        phase_order = [name for name, _ in runs if name != "rest"]
        if "charge" in phase_order[phase_order.index("discharge") :]:
            reasons.append("all charge runs must precede discharge runs for paired efficiency")
    return totals.get("discharge"), totals.get("charge"), reasons


def _percent(numerator, denominator):
    percent = numerator / denominator * 100
    return percent if math.isfinite(percent) else None


def analyze_battery_cycles(table, config=None):
    """Summarize each observed (cell, cycle); normalization always uses the same cell."""
    c = dict(config or {})
    mode = c.get("mode", "summary")
    baseline_cycle = c.get("baseline_cycle", 0)
    efficiency = c.get("calculate_efficiency", False)
    if type(baseline_cycle) is not int or baseline_cycle < 0:
        raise ValueError("baseline_cycle must be a nonnegative integer (0 selects the first valid cycle)")
    if type(efficiency) is not bool:
        raise ValueError("calculate_efficiency must be a boolean")
    cell_column, cycle_column = c.get("cell_id", "cell_id"), c.get("cycle", "cycle")
    if mode == "summary":
        factor = _choice(c, "capacity_unit", CAPACITY_TO_AH)
        discharge_column, charge_column = (
            c.get("discharge_capacity", "discharge_capacity"),
            c.get("charge_capacity"),
        )
        if efficiency and not charge_column:
            raise ValueError("select a charge_capacity column for Coulombic efficiency")
        declared = {column: c["capacity_unit"] for column in (discharge_column, charge_column) if column}
        measurement_columns = [discharge_column] + ([charge_column] if charge_column else [])
    elif mode == "raw":
        factors = (
            _choice(c, "time_unit", TIME_TO_H),
            _choice(c, "current_unit", CURRENT_TO_A),
            _choice(c, "current_sign", DISCHARGE_SIGN),
        )
        try:
            tolerance = float(numeric(c.get("sign_tolerance_a", 0.0)))
        except (ValueError, ArithmeticError) as exc:
            raise ValueError("sign_tolerance_a must be finite and nonnegative") from exc
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("sign_tolerance_a must be finite and nonnegative")
        measurement_columns = [c.get(column, column) for column in ("time", "current", "phase")]
        declared = dict(zip(measurement_columns[:2], (c["time_unit"], c["current_unit"]), strict=True))
    else:
        raise ValueError("mode must be summary or raw")
    frame = require_table(table, [cell_column, cycle_column, *measurement_columns])
    _check_units(frame, declared)
    if not frame[cell_column].map(_valid_cell).all():
        raise ValueError("cell_id must be a nonempty string or finite numeric identifier")
    selected = frame[[cell_column, cycle_column, *measurement_columns]].reset_index(drop=True)
    selected[cycle_column] = selected[cycle_column].map(_cycle_number)
    cycles = []
    for cell, cell_rows in selected.groupby(cell_column, sort=False, observed=True):
        cell_cycles = []
        for cycle, block in cell_rows.groupby(cycle_column, sort=True, observed=True):
            if mode == "summary":
                discharge, charge, reasons = _summary_capacities(
                    block, discharge_column, charge_column, factor
                )
            else:
                discharge, charge, reasons = _raw_capacities(
                    block, measurement_columns, factors, tolerance, efficiency
                )
            ratio = None
            if efficiency and discharge is not None and charge is not None and not reasons:
                ratio = _percent(discharge, charge)
                if ratio is None:
                    reasons.append("Coulombic efficiency exceeds the finite numeric range")
            cell_cycles.append(
                {
                    "cell_id": json_value(cell),
                    "cycle": int(cycle),
                    "source_row_count": len(block),
                    "source_first_row_position": int(block.index[0]),
                    "discharge_capacity_ah": discharge,
                    "charge_capacity_ah": charge,
                    "coulombic_efficiency_pct": ratio,
                    "reasons": reasons,
                }
            )
        baseline = next(
            (
                row
                for row in cell_cycles
                if row["discharge_capacity_ah"] is not None
                and (baseline_cycle == 0 or row["cycle"] == baseline_cycle)
            ),
            None,
        )
        for row in cell_cycles:
            discharge = row["discharge_capacity_ah"]
            retention = None
            if discharge is not None:
                if baseline is None:
                    row["reasons"].append(
                        f"cell has no valid discharge capacity for baseline cycle {baseline_cycle}"
                    )
                else:
                    retention = _percent(discharge, baseline["discharge_capacity_ah"])
                    if retention is None:
                        row["reasons"].append("retention exceeds the finite numeric range")
            reasons = row.pop("reasons")
            row.update(
                baseline_cycle=baseline["cycle"] if baseline else None,
                baseline_capacity_ah=baseline["discharge_capacity_ah"] if baseline else None,
                retention_pct=retention,
                status="invalid" if discharge is None else ("partial" if reasons else "valid"),
                reason=" | ".join(reasons),
            )
        cycles.extend(cell_cycles)
    counts = {
        status: sum(row["status"] == status for row in cycles) for status in ("valid", "partial", "invalid")
    }
    counts["total"] = len(cycles)
    features = pd.DataFrame(cycles)
    features["baseline_cycle"] = pd.array([row["baseline_cycle"] for row in cycles], dtype="Int64")
    for column in OUTPUT_UNITS:
        features[column] = features[column].astype(float)
    features.attrs["units"] = dict(OUTPUT_UNITS)
    features = attach_contract(
        features,
        make_contract(
            features,
            granularity="point",
            roles={"curve_id": "cell_id", "x": "cycle", "response": "retention_pct"},
            derived_from=[{"operation": "materials.battery_cycles"}],
        ),
    )
    return NodeResult(
        table=frame,
        features=features,
        data={
            "counts": counts,
            "cell_count": int(selected[cell_column].nunique()),
            "cycles": cycles,
            "units": dict(OUTPUT_UNITS),
            "source_units": declared,
            "capacity_method": "instrument_summary" if mode == "summary" else "phase_run_trapezoid",
            "baseline_policy": "first_valid_discharge_per_cell"
            if baseline_cycle == 0
            else "exact_cycle_per_cell",
            "requested_baseline_cycle": baseline_cycle or None,
            "efficiency_requested_for_comparable_cycles": efficiency,
        },
        warnings=["Partial or invalid cycles are retained with reasons."]
        if counts["partial"] or counts["invalid"]
        else [],
    )
