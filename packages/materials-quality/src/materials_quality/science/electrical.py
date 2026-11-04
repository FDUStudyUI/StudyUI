"""Windowed electrical measurements in acquisition order with per-curve diagnostics."""

import json
from numbers import Real

import numpy as np
import pandas as pd

from materials_quality.common import json_value, validate_table
from materials_quality.units import _unit

from .contracts import NodeResult, numeric_matrix, require_table
from .table_contract import attach_contract, make_contract, read_contract, restore_contract_units

OPERATION = "materials.electrical"
PHOTO_TIMES = (
    "baseline_start",
    "baseline_end",
    "light_on",
    "on_plateau_start",
    "on_plateau_end",
    "light_off",
    "recovery_end",
)
IV_FEATURE_UNITS = {
    "fit_voltage_min_V": "V",
    "fit_voltage_max_V": "V",
    "slope_A_per_V": "A/V",
    "intercept_A": "A",
    "conductance_S": "S",
    "resistance_ohm": "ohm",
    "r_squared": "dimensionless",
    "residual_rmse_A": "A",
}
PHOTO_FEATURE_UNITS = {
    "baseline_A": "A",
    "on_plateau_A": "A",
    "amplitude_A": "A",
    "rise_time_s": "s",
    "recovery_time_s": "s",
}


def _scale(c, key, target):
    declared = c.get(key)
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError(f"explicit {key} is required")
    unit = _unit(declared)
    base = _unit(target)
    if unit.dimensionality != base.dimensionality:
        raise ValueError(f"{key} must be compatible with {target}")
    scale = float((1 * unit).to(base).magnitude)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError(f"{key} requires a finite positive scale")
    return scale


def _coordinates(c, keys, scale):
    values = [c.get(k) for k in keys]
    if any(isinstance(v, (bool, np.bool_)) or not isinstance(v, Real) for v in values):
        raise ValueError(f"explicit numeric coordinates required: {', '.join(keys)}")
    converted = tuple(float(v) * scale for v in values)
    if not np.isfinite(converted).all():
        raise ValueError("coordinates must be finite in SI units")
    return converted


def _window(x, start, end):
    return (x >= start) & (x <= end)


def _iv(x, y, domain, points):
    delta = np.diff(x)
    if len(x) < 3:
        raise ValueError("at least three measurements are required per sweep")
    if not (np.all(delta > 0) or np.all(delta < 0)):
        raise ValueError("ambiguous sweep: voltage must strictly increase or decrease in acquisition order")
    mask = _window(x, *domain)
    points["in_fit_domain"] = mask
    v, i = x[mask], y[mask]
    if len(v) < 3:
        raise ValueError("the fit window contains fewer than three distinct voltage points")

    # Subtract an observed value before computing means to avoid fabricating
    # variation for exactly constant currents or losing small changes to offsets.
    relative_v, relative_i = v - v[0], i - i[0]
    v_offset, i_offset = relative_v.mean(), relative_i.mean()
    centered_v, centered_i = relative_v - v_offset, relative_i - i_offset
    span = np.max(np.abs(centered_v))
    normalized_v = centered_v / span
    slope = float((normalized_v @ centered_i) / (normalized_v @ normalized_v) / span)
    intercept = float((i[0] + i_offset) - slope * (v[0] + v_offset))
    fitted = i[0] + (i_offset + slope * centered_v)
    residual = centered_i - slope * centered_v
    rmse = float(np.linalg.norm(residual) / np.sqrt(len(v)))
    spread = float(np.linalg.norm(centered_i))
    r_squared = 1 - (np.linalg.norm(residual) / spread) ** 2 if spread > 0 else None
    if not np.isfinite([slope, intercept, rmse]).all() or (
        r_squared is not None and not np.isfinite(r_squared)
    ):
        raise ValueError("the linear fit does not produce finite diagnostics")
    resistance = 1 / slope if slope > 0 else None
    valid = resistance is not None and np.isfinite(resistance)
    points["fitted_current_A"][mask] = fitted
    points["residual_A"][mask] = residual
    return {
        "status": "ok" if valid else "partial",
        "reason": "" if valid else "positive_finite_reciprocal_slope_unavailable",
        "direction": "increasing" if delta[0] > 0 else "decreasing",
        "fit_n_points": len(v),
        "fit_voltage_min_V": float(v.min()),
        "fit_voltage_max_V": float(v.max()),
        "slope_A_per_V": slope,
        "intercept_A": intercept,
        "conductance_S": slope if valid else None,
        "resistance_ohm": resistance if valid else None,
        "r_squared": r_squared,
        "residual_rmse_A": rmse,
    }


def _crossing(t, y, level, start, end):
    """Find the first rising bracket wholly inside the phase, except at the switch."""
    search = np.flatnonzero((y[:-1] < level) & (y[1:] >= level) & (t[1:] >= start) & (t[1:] <= end))
    for index in search:
        fraction = (level - y[index]) / (y[index + 1] - y[index])
        crossing = t[index] + fraction * (t[index + 1] - t[index])
        if crossing >= start:
            return float(crossing)
    return None


