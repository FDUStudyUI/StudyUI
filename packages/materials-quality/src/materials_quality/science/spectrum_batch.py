"""Complete-curve spectra analysis and descriptive curve-level group statistics.

No plotting, material identification, automatic physical-unit guesses or pooling
of raw curves takes place here. Baseline, peak widths and integrations reuse the
same numerical routines as the existing single-curve materials operation.
"""

from copy import deepcopy

import numpy as np
import pandas as pd

from materials_quality.common import json_value
from materials_quality.units import _unit

from .contracts import NodeResult, require_table
from .features import FEATURE_COLUMNS, feature_units, features_for
from .materials import spectra
from .table_contract import attach_contract, make_contract, read_contract, restore_contract_units

# λ_10 denotes the lowest-energy coupled plasmon mode in Rocchetti et al.,
# Nano Letters (2023), DOI 10.1021/acs.nanolett.3c01016, Figure 2b.
# This extractor reports a window-selected spectral candidate, not a confirmed
# mode assignment or a reproduction of an unreported peak-fitting procedure.
LAMBDA10_REFERENCE = "https://doi.org/10.1021/acs.nanolett.3c01016"
SUMMARY_METRICS = (
    "peak_position",
    "height",
    "prominence",
    "fwhm",
    "area",
    "baseline",
    "lambda10_nm",
    "window_candidate_nm",
)
ENTITY_ROLES = ("sample_id", "experimental_unit", "pair_id", "technical_replicate")


def validate_spectral_contract(table, config):
    """Validate declared point/identity semantics at every spectral API entry."""
    contract = read_contract(table)
    if contract is None:
        return None
    if contract["granularity"] != "point":
        raise ValueError("spectral input contract must declare point-granularity measurements")
    curve_column = config.get("curve_id", "curve_id")
    bindings = {
        "curve_id": curve_column,
        "x": config.get("x", "x"),
        "response": config.get("y", "y"),
        "group": config.get("group", "group" if "group" in table else None),
    }
    require_table(table, [column for column in bindings.values() if column is not None])
    roles = contract["roles"]
    for role, column in bindings.items():
        if role in roles and roles[role] != column:
            raise ValueError(f"input contract role {role} conflicts with configured source column")
    relationships = {}
    for column in {roles[role] for role in ENTITY_ROLES if role in roles}:
        pair = table[list(dict.fromkeys([curve_column, column]))].drop_duplicates()
        if pair[curve_column].duplicated().any():
            raise ValueError(
                "each curve must map to exactly one declared sample/unit/pair/replicate identity"
            )
        relationships[column] = pair
    if config.get("bootstrap_independence_confirmed") is True:
        if contract["experimental_design"]["kind"] == "paired":
            raise ValueError("paired design cannot be overridden by independent-curve bootstrap")
        unit = roles.get("experimental_unit")
        if unit is not None and relationships[unit][unit].duplicated().any():
            raise ValueError(
                "known experimental units contain repeated curves; "
                "aggregate by unit before independent bootstrap"
            )
    return contract


def contract_spectral_output(source, frame, grain, roles, source_contract, curve_column="curve_id"):
    """Preserve declared entity topology across public and native spectral ports.

    Source topology must already pass ``validate_spectral_contract``. Point and
    peak outputs retain typed entity mappings, design and aggregation history;
    group summaries retain descriptive semantics. No contract is fabricated for
    legacy inputs lacking a declaration.
    """
    if source_contract is None:
        return frame
    frame = frame.copy(deep=True)
    frame.attrs = deepcopy(frame.attrs)
    roles = {
        role: column
        for role, column in roles.items()
        if column in frame and (role not in {"curve_id", "group"} or not frame[column].isna().any())
    }
    aggregation = deepcopy(source_contract["aggregation"])
    design = {"kind": "descriptive", "confirmed": False}
    if grain != "group_summary":
        source_roles = source_contract["roles"]
        source = restore_contract_units(source, source_contract)
        mapping = source.drop_duplicates(curve_column).set_index(curve_column, drop=False)
        targets = {
            source_roles[role]: roles[role]
            for role in ("curve_id", "group")
            if role in source_roles and role in roles
        }
        for role in ENTITY_ROLES:
            if role not in source_roles:
                continue
            column = source_roles[role]
            if column not in targets:
                target = column
                while target in frame.columns:
                    target = "source_" + target
                targets[column] = target
                frame[target] = frame.curve_id.map(mapping[column]).astype(object)
                if column in source.attrs.get("units", {}):
                    frame.attrs.setdefault("units", {})[target] = source.attrs["units"][column]
            roles[role] = targets[column]
        design = deepcopy(source_contract["experimental_design"])
    else:
        aggregation.append({"operation": "curve_level_description"})
    return attach_contract(
        frame,
        make_contract(
            frame,
            granularity=grain,
            roles=roles,
            experimental_design=design,
            aggregation=aggregation,
            derived_from=[
                *source_contract["derived_from"],
                {
                    "operation": "materials.batch_spectra",
                    "contract_sha256": source_contract["contract_sha256"],
                },
            ],
            units_state={"source": "spectral_analysis", "units": deepcopy(frame.attrs.get("units", {}))},
        ),
    )


