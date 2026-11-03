"""Validated curve operations used by material nodes (no material identity inference)."""

from copy import deepcopy

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid
from scipy.optimize import least_squares, linear_sum_assignment, nnls
from scipy.signal import find_peaks, savgol_filter

from .contracts import numeric_matrix, require_table


def positive(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def curve(table, config, default_x="x", default_y="y"):
    names = [config.get("x", default_x), config.get("y", default_y)]
    frame = require_table(table, names, min_rows=3)
    values = numeric_matrix(frame, names)
    sort = config.get("sort", False)
    if type(sort) is not bool:
        raise ValueError("sort must be a JSON boolean (true or false)")
    order = np.argsort(values[:, 0], kind="stable") if sort else np.arange(len(values))
    x, y = values[order].T
    if np.any(np.diff(x) <= 0):
        raise ValueError("coordinates must be strictly increasing; use sort=true for unordered unique points")
    result = pd.DataFrame({"source_row": order, "x": x, "raw_y": y})
    transform = {
        "parameters": deepcopy(config),
        "source_columns": names,
        "affected_rows": len(frame),
        "sorted": not np.array_equal(order, np.arange(len(order))),
        "raw_preserved": True,
    }
    return x, y, result, transform


def baseline(x, y, config):
    options = config.get("baseline", {"method": "none"})
    if isinstance(options, str):
        options = {"method": options}
    method = options.get("method", "none")
    if method == "none":
        return np.zeros_like(y)
    if method == "constant":
        value = float(options.get("value", 0))
        if not np.isfinite(value):
            raise ValueError("baseline value must be finite")
        return np.full_like(y, value)
    if method == "linear":
        return np.interp(x, [x[0], x[-1]], [y[0], y[-1]])
    if method == "anchors":
        points = np.asarray(options.get("points", []), dtype=float)
        if (
            points.ndim != 2
            or points.shape[1] != 2
            or len(points) < 2
            or not np.isfinite(points).all()
            or np.any(np.diff(points[:, 0]) <= 0)
        ):
            raise ValueError("baseline anchors require >=2 finite increasing [x, y] points")
        if points[0, 0] > x[0] or points[-1, 0] < x[-1]:
            raise ValueError("baseline anchors must cover the measured coordinate range")
        return np.interp(x, points[:, 0], points[:, 1])
    raise ValueError("baseline method must be none, constant, linear, or anchors")


def processed_curve(table, config):
    x, y, frame, transform = curve(table, config)
    base = baseline(x, y, config)
    corrected = y - base
    window = config.get("smooth_window", 0)
    if type(window) is not int or window < 0:
        raise ValueError("smooth_window must be zero or a positive odd integer")
    smooth = corrected.copy()
    if window:
        poly = config.get("smooth_order", 2)
        if type(poly) is not int or poly < 0 or window % 2 != 1 or window > len(x) or window <= poly:
            raise ValueError(
                "smoothing requires odd window <= sample count and window > polynomial order >=0"
            )
        if not np.allclose(np.diff(x), np.diff(x)[0], rtol=1e-5, atol=1e-12):
            raise ValueError(
                "Savitzky-Golay smoothing requires evenly spaced coordinates; resample explicitly"
            )
        smooth = savgol_filter(corrected, window, poly)
    frame["baseline"] = base
    frame["corrected"] = corrected
    frame["smoothed"] = smooth
    return x, smooth, frame, transform


def interval(x, y, bounds):
    bounds = np.asarray(bounds, dtype=float)
    if bounds.shape != (2,) or not np.isfinite(bounds).all():
        raise ValueError("integration/fit range must be two finite coordinates")
    lo, hi = bounds
    if not x[0] <= lo < hi <= x[-1]:
        raise ValueError("range must be increasing and inside measured coordinates")
    interior = (x > lo) & (x < hi)
    xx = np.r_[lo, x[interior], hi]
    yy = np.r_[np.interp(lo, x, y), y[interior], np.interp(hi, x, y)]
    return xx, yy


def integrate_ranges(x, y, config):
    ranges = config.get("area_ranges", [[float(x[0]), float(x[-1])]])
    if not isinstance(ranges, (list, tuple)) or not ranges:
        raise ValueError("area_ranges must contain at least one [lower, upper] interval")
    return [
        {"range": list(bounds), "area": float(trapezoid(*interval(x, y, bounds)[::-1]))} for bounds in ranges
    ]


def peak_detection_settings(x, y, config):
    """Resolve reproducible thresholds in processed-signal/native-coordinate units.

    Noise-reference MAD uses only an explicitly declared measured window. Its
    normal scaling is an assumption, not a calibration of false-positive rates;
    contamination, drift and correlated noise require external validation.

    Modes are ``legacy_relative`` (5% of full processed range), ``absolute``
    (positive ``prominence``), or ``noise_reference`` (positive
    ``noise_multiplier`` times normal-scaled MAD in ``noise_window=[lo, hi]``).
    A legacy prominence-only config selects absolute mode. Noise windows and
    ``peak_distance_x`` use native x units. Returned ``effective_prominence``
    uses processed response units; ``peak_distance`` retains sample units.
    """
    mode = config.get("prominence_mode", "absolute" if "prominence" in config else "legacy_relative")
    if mode not in {"legacy_relative", "absolute", "noise_reference"}:
        raise ValueError("prominence_mode must be legacy_relative, absolute, or noise_reference")
    settings = {"prominence_mode": mode, "signal": "baseline-corrected smoothed before normalization"}
    if mode == "absolute":
        prominence = positive(config.get("prominence"), "prominence")
        settings["threshold_source"] = "explicit absolute prominence"
    elif mode == "legacy_relative":
        if "prominence" in config:
            raise ValueError(
                "explicit prominence conflicts with prominence_mode=legacy_relative; use absolute"
            )
        prominence = max(float(np.ptp(y)) * 0.05, np.finfo(float).eps)
        settings.update({"threshold_source": "5% of full processed-signal range", "relative_fraction": 0.05})
    else:
        if "prominence" in config:
            raise ValueError(
                "explicit prominence conflicts with prominence_mode=noise_reference; use absolute"
            )
        try:
            bounds = np.asarray(config.get("noise_window"), dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError("noise_window must be two finite increasing native coordinates") from exc
        if (
            bounds.shape != (2,)
            or not np.isfinite(bounds).all()
            or not x[0] <= bounds[0] < bounds[1] <= x[-1]
        ):
            raise ValueError(
                "noise_window must be two finite increasing native coordinates inside the measured range"
            )
        selected = y[(x >= bounds[0]) & (x <= bounds[1])]
        if len(selected) < 5:
            raise ValueError("noise_window requires at least five measured points")
        multiplier = positive(config.get("noise_multiplier", 3), "noise_multiplier")
        noise = float(np.median(np.abs(selected - np.median(selected))) * 1.482602218505602)
        if not np.isfinite(noise) or noise <= 0:
            raise ValueError(
                "noise_window has no positive MAD noise estimate; "
                "declare another window or absolute threshold"
            )
        prominence = multiplier * noise
        settings.update(
            {
                "threshold_source": "declared noise window MAD times noise_multiplier",
                "noise_window": bounds.tolist(),
                "noise_window_unit": config.get("x_unit", "native x unit"),
                "noise_multiplier": multiplier,
                "noise_estimate": noise,
                "noise_sample_count": len(selected),
                "noise_estimator": "median_absolute_deviation_normal_scaled",
                "noise_assumptions": (
                    "normal-reference MAD scaling; window must represent background; "
                    "drift, peaks and correlation are not corrected"
                ),
            }
        )
    settings["effective_prominence"] = positive(prominence, "prominence")
    distance = config.get("peak_distance", 1)
    if type(distance) is not int or distance < 1:
        raise ValueError("peak_distance must be an integer >=1 measured in samples")
    settings["peak_distance"] = distance
    settings["peak_distance_unit"] = "samples"
    physical = config.get("peak_distance_x")
    settings["peak_distance_x"] = positive(physical, "peak_distance_x") if physical is not None else None
    settings["peak_distance_x_unit"] = config.get("x_unit", "native x unit")
    settings["distance_method"] = (
        "sample-distance selection then coordinate-distance greedy suppression by descending height; "
        "ties choose lower coordinate; no resampling"
        if physical is not None
        else "sample-distance selection"
    )
    return settings


def peak_records(x, y, config):
    settings = peak_detection_settings(x, y, config)
    indices, props = find_peaks(
        y, prominence=settings["effective_prominence"], distance=settings["peak_distance"]
    )
    if settings["peak_distance_x"] is not None:
        accepted = []
        for k in sorted(range(len(indices)), key=lambda k: (-y[indices[k]], x[indices[k]])):
            if all(abs(x[indices[k]] - x[indices[j]]) >= settings["peak_distance_x"] for j in accepted):
                accepted.append(k)
        keep = sorted(accepted)
        indices = indices[keep]
        props = {name: values[keep] for name, values in props.items()}
    records = []
    for k, idx in enumerate(indices):
        half = y[idx] / 2
        left = np.flatnonzero(y[:idx] <= half) if y[idx] > 0 else []
        right = np.flatnonzero(y[idx + 1 :] <= half) if y[idx] > 0 else []
        width = None
        if len(left) and len(right):
            li, ri = int(left[-1]), int(idx + 1 + right[0])
            lx = x[li] + (half - y[li]) * (x[li + 1] - x[li]) / (y[li + 1] - y[li])
            rx = x[ri - 1] + (half - y[ri - 1]) * (x[ri] - x[ri - 1]) / (y[ri] - y[ri - 1])
            width = float(rx - lx)
        lb, rb = int(props["left_bases"][k]), int(props["right_bases"][k])
        records.append(
            {
                "index": int(idx),
                "position": float(x[idx]),
                "height": float(y[idx]),
                "prominence": float(props["prominences"][k]),
                "fwhm": width,
                "fwhm_definition": "width at half baseline-corrected peak height",
                "left_base_index": lb,
                "right_base_index": rb,
                "area_between_bases": float(trapezoid(y[lb : rb + 1], x[lb : rb + 1])),
                "peak_detection": deepcopy(settings),
            }
        )
    return records


def references(data, config):
    refs = config.get("references") or (data or {}).get("references")
    if not isinstance(refs, list) or not refs:
        raise ValueError("supply nonempty references with names and measured profiles or peak lists")
    names = [r.get("name") for r in refs]
    if any(not isinstance(n, str) or not n.strip() for n in names) or len(set(names)) != len(names):
        raise ValueError("reference names must be unique nonempty strings")
    for ref in refs:
        if ref.get("x_unit") and config.get("x_unit") != ref["x_unit"]:
            raise ValueError("reference x_unit must match explicitly supplied measurement x_unit")
    return refs


def reference_matrix(x, refs):
    profiles = []
    for ref in refs:
        rx, ry = np.asarray(ref.get("x", []), dtype=float), np.asarray(ref.get("y", []), dtype=float)
        if (
            rx.ndim != 1
            or ry.shape != rx.shape
            or len(rx) < 2
            or not np.isfinite(rx).all()
            or not np.isfinite(ry).all()
            or np.any(np.diff(rx) <= 0)
        ):
            raise ValueError("reference profiles need finite, increasing x and same-length y")
        if rx[0] > x[0] or rx[-1] < x[-1]:
            raise ValueError(
                "reference profiles must cover the entire measurement range; extrapolation is forbidden"
            )
        if np.min(ry) < 0 or np.linalg.norm(ry) == 0:
            raise ValueError("reference profiles must be nonnegative and nonzero after baseline correction")
        sampled = np.interp(x, rx, ry)
        if np.linalg.norm(sampled) == 0:
            raise ValueError("reference profile has no signal in the measured range")
        profiles.append(sampled)
    return np.column_stack(profiles)


def match_references(x, y, peaks, config, data):
    method = config.get("match")
    if method in (None, False, "none"):
        return []
    refs = references(data, config)
    results = []
    if method == "profile":
        matrix = reference_matrix(x, refs)
        norm = np.linalg.norm(y)
        if norm == 0:
            raise ValueError("cannot match a zero spectrum")
        for i, ref in enumerate(refs):
            score = np.dot(y, matrix[:, i]) / (norm * np.linalg.norm(matrix[:, i]))
            results.append(
                {
                    "name": ref["name"],
                    "score": float(score),
                    "metric": "cosine similarity",
                    "source": ref.get("source", "user-supplied reference"),
                }
            )
    elif method == "peaks":
        tolerance = positive(config.get("match_tolerance", 0.1), "match_tolerance")
        observed = np.array([p["position"] for p in peaks])
        for ref in refs:
            positions = np.asarray(ref.get("peaks", []), dtype=float)
            if positions.ndim != 1 or not len(positions) or not np.isfinite(positions).all():
                raise ValueError("peak matching references require finite nonempty peaks lists")
            covered = positions[(positions >= x[0]) & (positions <= x[-1])]
            pairs = []
            if len(observed) and len(covered):
                distances = np.abs(observed[:, None] - covered[None, :])
                row, col = linear_sum_assignment(np.where(distances <= tolerance, distances, 1e12))
                pairs = [
                    {
                        "observed": float(observed[i]),
                        "reference": float(covered[j]),
                        "difference": float(distances[i, j]),
                    }
                    for i, j in zip(row, col, strict=False)
                    if distances[i, j] <= tolerance
                ]
            count = len(pairs)
            coverage = count / len(covered) if len(covered) else 0.0
            precision = count / len(observed) if len(observed) else 0.0
            results.append(
                {
                    "name": ref["name"],
                    "score": 2 * count / (len(covered) + len(observed))
                    if len(covered) + len(observed)
                    else 0.0,
                    "metric": "peak-list F1 within measured range",
                    "matched_count": count,
                    "reference_coverage": coverage,
                    "observed_coverage": precision,
                    "reference_peaks_outside_range": len(positions) - len(covered),
                    "pairs": pairs,
                    "tolerance": tolerance,
                    "source": ref.get("source", "user-supplied reference"),
                }
            )
    else:
        raise ValueError("match must be none, profile, or peaks")
    return sorted(results, key=lambda r: r["score"], reverse=True)


def fit_pattern(x, y, config, data):
    method = config.get("whole_pattern", "none")
    if method == "none":
        return None, None
    if method == "reference":
        refs = references(data, config)
        matrix = reference_matrix(x, refs)
        if np.linalg.matrix_rank(matrix) < len(refs):
            raise ValueError(
                "reference profiles are linearly dependent; mixture coefficients are not identifiable"
            )
        weights, _ = nnls(matrix, y)
        fitted = matrix @ weights
        info = {
            "model": "nonnegative linear combination of supplied reference profiles",
            "coefficients": dict(zip([r["name"] for r in refs], map(float, weights), strict=False)),
            "coefficient_meaning": "profile amplitude scales, not phase mass fractions",
            "references": [{"name": r["name"], "source": r.get("source", "user-supplied")} for r in refs],
        }
    elif method == "gaussian":
        guesses = config.get("fit_peaks")
        if not isinstance(guesses, list) or not guesses:
            raise ValueError(
                "Gaussian whole-pattern fitting requires fit_peaks with center, sigma and amplitude"
            )
        p0 = []
        for peak in guesses:
            center = float(peak["center"])
            if not x[0] < center < x[-1]:
                raise ValueError("initial peak center must be inside measurement range")
            p0.extend([positive(peak["amplitude"], "amplitude"), center, positive(peak["sigma"], "sigma")])
        if len(p0) >= len(x):
            raise ValueError("fit requires more measured points than parameters")
        low = [0, x[0], np.min(np.diff(x)) / 10] * len(guesses)
        high = [np.inf, x[-1], (x[-1] - x[0]) * 2] * len(guesses)

        def model(parameters):
            p = np.asarray(parameters).reshape(-1, 3)
            return np.sum(p[:, 0, None] * np.exp(-0.5 * ((x - p[:, 1, None]) / p[:, 2, None]) ** 2), axis=0)

        fit = least_squares(lambda parameters: model(parameters) - y, p0, bounds=(low, high), max_nfev=10000)
        if not fit.success:
            raise ValueError(f"Gaussian profile fit did not converge: {fit.message}")
        fitted = model(fit.x)
        info = {
            "model": "empirical sum of Gaussian profiles",
            "converged": bool(fit.success),
            "peaks": [
                {
                    "amplitude": float(a),
                    "center": float(c),
                    "sigma": float(s),
                    "fwhm": float(2 * np.sqrt(2 * np.log(2)) * s),
                    "area": float(a * s * np.sqrt(2 * np.pi)),
                }
                for a, c, s in sorted(fit.x.reshape(-1, 3), key=lambda p: p[1])
            ],
        }
    else:
        raise ValueError("whole_pattern must be none, reference, or gaussian")
    residual = y - fitted
    total = np.sum((y - y.mean()) ** 2)
    info.update(
        {
            "rmse": float(np.sqrt(np.mean(residual**2))),
            "r_squared": float(1 - np.sum(residual**2) / total) if total > 0 else None,
            "structural_refinement": False,
        }
    )
    return fitted, info