def _transition(t, progress, start, end, increasing):
    first_percent, second_percent = (10, 90) if increasing else (90, 10)
    directed = progress if increasing else 1 - progress
    first = _crossing(t, directed, 0.1, start, end)
    if first is None:
        return None, f"missing_{first_percent}_percent_crossing"
    second = _crossing(t, directed, 0.9, first, end)
    if second is None:
        return None, f"missing_{second_percent}_percent_crossing"
    return second - first, ""


def _photoresponse(t, y, domain, points):
    if np.any(np.diff(t) <= 0):
        raise ValueError("time must strictly increase in acquisition order")
    baseline_start, baseline_end, light_on, plateau_start, plateau_end, light_off, recovery_end = domain
    baseline = _window(t, baseline_start, baseline_end)
    plateau = _window(t, plateau_start, plateau_end)
    if min(baseline.sum(), plateau.sum()) < 2:
        raise ValueError("each dark baseline and light plateau window requires at least two measurements")

    phase = points["photo_phase"]
    phase[(t >= light_on) & (t < light_off)] = "illuminated"
    phase[_window(t, light_off, recovery_end)] = "recovery"
    phase[baseline] = "baseline"
    phase[plateau] = "on_plateau"
    dark, light = float(np.median(y[baseline])), float(np.median(y[plateau]))
    amplitude = light - dark
    if not np.isfinite(amplitude):
        raise ValueError("the photoresponse amplitude is not finite")
    if amplitude == 0:
        rise = recovery = None
        rise_reason = recovery_reason = "zero_photoresponse_amplitude"
    else:
        progress = (y - dark) / amplitude
        # A sample at switch-off can bracket recovery but cannot finish the rise.
        rise, rise_reason = _transition(t, progress, light_on, np.nextafter(light_off, -np.inf), True)
        recovery, recovery_reason = _transition(t, progress, light_off, recovery_end, False)
    return {
        "status": "partial" if rise_reason or recovery_reason else "ok",
        "reason": "; ".join(dict.fromkeys(r for r in (rise_reason, recovery_reason) if r)),
        "baseline_A": dark,
        "on_plateau_A": light,
        "amplitude_A": amplitude,
        "rise_time_s": rise,
        "recovery_time_s": recovery,
        "rise_reason": rise_reason,
        "recovery_reason": recovery_reason,
    }


def _set_contracts(table, features, upstream, source_roles, feature_roles):
    parents = (
        []
        if upstream is None
        else [
            *upstream["derived_from"],
            {
                "operation": OPERATION,
                "contract_sha256": upstream["contract_sha256"],
            },
        ]
    )
    point_options = (
        {}
        if upstream is None
        else {
            "experimental_design": upstream["experimental_design"],
            "aggregation": upstream["aggregation"],
        }
    )
    table = attach_contract(
        table,
        make_contract(
            table,
            granularity="point",
            roles=source_roles,
            derived_from=parents,
            **point_options,
        ),
    )
    features = attach_contract(
        features,
        make_contract(
            features,
            granularity="curve",
            roles=feature_roles,
            derived_from=parents,
            aggregation=[{"operation": OPERATION, "input_granularity": "point"}],
        ),
    )
    return table, features


