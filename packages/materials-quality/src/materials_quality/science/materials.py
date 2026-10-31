"""Six evidence-bounded materials analysis operations, independent of Langflow."""

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from .contracts import NodeResult, numeric_matrix, read_path, require_table
from .materials_curves import (
    curve,
    fit_pattern,
    integrate_ranges,
    interval,
    match_references,
    peak_records,
    positive,
    processed_curve,
)


def xrd(table=None, *, config=None, data=None, tables=None):
    """Background/smoothing, absolute-height widths, reference matching and profile fits."""
    config = dict(config or {})
    x, y, frame, transform = processed_curve(table, config)
    peaks = peak_records(x, y, config)
    matches = match_references(x, y, peaks, config, data)
    fitted, fit = fit_pattern(x, y, config, data)
    warnings = [
        "Peak widths are apparent baseline-corrected widths; "
        "overlap and instrumental broadening are not removed."
    ]
    if any(p["fwhm"] is None for p in peaks):
        warnings.append("Some peaks lack both half-height crossings; their FWHM is unavailable.")
    if matches:
        warnings.append(
            "Reference matches are candidates within the supplied library, not confirmed material phases."
        )
    if fit is not None:
        frame["fitted"] = fitted
        frame["residual"] = y - fitted
        warnings.append(
            "Whole-pattern fitting is empirical profile fitting, not structural Rietveld refinement."
        )
    return NodeResult(
        table=frame,
        data={
            "peaks": peaks,
            "matches": matches,
            "fit": fit,
            "x_unit": config.get("x_unit", "unspecified coordinate unit"),
            "transform": transform,
        },
        warnings=warnings,
    )


def spectra(table=None, *, config=None, data=None, tables=None):
    """FTIR/Raman signal processing; integration occurs before normalization."""
    config = dict(config or {})
    x, y, frame, transform = processed_curve(table, config)
    peaks = peak_records(x, y, config)
    areas = integrate_ranges(x, y, config)
    method = config.get("normalization", "none")
    if method == "none":
        scale = 1.0
    elif method == "max":
        scale = float(np.max(np.abs(y)))
    elif method == "l2":
        scale = float(np.linalg.norm(y))
    elif method == "area":
        scale = float(trapezoid(np.abs(y), x))
    else:
        raise ValueError("normalization must be none, max, l2, or area")
    if scale <= 0:
        raise ValueError("cannot normalize a zero spectrum")
    frame["normalized"] = y / scale
    matches = match_references(x, y, peaks, config, data)
    warnings = [
        "Peak-base areas can overlap; use explicit non-overlapping area_ranges for quantitative integration.",
        "FTIR input must use an appropriate signal convention (for example absorbance); "
        "no automatic transmittance conversion.",
    ]
    if matches:
        warnings.append("Library scores rank supplied references; they do not confirm chemical identity.")
    return NodeResult(
        table=frame,
        data={
            "peaks": peaks,
            "areas": areas,
            "matches": matches,
            "area_signal": "baseline-corrected smoothed signal before normalization",
            "normalization": {"method": method, "scale": scale},
            "transform": transform,
        },
        warnings=warnings,
    )


def _thermal_units(config):
    unit = config.get("x_unit")
    if unit not in {"degC", "K", "s", "min"}:
        raise ValueError("thermal x_unit must be degC, K, s, or min")
    return unit


def _dsc_time_scale(config):
    unit = _thermal_units(config)
    if unit in {"s", "min"}:
        return 1.0 if unit == "s" else 60.0
    rate = positive(config.get("heating_rate"), "heating_rate")
    rate_unit = config.get("heating_rate_unit")
    if rate_unit not in {"K/min", "K/s", "degC/min", "degC/s"}:
        raise ValueError("heating_rate_unit must be K/min, K/s, degC/min, or degC/s")
    return (60.0 if rate_unit.endswith("/min") else 1.0) / rate


