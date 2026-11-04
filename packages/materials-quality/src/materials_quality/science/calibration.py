"""Traceable single-signal calibration with independent standards."""

import numpy as np
from scipy.stats import linregress

from materials_quality.common import groups
from materials_quality.context import table_fingerprint
from materials_quality.units import _unit

from .contracts import numeric_matrix
from .preprocessing import _complete_keys, _result, table_units
from .table_contract import propagate_contract, read_contract, restore_contract_units


def _finite(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a finite number")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not np.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def _reference(frame, config, key, unit_declarations, unit, default=None):
    column = config.get(f"calibration_{key}_column")
    if column:
        if column == config["calibration_signal"]:
            raise ValueError(f"{key} column must differ from the measured signal")
        values = numeric_matrix(frame, [column])[:, 0]
        unit_declarations[column] = unit
        return values, {"column": column}
    value = _finite(config.get(f"calibration_{key}", default), key)
    return value, {"value": value}


def _linear(signal, config):
    pairs = config.get("calibration_standards")
    if not isinstance(pairs, (list, tuple)) or not 3 <= len(pairs) <= 1000:
        raise ValueError("linear calibration requires 3 to 1000 standard pairs")
    if any(not isinstance(pair, (list, tuple)) or len(pair) != 2 for pair in pairs):
        raise ValueError("each calibration standard must be a signal and known value pair")
    x, y = np.array([[_finite(v, "standard value") for v in pair] for pair in pairs]).T
    if len(np.unique(x)) < 3 or len(np.unique(y)) < 2:
        raise ValueError("linear calibration needs three distinct standard signals and nonconstant values")
    fit = linregress(x, y)
    if not np.isfinite([fit.slope, fit.intercept, fit.rvalue, fit.stderr]).all() or fit.slope == 0:
        raise ValueError("linear calibration has an invalid or zero slope")
    low, high = float(x.min()), float(x.max())
    outside = int(np.count_nonzero((signal < low) | (signal > high)))
    allow = config.get("calibration_allow_extrapolation", False)
    if type(allow) is not bool:
        raise ValueError("allow extrapolation must be boolean")
    if outside and not allow:
        raise ValueError(f"{outside} rows fall outside the standards' signal range")
    residuals = y - (fit.intercept + fit.slope * x)
    return fit.intercept + fit.slope * signal, {
        "method": "ordinary least squares on reference standards",
        "slope": fit.slope,
        "intercept": fit.intercept,
        "r_squared": fit.rvalue**2,
        "rmse": _finite(np.sqrt(np.mean(residuals**2)), "calibration residual RMSE"),
        "slope_standard_error": fit.stderr,
        "input_range": [low, high],
        "extrapolated_rows": outside,
        "standards": np.column_stack([x, y]).tolist(),
    }


def _repeatability(frame, corrected, group_by):
    if not group_by:
        return []
    group_by = _complete_keys(frame, group_by)
    rows = []
    for group, positions in groups(frame, group_by):
        values = corrected[positions]
        count = len(values)
        mean = _finite(np.mean(values), "repeat mean")
        sd = _finite(np.std(values, ddof=1), "repeat standard deviation") if count > 1 else None
        rows.append({"group": group, "n": count, "mean": mean, "sd": sd})
    return rows


def calibrate_signal(frame, config, data=None):
    method = config["method"]
    signal_column = config.get("calibration_signal")
    output_column = config.get("calibration_output")
    source = config.get("calibration_source")
    required = {"signal column": signal_column, "output column": output_column, "source": source}
    for name, value in required.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"calibration {name} is required")
    if output_column in frame.columns:
        raise ValueError("calibration output must be a new column")
    signal_unit = config.get("calibration_input_unit")
    unit = _unit(signal_unit)
    contract = read_contract(frame)
    if contract is not None:
        frame = restore_contract_units(frame, contract)
    signal = numeric_matrix(frame, [signal_column])[:, 0]
    declared = {signal_column: signal_unit}
    evidence = {"source": source, "signal_column": signal_column, "input_unit": signal_unit}
    warnings = []
    if method == "linear_calibration":
        output_unit = config.get("calibration_output_unit")
        _unit(output_unit)
        corrected, fit = _linear(signal, config)
        evidence["fit"] = fit
        if fit["extrapolated_rows"]:
            warnings.append(f"{fit['extrapolated_rows']} rows extrapolated beyond calibration standards.")
    else:
        if unit.is_compatible_with("kelvin") and unit != _unit("kelvin"):
            raise ValueError("convert temperatures to kelvin before blank or reference correction")
        blank, evidence["blank"] = _reference(frame, config, "blank", declared, signal_unit, default=0)
        corrected, output_unit = signal - blank, signal_unit
        if method == "reference_ratio":
            reference, evidence["reference"] = _reference(frame, config, "reference", declared, signal_unit)
            denominator = reference - blank
            if np.any(denominator == 0):
                raise ValueError("reference minus blank is zero")
            corrected, output_unit = corrected / denominator, "dimensionless"
    units = table_units(frame, data, declared)
    if not np.isfinite(corrected).all():
        raise ValueError("calibration produced a non-finite result")
    output = frame.copy(deep=True)
    output[output_column] = corrected
    output.attrs["units"] = {**units, output_column: output_unit}
    output = propagate_contract(frame, output, "calibration", {"method": method})
    evidence.update(
        input_sha256=table_fingerprint(frame),
        output_column=output_column,
        output_unit=output_unit,
    )
    return _result(
        frame,
        output,
        method,
        config,
        warnings,
        units=output.attrs["units"],
        calibration=evidence,
        repeatability_by_group=_repeatability(frame, corrected, config.get("group_by")),
        repeatability_scope="Descriptive SD of user-declared repeats, not calibration uncertainty.",
    )