def analyze_electrical(table, config=None):
    """Fit explicit I–V windows or measure a declared light step per curve."""
    c = dict(config or {})
    mode = c.get("mode", "iv")
    if mode not in {"iv", "photoresponse"}:
        raise ValueError("mode must be iv or photoresponse")
    iv = mode == "iv"
    axis = "voltage" if iv else "time"
    si_column, axis_unit = ("voltage_V", "V") if iv else ("time_s", "s")
    x_column, current = c.get(axis, axis), c.get("current", "current")
    x_scale, i_scale = _scale(c, f"{axis}_unit", axis_unit), _scale(c, "current_unit", "A")
    keys = ("voltage_min", "voltage_max") if iv else PHOTO_TIMES
    domain = _coordinates(c, keys, x_scale)
    if iv and not domain[0] < domain[1]:
        raise ValueError("voltage_min must be below voltage_max")
    if not iv:
        b0, b1, on, p0, p1, off, end = domain
        if not b0 < b1 < on <= p0 < p1 < off < end:
            raise ValueError(
                "declare ordered dark baseline, light-on, light plateau, light-off, and recovery times"
            )

    validate_table(table)
    upstream = read_contract(table)
    source_roles = dict(upstream["roles"]) if upstream else {}
    if upstream and upstream["granularity"] not in {"point", "measurement"}:
        raise ValueError("electrical analysis requires point or measurement data")
    identity = c.get("curve_id") or source_roles.get("curve_id", "curve_id")
    sample = c.get("sample_id") or source_roles.get("sample_id")
    sweep = (c.get("sweep") or None) if iv else None
    for role, column in (("curve_id", identity), ("sample_id", sample)):
        if role in source_roles and column != source_roles[role]:
            raise ValueError(f"selected {role} conflicts with the upstream table contract")
    if (
        identity in {x_column, current, sweep}
        or x_column in {current, sample, sweep}
        or current in {sample, sweep}
    ):
        raise ValueError("measurement, curve and sweep columns must be distinct")
    shared = source_roles.get("sample_id") == source_roles.get("curve_id") == sample
    if sample and (sample == sweep or (sample == identity and not shared)):
        raise ValueError(
            "sample, curve and sweep columns must be distinct unless identity is already declared"
        )
    identifiers = list(dict.fromkeys(k for k in (identity, sample, sweep) if k))
    frame = require_table(table, [*identifiers, x_column, current]).reset_index(drop=True)
    for column in identifiers:
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"{column} identifiers cannot be missing or empty")
    if sample and (frame.groupby(identity, sort=False, observed=True)[sample].nunique() != 1).any():
        raise ValueError("every curve_id must refer to exactly one sample_id")

    declared_units = {x_column: c[f"{axis}_unit"], current: c["current_unit"]}
    if upstream:
        frame = restore_contract_units(frame, upstream, declared_units)
    else:
        existing = frame.attrs.get("units", {})
        for column, unit in declared_units.items():
            if column in existing and _unit(existing[column]) != _unit(unit):
                raise ValueError(f"conflicting units for {column}: {existing[column]!r} and {unit!r}")
        frame.attrs["units"] = {**existing, **declared_units}

    extra = (
        {"in_fit_domain": False, "fitted_current_A": np.nan, "residual_A": np.nan}
        if iv
        else {
            "photo_phase": None,
        }
    )
    derived = {si_column: np.nan, "current_A": np.nan, **extra}
    # Some instrument exports already use these SI column names for the raw measurements.
    overlap = set(derived) & set(frame)
    reusable = {
        output
        for raw, output, scale in (
            (x_column, si_column, x_scale),
            (current, "current_A", i_scale),
        )
        if raw == output and scale == 1
    }
    if overlap - reusable:
        raise ValueError("existing columns collide with reserved electrical result columns")
    for column, initial in derived.items():
        if column not in overlap:
            frame[column] = initial

    metric_units = IV_FEATURE_UNITS if iv else PHOTO_FEATURE_UNITS
    diagnostics = ("direction", "fit_n_points") if iv else ("rise_reason", "recovery_reason")
    metric_columns = [*metric_units, *diagnostics]
    rows = []
    group_key = [identity, sweep] if sweep else identity
    for _, block in frame.groupby(group_key, sort=False, observed=True):
        record = {"curve_id": block[identity].iloc[0], "n_points": len(block)}
        if sample:
            record["sample_id"] = block[sample].iloc[0]
        if sweep:
            record["sweep_id"] = block[sweep].iloc[0]
            record["analysis_curve_id"] = json.dumps(
                json_value([record["curve_id"], record["sweep_id"]]), ensure_ascii=False, allow_nan=False
            )
        points = {column: np.full(len(block), value) for column, value in extra.items()}
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                xy = numeric_matrix(block, [x_column, current]) * [x_scale, i_scale]
                for column, values in zip((si_column, "current_A"), xy.T, strict=True):
                    if column not in overlap:
                        frame.loc[block.index, column] = values
                analysis = _iv if iv else _photoresponse
                record.update(analysis(*xy.T, domain, points))
        except (ValueError, FloatingPointError) as exc:
            record.update(status="invalid", reason=str(exc))
        for column, values in points.items():
            frame.loc[block.index, column] = values
        rows.append(record)

    feature_roles = {"curve_id": "analysis_curve_id" if sweep else "curve_id"}
    source_roles.setdefault("curve_id", identity)
    if sample:
        source_roles.setdefault("sample_id", sample)
        feature_roles["sample_id"] = "sample_id"
    columns = [*rows[0], *[key for key in metric_columns if key not in rows[0]]]
    features = pd.DataFrame(rows, columns=columns)
    features.attrs["units"] = dict(metric_units)
    frame.attrs["units"].update({si_column: axis_unit, "current_A": "A"})
    if iv:
        frame.attrs["units"].update({"fitted_current_A": "A", "residual_A": "A"})
    frame.index = table.index
    frame, features = _set_contracts(frame, features, upstream, source_roles, feature_roles)
    status_columns = [col for col in columns if col not in metric_columns] + (
        [] if iv else ["rise_reason", "recovery_reason"]
    )
    return NodeResult(
        table=frame,
        features=features,
        data={
            "mode": mode,
            "curve_count": len(features),
            "status_counts": features["status"].value_counts().to_dict(),
            "statuses": json_value(features[status_columns].to_dict("records")),
            "domain_si": dict(zip(keys, domain, strict=True)),
            "domain_unit": axis_unit,
            "sample_id_column": sample,
            "feature_units": dict(metric_units),
        },
        warnings=[
            "Conductance and resistance describe the fitted window; inspect residuals and R² for linearity."
            if iv
            else (
                "Timings use the first ordered interpolated 10%–90% / 90%–10% crossings. "
                "Dark and light medians define the thresholds."
            )
        ],
    )