def _tangent_onset(x, y, peak, left, direction=1, baseline_value=0.0):
    gradient = np.gradient(y, x)
    if peak <= left:
        return None, None
    point = int(left + np.argmax(direction * gradient[left : peak + 1]))
    slope = float(gradient[point])
    if direction * slope <= 0:
        return None, None
    onset = float(x[point] + (baseline_value - y[point]) / slope)
    if not x[left] <= onset <= x[peak]:
        return None, {"coordinate": float(x[point]), "slope": slope, "extrapolated_intersection": onset}
    return onset, {"coordinate": float(x[point]), "slope": slope, "baseline_level": float(baseline_value)}


def _tg_plateau(x, mass, loss_rate, low, peak):
    """Last contiguous stable region before the maximum loss rate, within this event's history."""
    flat = np.abs(loss_rate[low:peak]) <= 0.01 * loss_rate[peak]
    edges = np.flatnonzero(np.diff(np.r_[False, flat, False]))
    for start, stop in reversed(edges.reshape(-1, 2)):
        if stop - start >= 3:
            start, stop = low + start, low + stop
            return float(np.median(mass[start:stop])), [float(x[start]), float(x[stop - 1])]
    return None, None


def _dsc_events(x, y, config, sign, unit):
    candidates = []
    for direction in (1, -1):
        for peak in peak_records(x, direction * y, config):
            if peak["height"] > 0:
                candidates.append((peak["index"], direction, peak["left_base_index"]))
    events = []
    previous = None
    for idx, direction, left in sorted(candidates):
        if previous is not None:
            # The inter-event minimum bounds same-sign peaks. A baseline return
            # separates successive peaks of opposite sign.
            signed = direction * y[previous : idx + 1]
            left = max(left, previous + int(np.argmin(signed)))
        baseline_samples = np.flatnonzero(direction * y[left:idx] <= 0)
        if len(baseline_samples):
            left += int(baseline_samples[-1])
        onset, tangent = _tangent_onset(x, y, idx, left, direction)
        is_endo = direction == (1 if sign == "positive" else -1)
        events.append(
            {
                "peak_coordinate": float(x[idx]),
                "peak_temperature": float(x[idx]) if unit in {"K", "degC"} else None,
                "peak_signal": float(y[idx]),
                "event": "endothermic" if is_endo else "exothermic",
                "onset": onset,
                "onset_method": "local leading-edge tangent to corrected zero baseline",
                "leading_range": [float(x[left]), float(x[idx])],
                "tangent": tangent,
            }
        )
        previous = idx
    return events