def _identifiers(series, name):
    """Reject missing, composite and ambiguous textual representations of keys."""
    seen = {}
    for value in pd.unique(series):
        if not pd.api.types.is_scalar(value) or pd.isna(value) or not str(value).strip():
            raise ValueError(f"{name} keys must be nonmissing scalar values")
        if isinstance(value, (bool, np.bool_)):
            raise ValueError(f"{name} keys cannot be booleans")
        label = str(value)
        identity = (type(value).__name__, repr(value))
        if label in seen and seen[label] != identity:
            raise ValueError(f"ambiguous {name} key: {label!r}")
        seen[label] = identity


def _declared_unit(frame, config, key, column, alternative=None):
    declared = config.get(key, config.get(alternative) if alternative else None)
    stored = frame.attrs.get("units", {}).get(column)
    if declared is None:
        declared = stored
    if (
        not isinstance(declared, str)
        or not declared.strip()
        or declared.strip() in {"unspecified", "unknown"}
    ):
        raise ValueError(f"{key} must be declared explicitly (or in table.attrs['units'])")
    if stored is not None and stored != declared:
        raise ValueError(f"{key} conflicts with source table unit {stored!r}; convert explicitly first")
    return declared.strip()


def _wavelength_scale(unit):
    try:
        parsed = _unit(unit)
        if not parsed.is_compatible_with(_unit("nm")):
            raise ValueError("not length")
        return float((1 * parsed).to("nm").magnitude)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(
            "lambda10 requires a wavelength length unit; no wavenumber/energy inversion is assumed"
        ) from exc


