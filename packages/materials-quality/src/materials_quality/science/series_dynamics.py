"""Observed time-series summaries; HAC intervals are not future prediction intervals."""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.signal import find_peaks, savgol_filter

from .contracts import NodeResult, numeric_matrix, require_table


def _integer(c, key, default, minimum=1):
    value = c.get(key, default)
    if type(value) is not int or value < minimum:
        raise ValueError(f"{key} must be an integer >= {minimum}")
    return value


def analyze_series(table, config=None):
    c = dict(config or {})
    ident, time, value = c.get("curve_id", "curve_id"), c.get("time", "time"), c.get("value", "value")
    unit = c.get("time_unit")
    if unit not in {"s", "ms", "min", "h", "day"}:
        raise ValueError("time_unit must explicitly declare elapsed numeric time: ms, s, min, h, day")
    frame = require_table(table, [ident, time, value], min_rows=3)
    frame["input_row_position"] = np.arange(len(frame))
    numeric_matrix(frame, [time, value])
    if frame[ident].isna().any() or frame[ident].astype(str).str.strip().eq("").any():
        raise ValueError("curve identity cannot be missing or empty")
    group = c.get("group") or ("group" if "group" in frame else None)
    if group:
        require_table(frame, [group])
        if frame[group].isna().any() or (frame.groupby(ident, sort=False)[group].nunique() != 1).any():
            raise ValueError("whole curve identity must have exactly one nonmissing group")
    method = c.get("smoothing", "none")
    if method not in {"none", "moving", "savgol"}:
        raise ValueError("smoothing must be none, moving or savgol")
    cp_method = c.get("change_method", "window")
    if cp_method not in {"none", "window"}:
        raise ValueError("change_method must be none or window")
    alpha = float(c.get("alpha", 0.05))
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie between 0 and 1")
    threshold = float(c.get("spike_threshold", 3.5))
    change_threshold = float(c.get("change_threshold", 3))
    growth_min_points = _integer(c, "growth_min_points", 3, 2)
    growth_duration = float(c.get("growth_min_duration", 0))
    growth_slope = float(c.get("growth_min_slope", 0))
    if (
        not np.isfinite([threshold, change_threshold, growth_duration, growth_slope]).all()
        or min(threshold, change_threshold) <= 0
        or growth_duration < 0
        or growth_slope < 0
    ):
        raise ValueError("thresholds must be finite positive; growth duration/slope nonnegative")
    points, features, events = [], [], []
    for identity, block in frame.groupby(ident, sort=False, observed=True):
        b = block.copy().reset_index(drop=True)
        if len(b) < 3:
            raise ValueError(f"curve {identity} needs at least three observations")
        t = b[time].to_numpy(dtype=float)
        y = b[value].to_numpy(dtype=float)
        if len(np.unique(t)) != len(t):
            raise ValueError(f"duplicate time in curve {identity}")
        if c.get("sort", False):
            order = np.argsort(t)
            b = b.iloc[order].reset_index(drop=True)
            t = t[order]
            y = y[order]
        if np.any(np.diff(t) <= 0):
            raise ValueError("time must increase within every curve; enable sort explicitly if needed")
        filtered = y.copy()
        if method != "none":
            window = _integer(c, "smooth_window", 5)
            if window > len(y) or window % 2 != 1:
                raise ValueError("smooth_window must be odd and not exceed curve length")
            if method == "savgol":
                if not np.allclose(np.diff(t), np.diff(t)[0], rtol=1e-6, atol=1e-12):
                    raise ValueError("Savitzky-Golay requires uniform elapsed time spacing")
                order = _integer(c, "smooth_order", 2, 0)
                if order >= window:
                    raise ValueError("smooth_order must be below smooth_window")
                filtered = savgol_filter(y, window, order)
            else:
                filtered = pd.Series(y).rolling(window, center=True, min_periods=1).mean().to_numpy()
        # A local median reference remains informative when smoothing is disabled.
        spike_window = min(5, len(y) if len(y) % 2 else len(y) - 1)
        reference = (
            pd.Series(y).rolling(spike_window, center=True, min_periods=spike_window).median().to_numpy()
        )
        spike_valid = np.isfinite(reference)
        reference = np.where(spike_valid, reference, y)
        residual = y - reference
        center = float(np.median(residual))
        scale = 1.4826 * float(np.median(np.abs(residual - center)))
        tolerance = np.finfo(float).eps * max(1.0, float(np.max(np.abs(y)))) * 32
        score = np.abs(residual - center) / max(scale, tolerance)
        spikes = score > threshold
        elapsed = t - t[0]
        lags = min(_integer(c, "hac_lags", 1, 0), len(y) - 2)
        fit = sm.OLS(y, sm.add_constant(elapsed)).fit(cov_type="HAC", cov_kwds={"maxlags": lags}, use_t=True)
        ci = np.asarray(fit.conf_int(alpha=alpha))
        trend = fit.predict(sm.add_constant(elapsed))
        b["elapsed_time"] = elapsed
        b["smoothed"] = filtered
        b["residual"] = residual
        b["spike_score"] = score
        b["spike"] = spikes
        b["spike_evaluated"] = spike_valid
        b["linear_trend"] = trend
        prediction = fit.get_prediction(sm.add_constant(elapsed)).summary_frame(alpha=alpha)
        b["trend_mean_ci_low"] = prediction.mean_ci_lower.to_numpy()
        b["trend_mean_ci_high"] = prediction.mean_ci_upper.to_numpy()
        cp_scores = np.zeros(len(y))
        if cp_method == "window":
            w = _integer(c, "change_window", 5, 2)
            for i in range(w, len(y) - w + 1):
                left, right = y[i - w : i], y[i : i + w]
                se = np.sqrt(left.var(ddof=1) / w + right.var(ddof=1) / w)
                cp_scores[i] = abs(right.mean() - left.mean()) / max(float(se), tolerance)
            peaks, _ = find_peaks(cp_scores, height=change_threshold, distance=w)
            for i in peaks:
                events.append(
                    {
                        "curve_id": identity,
                        "event": "change_point",
                        "time": float(t[i]),
                        "score": float(cp_scores[i]),
                        "method": "adjacent_window_mean_difference_over_standard_error",
                    }
                )
        b["change_score"] = cp_scores
        positive = np.diff(filtered) / np.diff(t) > growth_slope
        edges = np.flatnonzero(np.diff(np.r_[False, positive, False].astype(int))).reshape(-1, 2)
        for start, stop in edges:
            if stop - start + 1 >= growth_min_points and t[stop] - t[start] >= growth_duration:
                events.append(
                    {
                        "curve_id": identity,
                        "event": "sustained_growth",
                        "start_time": float(t[start]),
                        "end_time": float(t[stop]),
                        "points": int(stop - start + 1),
                        "duration": float(t[stop] - t[start]),
                    }
                )
        for i in np.flatnonzero(spikes):
            events.append(
                {
                    "curve_id": identity,
                    "event": "spike",
                    "time": float(t[i]),
                    "score": float(score[i]),
                    "method": "local_median_residual_MAD",
                }
            )
        record = {
            "curve_id": identity,
            "count": len(y),
            "start_time": float(t[0]),
            "end_time": float(t[-1]),
            "slope": float(fit.params[1]),
            "intercept_at_start": float(fit.params[0]),
            "slope_ci_low": float(ci[1, 0]),
            "slope_ci_high": float(ci[1, 1]),
            "spike_count": int(spikes.sum()),
            "time_unit": unit,
            "slope_unit": f"{c.get('value_unit', 'unspecified')}/{unit}",
        }
        if group:
            record[group] = b[group].iloc[0]
        features.append(record)
        points.append(b)
    point_frame = pd.concat(points, ignore_index=True)
    point_frame.attrs["units"] = {
        key: val for key, val in frame.attrs.get("units", {}).items() if key in point_frame
    }
    point_frame.attrs["units"].update(
        {
            time: unit,
            "elapsed_time": unit,
            value: c.get("value_unit", "unspecified"),
            **{
                key: c.get("value_unit", "unspecified")
                for key in ["smoothed", "residual", "linear_trend", "trend_mean_ci_low", "trend_mean_ci_high"]
            },
        }
    )
    feature_frame = pd.DataFrame(features)
    feature_frame.attrs["units"] = {
        key: f"{c.get('value_unit', 'unspecified')}/{unit}"
        for key in ["slope", "slope_ci_low", "slope_ci_high"]
    }
    feature_frame.attrs["units"].update(
        {"start_time": unit, "end_time": unit, "intercept_at_start": c.get("value_unit", "unspecified")}
    )
    return NodeResult(
        table=point_frame,
        features=feature_frame,
        data={
            "events": events,
            "curve_count": len(features),
            "time_unit": unit,
            "smoothing": method,
            "change_method": cp_method,
            "confidence_method": "OLS mean trend with HAC covariance and Student t reference",
            "alpha": alpha,
            "parameters": c,
        },
        warnings=[
            "Change scores and MAD spike flags are descriptive thresholds, not calibrated p-values.",
            "Intervals describe the observed linear mean trend; they do not predict future observations. "
            "Centered smoothing uses adjacent measured points.",
            "Spike flags use full centered local median windows only; "
            "boundary points without a full window are marked unevaluated.",
            "HAC uncertainty is asymptotic and may be unstable for short curves; "
            "a linear trend is an empirical summary.",
        ],
    )