def thermal(table=None, *, config=None, data=None, tables=None):
    """TG loss segments or DSC signed energy integration with explicit units."""
    config = dict(config or {})
    kind = config.get("kind", "tg")
    x_unit = _thermal_units(config)
    x, y, frame, transform = processed_curve(table, config)
    warnings = []
    if kind == "tg":
        if config.get("y_unit") not in {"%", "mg", "g"}:
            raise ValueError("TG y_unit must be %, mg, or g")
        initial = positive(config.get("initial_mass", y[0]), "initial_mass")
        if np.any(y < 0):
            raise ValueError("TG baseline-corrected mass cannot be negative")
        mass_percent = 100 * y / initial
        loss_rate = -np.gradient(mass_percent, x)
        threshold = positive(
            config.get("stage_threshold", max(float(loss_rate.max()) * 0.05, 1e-12)), "stage_threshold"
        )
        active = loss_rate >= threshold
        transitions = np.diff(np.r_[False, active, False].astype(int))
        starts, ends = np.flatnonzero(transitions == 1), np.flatnonzero(transitions == -1) - 1
        stages = []
        plateau_search_start = 0
        for start, end in zip(starts, ends, strict=False):
            if end <= start:
                continue
            peak = int(start + np.argmax(loss_rate[start : end + 1]))
            slope = -float(loss_rate[peak])
            level, plateau_range = _tg_plateau(x, mass_percent, loss_rate, plateau_search_start, peak)
            plateau_search_start = peak + 1
            onset = None
            if level is not None:
                candidate = float(x[peak] + (level - mass_percent[peak]) / slope)
                if plateau_range[0] <= candidate <= x[peak]:
                    onset = candidate
            if onset is None:
                warnings.append(f"TG stage at {x[peak]:g} lacks a supported measured plateau/tangent onset.")
            stages.append(
                {
                    "start": float(x[start]),
                    "end": float(x[end]),
                    "mass_loss_percent": float(mass_percent[start] - mass_percent[end]),
                    "peak_loss_coordinate": float(x[peak]),
                    "peak_loss_rate": float(loss_rate[peak]),
                    "onset": onset,
                    "onset_method": "maximum-loss-rate tangent to observed pre-event plateau median",
                    "tangent_slope": slope,
                    "baseline_level": level,
                    "plateau_range": plateau_range,
                    "plateau_rate_limit": float(0.01 * loss_rate[peak]),
                }
            )
        frame["mass_percent"] = mass_percent
        frame["loss_rate"] = loss_rate
        warnings.append(
            "Stage limits depend on the derivative threshold; separated losses can merge. "
            "TG baseline represents additive drift."
        )
        return NodeResult(
            table=frame,
            data={
                "kind": kind,
                "stages": stages,
                "total_mass_loss_percent": float(mass_percent[0] - mass_percent[-1]),
                "initial_mass": initial,
                "stage_threshold": threshold,
                "loss_rate_unit": f"percent/{x_unit}",
                "x_unit": x_unit,
                "transform": transform,
            },
            warnings=warnings,
        )
    if kind != "dsc":
        raise ValueError("kind must be tg or dsc")
    sign = config.get("endotherm")
    if sign not in {"positive", "negative"}:
        raise ValueError("DSC requires endotherm=positive or negative to declare instrument sign convention")
    conversion = {
        "W/g": (1.0, "J/g"),
        "mW/mg": (1.0, "J/g"),
        "mW/g": (0.001, "J/g"),
        "W": (1.0, "J"),
        "mW": (0.001, "J"),
    }
    if config.get("y_unit") not in conversion:
        raise ValueError("DSC y_unit must be W/g, mW/mg, mW/g, W, or mW")
    power_scale, energy_unit = conversion[config["y_unit"]]
    seconds_per_x = _dsc_time_scale(config)
    areas = integrate_ranges(x, y, config)
    for area in areas:
        area["enthalpy"] = area["area"] * seconds_per_x * power_scale
        area["endothermic_positive_enthalpy"] = area["enthalpy"] * (1 if sign == "positive" else -1)
        area["unit"] = energy_unit
    peaks = _dsc_events(x, y, config, sign, x_unit)
    if any(p["onset"] is None for p in peaks):
        warnings.append("Some tangent onsets fall outside the observed leading edge and are unavailable.")
    warnings.append(
        "Integrated energy depends on baseline and selected bounds; "
        "overlapping transitions are not deconvolved."
    )
    return NodeResult(
        table=frame,
        data={
            "kind": kind,
            "peaks": peaks,
            "areas": areas,
            "x_unit": x_unit,
            "endotherm": sign,
            "seconds_per_coordinate": seconds_per_x,
            "transform": transform,
        },
        warnings=warnings,
    )