def _lambda10_settings(config, x_unit):
    window = config.get("lambda10_window_nm")
    if window is None:
        return None, None, None
    try:
        bounds = np.asarray(window, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("lambda10_window_nm must be two finite positive increasing wavelengths") from exc
    if bounds.shape != (2,) or not np.isfinite(bounds).all() or not 0 < bounds[0] < bounds[1]:
        raise ValueError("lambda10_window_nm must be two finite positive increasing wavelengths")
    method = config.get("lambda10_selection", "highest_prominence")
    if method not in {"highest_prominence", "redmost"}:
        raise ValueError("lambda10_selection must be highest_prominence or redmost")
    return bounds, method, _wavelength_scale(x_unit)


def _lambda10_candidate(peaks, x, bounds, method, scale, source_rows=None):
    if np.any(x <= 0):
        raise ValueError("wavelength coordinates must be positive")
    candidates = [i for i, peak in enumerate(peaks) if bounds[0] <= peak["position"] * scale <= bounds[1]]
    if method == "redmost":
        chosen = (
            max(candidates, key=lambda i: (peaks[i]["position"], peaks[i]["prominence"]))
            if candidates
            else None
        )
    else:
        chosen = (
            min(candidates, key=lambda i: (-peaks[i]["prominence"], -peaks[i]["position"]))
            if candidates
            else None
        )
    status = (
        "missing_candidate"
        if chosen is None
        else ("ambiguous_candidate" if len(candidates) > 1 else "candidate")
    )
    value = float(peaks[chosen]["position"] * scale) if chosen is not None else np.nan
    candidate_records = [
        {
            "peak_index": i,
            "processed_index": peaks[i]["index"],
            "source_index": int(source_rows[peaks[i]["index"]])
            if source_rows is not None
            else peaks[i]["index"],
            "position": peaks[i]["position"],
            "position_nm": float(peaks[i]["position"] * scale),
            "height": peaks[i]["height"],
            "prominence": peaks[i]["prominence"],
            "fwhm": peaks[i]["fwhm"],
            "selected": i == chosen,
            "at_window_edge": bool(np.isclose(peaks[i]["position"] * scale, bounds, rtol=0, atol=1e-9).any()),
        }
        for i in candidates
    ]
    return {
        "window_candidate_nm": value,
        "selection_rule": method,
        "candidate_count": len(candidates),
        "ambiguous": len(candidates) > 1,
        "detection_status": status,
        "window_candidates": candidate_records,
        "candidate_at_window_edge": any(p["selected"] and p["at_window_edge"] for p in candidate_records),
        "selection_reason": "largest prominence; ties choose redmost coordinate"
        if method == "highest_prominence"
        else "redmost coordinate; ties choose largest prominence",
        "lambda10_nm": value,
        "lambda10_peak_index": chosen,
        "lambda10_candidate_count": len(candidates),
        "lambda10_ambiguous": len(candidates) > 1,
        "lambda10_method": method,
        "lambda10_status": status,
    }


def _group_statistics(summaries, config):
    count = config.get("bootstrap_samples", 0)
    seed = config.get("bootstrap_seed", 0)
    if type(count) is not int or not 0 <= count <= 10000:
        raise ValueError("bootstrap_samples must be an integer between 0 and 10000")
    if type(seed) is not int or seed < 0:
        raise ValueError("bootstrap_seed must be a nonnegative integer")
    confirmed = config.get("bootstrap_independence_confirmed", False)
    if type(confirmed) is not bool:
        raise ValueError("bootstrap_independence_confirmed must be a JSON boolean")
    rng = np.random.default_rng(seed)
    output = []
    records = pd.DataFrame(summaries)
    for group, frame in records.groupby("group", sort=False, dropna=False, observed=True):
        valid = frame[frame.status == "completed"]
        detected = (
            valid["candidate_count"].gt(0)
            if "candidate_count" in valid
            else valid.get("has_peak", pd.Series(False, index=valid.index)).eq(True)
        )
        ambiguous = (
            valid["ambiguous"].eq(True) if "ambiguous" in valid else pd.Series(False, index=valid.index)
        )
        item = {
            "group": None if pd.isna(group) else group,
            "n_curves": len(valid),
            "n_total_curves": len(frame),
            "n_failed": int((frame.status == "failed").sum()),
            "n_skipped": int((frame.status == "skipped").sum()),
            "n_total": len(frame),
            "n_eligible": len(valid),
            "n_detected": int(detected.sum()),
            "n_ambiguous": int(ambiguous.sum()),
            "n_no_candidate": int((~detected).sum()),
            "observed_detection_fraction": float(detected.mean()) if len(valid) else None,
            "detection_denominator": "eligible completed curves; ambiguous candidates count as detected",
            "ambiguous_in_descriptive_statistics": True,
            "candidate_mean_scope": (
                "conditional description among detected curves, including ambiguous selections"
            ),
            "statistics_unit": (
                "one selected feature value per curve; independence is not inferred from curve count"
            ),
            "bootstrap_independence_confirmed": confirmed,
            "bootstrap_policy": (
                "default product policy withholds n<3 and degenerate empirical resampling; "
                "an explicit independence declaration is required"
            ),
            "bootstrap_samples": count,
            "bootstrap_seed": seed,
        }
        if "lambda10_ambiguous" in valid:
            item["lambda10_ambiguous_curves"] = int(valid.lambda10_ambiguous.eq(True).sum())
        for metric in SUMMARY_METRICS:
            if metric not in valid:
                continue
            if metric == "window_candidate_nm" and "lambda10_nm" in valid:
                # Compatibility aliases describe the same estimand and must
                # share the exact resampling realization, not merely its seed.
                item.update(
                    {
                        key.replace("lambda10_nm_", "window_candidate_nm_", 1): value
                        for key, value in list(item.items())
                        if key.startswith("lambda10_nm_")
                    }
                )
                continue
            values = pd.to_numeric(valid[metric], errors="coerce").dropna().to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            item[f"{metric}_n"] = len(values)
            if count:
                item[f"{metric}_ci_low"] = item[f"{metric}_ci_high"] = None
                if len(values) < 3:
                    ci_status, reason = (
                        "insufficient_sample_size",
                        "product policy requires at least three observed selected values; "
                        "small n remains descriptive",
                    )
                elif np.ptp(values) == 0:
                    ci_status, reason = (
                        "degenerate_resampling",
                        "all observed values are identical; "
                        "empirical resampling cannot estimate population precision",
                    )
                elif not confirmed:
                    ci_status, reason = (
                        "independence_not_declared",
                        "curve count does not establish independent experimental units; "
                        "declare and validate the design first",
                    )
                else:
                    ci_status, reason = (
                        "estimated",
                        "percentile empirical bootstrap of explicitly declared "
                        "independent curve-level values",
                    )
                item[f"{metric}_ci_status"], item[f"{metric}_ci_reason"] = ci_status, reason
            if not len(values):
                continue
            item.update(
                {
                    f"{metric}_mean": float(values.mean()),
                    f"{metric}_std": float(values.std(ddof=1)) if len(values) > 1 else None,
                    f"{metric}_q25": float(np.quantile(values, 0.25)),
                    f"{metric}_q50": float(np.quantile(values, 0.5)),
                    f"{metric}_q75": float(np.quantile(values, 0.75)),
                }
            )
            if count and ci_status == "estimated":
                means = np.array(
                    [rng.choice(values, size=len(values), replace=True).mean() for _ in range(count)]
                )
                if np.ptp(means) == 0:
                    item[f"{metric}_ci_status"] = "degenerate_resampling"
                    item[f"{metric}_ci_reason"] = (
                        "empirical bootstrap means are constant at the requested resampling count"
                    )
                else:
                    item[f"{metric}_ci_low"], item[f"{metric}_ci_high"] = map(
                        float, np.quantile(means, [0.025, 0.975])
                    )
        output.append(item)
    return output


def analyze_spectra(table, config=None):
    """Analyze each entire ``curve_id,x,y[,group]`` curve; return complete rows.

    ``features`` contains all detected peaks (and an explicit no-peak record for
    completed curves without peaks). ``curve_summary`` retains every curve and
    selects its primary peak by largest prominence, then lowest coordinate.
    Group statistics use those primary curve records, never individual peaks.
    Optional ``lambda10_window_nm`` adds canonical ``window_candidate_nm`` and
    legacy aliases, with ``selection_rule``, candidate counts and detection
    diagnostics. All completed curves retain effective ``peak_detection``.

    Bootstrap intervals require ``bootstrap_independence_confirmed=True``;
    this records a caller declaration, never derives independence from IDs or
    count. The product policy withholds n<3, constant empirical samples and
    degenerate resampling, retaining None limits and per-metric status/reason.
    """
    config = deepcopy(dict(config or {}))
    curve_column, x_column, y_column = (config.get(k, k) for k in ("curve_id", "x", "y"))
    group_column = config.get("group", "group" if table is not None and "group" in table else None)
    needed = [curve_column, x_column, y_column] + ([group_column] if group_column else [])
    if len(set(needed)) != len(needed):
        raise ValueError("curve_id, group, x and y must name distinct columns")
    frame = require_table(table, needed, min_rows=1)
    source_contract = validate_spectral_contract(frame, config)
    if source_contract is not None:
        frame = restore_contract_units(frame, source_contract)
    _identifiers(frame[curve_column], "curve_id")
    if group_column:
        _identifiers(frame[group_column], "group")
        if frame.groupby(curve_column, sort=False, observed=True)[group_column].nunique().gt(1).any():
            raise ValueError("each curve_id must belong to exactly one homogeneous group")
    x_unit = _declared_unit(frame, config, "x_unit", x_column)
    intensity_unit = _declared_unit(frame, config, "intensity_unit", y_column, "y_unit")
    if "lambda10_definition" in config and config["lambda10_definition"] not in {
        None,
        "none",
        "coupled_mode_candidate",
    }:
        raise ValueError(
            "lambda10 denotes a coupled plasmon mode; use lambda10_window_nm, not a 10% threshold"
        )
    bounds, selection, scale = _lambda10_settings(config, x_unit)
    definition = "coupled_mode_candidate" if bounds is not None else "none"
    on_error = config.get("on_error", "continue")
    if on_error not in {"continue", "stop"}:
        raise ValueError("on_error must be continue or stop")
    # Validate group-statistics controls even when every measured curve fails.
    _group_statistics([{"group": None, "status": "failed"}], config)
    parameters = {**config, "x": x_column, "y": y_column, "x_unit": x_unit, "intensity_unit": intensity_unit}
    processed, features, summaries, warnings = [], [], [], []
    processed_units = {}
    halted = False
    for identifier, row_positions in frame.groupby(curve_column, sort=False, observed=True).indices.items():
        subset = frame.iloc[row_positions]
        group = subset[group_column].iloc[0] if group_column else None
        summary = {
            "curve_id": identifier,
            "group": group,
            "n_points": len(subset),
            "x_unit": x_unit,
            "intensity_unit": intensity_unit,
            "detection_status": "not_analyzed",
            "selection_rule": selection,
            "candidate_count": None,
            "ambiguous": False,
        }
        if halted:
            summaries.append(
                {
                    **summary,
                    "status": "skipped",
                    "detection_status": "skipped",
                    "error": "earlier curve failed with on_error=stop",
                }
            )
            continue
        try:
            result = spectra(subset, config=parameters)
            processed_units.update(result.table.attrs.get("units", {}))
            warnings.extend(warning for warning in result.warnings if warning not in warnings)
            curve_features = features_for("materials.spectra", result, identifier, group)
            curve_features["status"] = "completed"
            curve_features["reason"] = None
            peaks = result.data["peaks"]
            summary.update(
                {
                    "status": "completed",
                    "error": None,
                    "n_peaks": len(peaks),
                    "areas": result.data["areas"],
                    "has_peak": bool(peaks),
                    "peak_detection": result.data["peak_detection"],
                    "detection_status": "candidate" if peaks else "missing_candidate",
                    "candidate_count": len(peaks),
                }
            )
            primary = (
                min(range(len(peaks)), key=lambda i: (-peaks[i]["prominence"], peaks[i]["position"]))
                if peaks
                else None
            )
            curve_features["is_primary"] = [i == primary for i in range(len(curve_features))]
            if primary is not None:
                summary.update(
                    {k: curve_features.iloc[primary][k] for k in SUMMARY_METRICS if k in curve_features}
                )
            else:
                curve_features = pd.DataFrame(
                    [
                        {
                            **{k: np.nan for k in FEATURE_COLUMNS},
                            "curve_id": identifier,
                            "group": group,
                            "x_unit": x_unit,
                            "intensity_unit": intensity_unit,
                            "status": "no_peaks",
                            "reason": "no peaks pass the configured prominence and distance",
                            "is_primary": False,
                        }
                    ]
                )
                summary["reason"] = "no peaks pass the configured prominence and distance"
            if bounds is not None:
                metrics = _lambda10_candidate(
                    peaks,
                    result.table.x.to_numpy(),
                    bounds,
                    selection,
                    scale,
                    result.table.source_row.to_numpy(),
                )
                for candidate in metrics["window_candidates"]:
                    candidate["input_row_position"] = int(row_positions[candidate["source_index"]])
                    candidate["input_row_index"] = subset.index[candidate["source_index"]]
                summary.update(metrics)
                for key, value in metrics.items():
                    curve_features[key] = [deepcopy(value) for _ in range(len(curve_features))]
                curve_features["is_lambda10_candidate"] = [
                    (
                        not pd.isna(row["peak_index"])
                        and bounds[0] <= row["peak_position"] * scale <= bounds[1]
                    )
                    for _, row in curve_features.iterrows()
                ]
                if metrics["lambda10_candidate_count"] == 0:
                    warnings.append(
                        f"curve {identifier!r}: no lambda10 peak candidate inside the explicit search window"
                    )
                if metrics["lambda10_ambiguous"]:
                    warnings.append(
                        f"curve {identifier!r}: multiple lambda10 candidates; "
                        "inspect the configured selection rule"
                    )
                if bounds[0] < result.table.x.iloc[0] * scale or bounds[1] > result.table.x.iloc[-1] * scale:
                    warnings.append(
                        f"curve {identifier!r}: lambda10 search window extends beyond the observed spectrum; "
                        "no extrapolation"
                    )
            if x_unit == "nm":
                for name in ("peak_position", "fwhm"):
                    if name in curve_features:
                        curve_features[f"{name}_nm"] = curve_features[name]
            curve_features["peak_detection"] = [
                deepcopy(result.data["peak_detection"]) for _ in range(len(curve_features))
            ]
            curve_features.attrs = {}
            features.append(curve_features)
            complete = result.table.copy(deep=True)
            complete["curve_id"], complete["group"] = identifier, group
            complete["input_row_position"] = row_positions[complete.source_row.to_numpy()]
            complete["input_row_index"] = subset.index.to_numpy()[complete.source_row.to_numpy()]
            complete.attrs = {}
            processed.append(complete)
            if any(p.get("fwhm") is None for p in peaks):
                warnings.append(
                    f"curve {identifier!r}: FWHM unavailable without both observed half-height crossings"
                )
        except (ValueError, TypeError, ArithmeticError) as exc:
            summary.update({"status": "failed", "detection_status": "failed", "error": str(exc)})
            halted = on_error == "stop"
        summaries.append(summary)
    peak_table = pd.concat(features, ignore_index=True) if features else pd.DataFrame(columns=FEATURE_COLUMNS)
    feature_units(peak_table, x_unit, intensity_unit)
    complete_table = (
        pd.concat(processed, ignore_index=True)
        if processed
        else pd.DataFrame(
            columns=[
                "source_row",
                "x",
                "raw_y",
                "baseline",
                "corrected",
                "smoothed",
                "normalized",
                "curve_id",
                "group",
            ]
        )
    )
    complete_table.attrs["units"] = {
        "x": x_unit,
        **{
            key: intensity_unit
            for key in ("raw_y", "baseline", "corrected", "smoothed")
            if key in complete_table
        },
    }
    if "normalized" in complete_table:
        complete_table.attrs["units"]["normalized"] = {
            "none": intensity_unit,
            "max": "dimensionless",
            "l2": "dimensionless",
            "area": f"1/{x_unit}",
            "snv": "dimensionless",
        }[config.get("normalization", "none")]
    complete_table.attrs["units"].update(
        {key: value for key, value in processed_units.items() if key in complete_table.columns}
    )
    if source_contract is not None:
        complete_table = contract_spectral_output(
            frame,
            complete_table,
            "point",
            {"curve_id": "curve_id", "group": "group", "x": "x", "response": "smoothed"},
            source_contract,
            curve_column,
        )
        peak_table = contract_spectral_output(
            frame,
            peak_table,
            "peak",
            {
                "curve_id": "curve_id",
                "group": "group",
                "x": "peak_position",
                "response": "height",
                "peak_id": "peak_index",
            },
            source_contract,
            curve_column,
        )
    counts = {
        "total": len(summaries),
        **{s: sum(r["status"] == s for r in summaries) for s in ("completed", "failed", "skipped")},
    }
    status = (
        "completed"
        if counts["completed"] == counts["total"]
        else ("partial_failed" if counts["completed"] else "failed")
    )
    warnings.append(
        "Peak-base areas can overlap; use explicit non-overlapping area_ranges for quantitative integration."
    )
    warnings.append(
        "Group summaries describe curve-level selected values, including ambiguous candidates. "
        "Curve count does not establish independence; "
        "bootstrap inference requires an explicitly confirmed design."
    )
    group_summary = _group_statistics(summaries, config)
    group_columns = set(pd.DataFrame(group_summary).columns)
    group_units = {
        f"{metric}_{statistic}": unit
        for metric, unit in peak_table.attrs["units"].items()
        for statistic in ("mean", "std", "q25", "q50", "q75", "ci_low", "ci_high")
        if f"{metric}_{statistic}" in group_columns
    }
    data = {
        "counts": counts,
        "execution_status": status,
        "curve_summary": summaries,
        "group_summary": group_summary,
        "group_summary_units": group_units,
        "features": peak_table.to_dict("records"),
        "x_unit": x_unit,
        "intensity_unit": intensity_unit,
        "lambda10_definition": definition,
        "lambda10_description": (
            "window-selected candidate for lowest-energy coupled plasmon mode; not a confirmed assignment"
        ),
        "lambda10_window_nm": bounds.tolist() if bounds is not None else None,
        "lambda10_selection": selection,
        "lambda10_reference": LAMBDA10_REFERENCE,
        "primary_peak_selection": "largest prominence; ties choose lowest coordinate",
        "candidate_alias_schema": (
            "studyui-window-candidate/1; lambda10_* are compatibility aliases, not confirmed mode assignments"
        ),
        "peak_detection_settings": {
            key: config[key]
            for key in (
                "prominence_mode",
                "prominence",
                "noise_window",
                "noise_multiplier",
                "peak_distance",
                "peak_distance_x",
            )
            if key in config
        },
        "peak_detection": [
            {"curve_id": row["curve_id"], **row["peak_detection"]}
            for row in summaries
            if "peak_detection" in row
        ],
        "area_signal": "baseline-corrected smoothed signal before normalization",
        "parameters": config,
    }
    return NodeResult(table=complete_table, data=json_value(data), features=peak_table, warnings=warnings)
