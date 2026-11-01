"""Complete-curve spectra analysis and independent-curve group statistics.

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

# λ_10 denotes the lowest-energy coupled plasmon mode in Rocchetti et al.,
# Nano Letters (2023), DOI 10.1021/acs.nanolett.3c01016, Figure 2b.
# This extractor reports a window-selected spectral candidate, not a confirmed
# mode assignment or a reproduction of an unreported peak-fitting procedure.
LAMBDA10_REFERENCE = "https://doi.org/10.1021/acs.nanolett.3c01016"
SUMMARY_METRICS = ("peak_position", "height", "prominence", "fwhm", "area", "baseline", "lambda10_nm")


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


def _lambda10_candidate(peaks, x, bounds, method, scale):
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
    return {
        "lambda10_nm": float(peaks[chosen]["position"] * scale) if chosen is not None else np.nan,
        "lambda10_peak_index": chosen,
        "lambda10_candidate_count": len(candidates),
        "lambda10_ambiguous": len(candidates) > 1,
        "lambda10_method": method,
        "lambda10_status": "missing_candidate"
        if chosen is None
        else ("ambiguous_candidate" if len(candidates) > 1 else "candidate"),
    }


def _group_statistics(summaries, config):
    count = config.get("bootstrap_samples", 0)
    seed = config.get("bootstrap_seed", 0)
    if type(count) is not int or not 0 <= count <= 10000:
        raise ValueError("bootstrap_samples must be an integer between 0 and 10000")
    if type(seed) is not int or seed < 0:
        raise ValueError("bootstrap_seed must be a nonnegative integer")
    rng = np.random.default_rng(seed)
    output = []
    records = pd.DataFrame(summaries)
    for group, frame in records.groupby("group", sort=False, dropna=False, observed=True):
        valid = frame[frame.status == "completed"]
        item = {
            "group": None if pd.isna(group) else group,
            "n_curves": len(valid),
            "n_total_curves": len(frame),
            "n_failed": int((frame.status == "failed").sum()),
            "n_skipped": int((frame.status == "skipped").sum()),
            "statistics_unit": "one selected feature value per independent curve",
            "bootstrap_samples": count,
            "bootstrap_seed": seed,
        }
        if "lambda10_ambiguous" in valid:
            item["lambda10_ambiguous_curves"] = int(valid.lambda10_ambiguous.fillna(False).sum())
        for metric in SUMMARY_METRICS:
            if metric not in valid:
                continue
            values = pd.to_numeric(valid[metric], errors="coerce").dropna().to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            item[f"{metric}_n"] = len(values)
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
            if count:
                means = np.array(
                    [rng.choice(values, size=len(values), replace=True).mean() for _ in range(count)]
                )
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
    """
    config = deepcopy(dict(config or {}))
    curve_column, x_column, y_column = (config.get(k, k) for k in ("curve_id", "x", "y"))
    group_column = config.get("group", "group" if table is not None and "group" in table else None)
    needed = [curve_column, x_column, y_column] + ([group_column] if group_column else [])
    if len(set(needed)) != len(needed):
        raise ValueError("curve_id, group, x and y must name distinct columns")
    frame = require_table(table, needed, min_rows=1)
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
        }
        if halted:
            summaries.append(
                {**summary, "status": "skipped", "error": "earlier curve failed with on_error=stop"}
            )
            continue
        try:
            result = spectra(subset, config=parameters)
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
                metrics = _lambda10_candidate(peaks, result.table.x.to_numpy(), bounds, selection, scale)
                summary.update(metrics)
                for key, value in metrics.items():
                    curve_features[key] = value
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
            summary.update({"status": "failed", "error": str(exc)})
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
        }[config.get("normalization", "none")]
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
        "Group statistics assume each curve is an independent experimental unit; "
        "repeated measurements require an appropriate design."
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
        "area_signal": "baseline-corrected smoothed signal before normalization",
        "parameters": config,
    }
    return NodeResult(table=complete_table, data=json_value(data), features=peak_table, warnings=warnings)