def mechanics(table=None, *, config=None, data=None, tables=None):
    """Engineering tensile curve; explicit elastic fit and offset proof stress."""
    config = dict(config or {})
    fracture_confirmed = config.get("fracture_confirmed", False)
    if type(fracture_confirmed) is not bool:
        raise ValueError("fracture_confirmed must be a JSON boolean (true or false)")
    if "fit_range" not in config:
        raise ValueError("fit_range in supplied strain units is required for elastic modulus fitting")
    if config.get("strain_unit") not in {"fraction", "%"}:
        raise ValueError("strain_unit must be fraction or %")
    stress_scale = {"Pa": 1e-6, "kPa": 1e-3, "MPa": 1, "GPa": 1000}
    if config.get("stress_unit") not in stress_scale:
        raise ValueError("stress_unit must be Pa, kPa, MPa, or GPa")
    original_x, original_y, frame, transform = curve(table, config, "strain", "stress")
    strain_scale = 0.01 if config["strain_unit"] == "%" else 1
    strain, stress = original_x * strain_scale, original_y * stress_scale[config["stress_unit"]]
    bounds = np.asarray(config["fit_range"], dtype=float) * strain_scale
    interval(strain, stress, bounds)
    selection = (strain >= bounds[0]) & (strain <= bounds[1])
    if selection.sum() < 3:
        raise ValueError("fit_range must contain at least three measured strain points")
    modulus, intercept = np.polyfit(strain[selection], stress[selection], 1)
    positive(modulus, "elastic modulus")
    predicted = modulus * strain[selection] + intercept
    residual = stress[selection] - predicted
    total = np.sum((stress[selection] - stress[selection].mean()) ** 2)
    if total <= 0:
        raise ValueError("elastic fit requires nonconstant stress")
    r_squared = float(1 - np.sum(residual**2) / total)
    offset = positive(config.get("yield_offset", 0.002), "yield_offset")
    offset_line = modulus * (strain - offset) + intercept
    difference = stress - offset_line
    roundoff = 4 * np.finfo(float).eps * np.maximum(np.abs(stress), np.abs(offset_line))
    difference[np.abs(difference) <= roundoff] = 0
    crossings = np.flatnonzero(
        (difference[:-1] > 0) & (difference[1:] <= 0) & (strain[1:] > bounds[1]) & (strain[1:] >= offset)
    )
    yield_strain, yield_stress = None, None
    warnings = []
    for i in crossings:
        fraction = difference[i] / (difference[i] - difference[i + 1])
        root = float(strain[i] + fraction * (strain[i + 1] - strain[i]))
        if root > bounds[1] and root >= offset:
            yield_strain = root
            yield_stress = float(stress[i] + fraction * (stress[i + 1] - stress[i]))
            break
    else:
        warnings.append(
            "No offset-line crossing was measured after the elastic fit range; yield stress is unavailable."
        )
    fracture = float(strain[-1]) if fracture_confirmed else None
    if fracture is None:
        warnings.append(
            "The final measured strain is not a confirmed fracture; "
            "set fracture_confirmed only with experimental evidence."
        )
    if r_squared < 0.99:
        warnings.append(
            "Elastic-region fit R-squared <0.99; inspect the supplied fit range and test compliance."
        )
    maximum = int(np.argmax(stress))
    frame["strain_fraction"] = strain
    frame["stress_MPa"] = stress
    frame["elastic_fit_MPa"] = modulus * strain + intercept
    frame["offset_line_MPa"] = offset_line
    return NodeResult(
        table=frame,
        data={
            "elastic_modulus_MPa": float(modulus),
            "fit_intercept_MPa": float(intercept),
            "fit_r_squared": r_squared,
            "fit_range_fraction": bounds.tolist(),
            "fit_source_rows": frame.loc[selection, "source_row"].tolist(),
            "yield_offset_fraction": offset,
            "yield_strain": yield_strain,
            "yield_stress_MPa": yield_stress,
            "ultimate_strength_MPa": float(stress[maximum]),
            "ultimate_strength_strain": float(strain[maximum]),
            "fracture_strain": fracture,
            "last_measured_strain": float(strain[-1]),
            "work_density_MJ_m3": float(trapezoid(stress, strain)),
            "curve_convention": "engineering stress-strain, monotonic tensile loading",
            "transform": transform,
        },
        warnings=warnings,
    )


def _eds(table, config, data):
    if table is None:
        table = pd.read_csv(read_path(config, data), encoding=config.get("encoding", "utf-8-sig"))
    element = config.get("element_column", "element")
    frame = require_table(table, [element])
    if frame[element].isna().any() or frame[element].astype(str).str.strip().eq("").any():
        raise ValueError("element identifiers must be nonempty")
    columns = config.get("percent_columns", [c for c in ("wt_percent", "at_percent") if c in frame])
    if not columns:
        raise ValueError(
            "externally quantified EDS requires wt_percent/at_percent or explicit percent_columns"
        )
    values = numeric_matrix(frame, columns)
    if np.any((values < 0) | (values > 100)):
        raise ValueError("EDS percent values must lie between 0 and 100")
    group_by = config.get("group_by")
    if group_by is not None:
        if not isinstance(group_by, str) or group_by not in frame or frame[group_by].isna().any():
            raise ValueError("group_by must name a composition identifier column without missing values")
        groups = frame.groupby(group_by, sort=False, observed=True).indices
    else:
        groups = {None: np.arange(len(frame))}
    identifiers = frame[element].astype(str).str.strip().str.casefold()
    group_totals = []
    warnings = [
        "EDS values are externally supplied; no peak deconvolution, "
        "ZAF correction or elemental quantification is performed."
    ]
    for group, rows in groups.items():
        if identifiers.iloc[rows].duplicated().any():
            raise ValueError("Repeated element within a composition: supply group_by or select a single spot")
        totals = dict(zip(columns, map(float, values[rows].sum(axis=0)), strict=True))
        group_label = str(group) if group is not None else None
        group_totals.append({"group": group_label, "totals": totals})
        if any(abs(total - 100) > 1 for total in totals.values()):
            warnings.append(
                f"EDS totals differ from 100 by >1 percentage point for {group_label or 'this composition'}."
            )
    return NodeResult(
        table=frame,
        data={
            "quantification": "externally supplied",
            "totals": group_totals[0]["totals"] if len(group_totals) == 1 else None,
            "group_by": group_by,
            "group_totals": group_totals,
            "transform": {"parameters": dict(config), "raw_preserved": True, "affected_rows": 0},
        },
        warnings=warnings,
    )


def sem_eds(table=None, *, config=None, data=None, tables=None):
    """SEM morphology or import of externally quantified EDS CSV/table."""
    config = dict(config or {})
    method = config.get("method", "image")
    if method == "eds":
        return _eds(table, config, data)
    if method != "image":
        raise ValueError("SEM/EDS method must be image or eds")
    from .materials_images import morphology

    return morphology(config, data)


def microstructure(table=None, *, config=None, data=None, tables=None):
    """Threshold or supervised pixel segmentation and calibrated component statistics."""
    from .materials_images import morphology

    return morphology(dict(config or {}), data)


_ENTRIES = [
    ("xrd", "XRD 数据处理", {"x": "x", "y": "y", "baseline": {"method": "none"}}),
    ("spectra", "FTIR/Raman 数据处理", {"x": "x", "y": "y", "normalization": "none"}),
    ("thermal", "TG/DSC 热分析", {"kind": "tg", "x_unit": "degC", "y_unit": "%"}),
    ("mechanics", "应力—应变分析", {"strain_unit": "fraction", "stress_unit": "MPa"}),
    ("sem_eds", "SEM/EDS 分析", {"method": "image", "segmentation": "threshold"}),
    ("microstructure", "显微结构图像分析", {"segmentation": "threshold"}),
]

CATALOG = [
    {
        "key": f"materials.{key}",
        "title": title,
        "function": f"materials_quality.science.materials:{key}",
        "category": "材料专业分析",
        "requirement": title,
        "table_input": key != "microstructure",
        "data_input": True,
        "tables_input": False,
        "default_config": default,
    }
    for key, title, default in _ENTRIES
]
