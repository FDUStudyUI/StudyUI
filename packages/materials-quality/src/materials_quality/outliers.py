"""Flag suspicious observations without treating statistical rarity as an error."""

import math

import numpy as np

from materials_quality.common import ReportBuilder, groups, missing, numeric, select_columns


def _finite_parameter(value, name, *, positive=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite numeric")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be finite numeric") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be {'positive and ' if positive else ''}finite")
    return result


def _exact_bound(value):
    try:
        return numeric(value)
    except (ValueError, ArithmeticError) as exc:
        raise ValueError("range bounds must be finite numeric values") from exc


def _statistical_flags(values, method, multiplier, mad_threshold):
    # Overflowed intermediates must not silently compare False and imply success.
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        if method == "iqr":
            q1, q3 = np.quantile(values, [0.25, 0.75])
            spread = q3 - q1
            lower, upper = q1 - multiplier * spread, q3 + multiplier * spread
            if not np.isfinite([q1, q3, lower, upper]).all():
                raise FloatingPointError("non-finite IQR thresholds")
            return (values < lower) | (values > upper), {
                "lower": float(lower),
                "upper": float(upper),
                "q1": float(q1),
                "q3": float(q3),
            }
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        if not np.isfinite([median, mad]).all():
            raise FloatingPointError("non-finite MAD baseline")
        detail = {"median": median, "mad": mad, "threshold": mad_threshold}
        if mad == 0:
            detail["fallback"] = "deviations_from_constant_median"
            return values != median, detail
        scores = 0.6744897501960817 * np.abs(values - median) / mad
        if not np.isfinite(scores).all():
            raise FloatingPointError("non-finite robust scores")
        return scores > mad_threshold, detail


def check_outliers(
    table,
    *,
    columns,
    method,
    bounds=None,
    multiplier=1.5,
    mad_threshold=3.5,
    group_by=None,
    finding_limit=500,
):
    report = ReportBuilder(
        table,
        "outliers",
        {
            "columns": columns,
            "method": method,
            "bounds": bounds,
            "multiplier": multiplier,
            "mad_threshold": mad_threshold,
            "group_by": group_by,
        },
        finding_limit,
    )
    selected = select_columns(table, columns)
    if method not in {"range", "iqr", "mad"}:
        raise ValueError("method must be range, iqr or mad")
    multiplier = _finite_parameter(multiplier, "multiplier", positive=True)
    mad_threshold = _finite_parameter(mad_threshold, "mad_threshold", positive=True)
    parsed_bounds = {}
    if method == "range":
        if not isinstance(bounds, dict) or any(c not in bounds for c in selected):
            raise ValueError("range checks require explicit bounds for every selected column")
        for column in selected:
            spec = bounds[column]
            if not isinstance(spec, dict) or not set(spec) <= {"min", "max"} or not spec:
                raise ValueError("bounds entries must provide min and/or max")
            lower = _exact_bound(spec["min"]) if "min" in spec else None
            upper = _exact_bound(spec["max"]) if "max" in spec else None
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("min must not exceed max")
            parsed_bounds[column] = (lower, upper)
    thresholds = []
    for key, positions in groups(table, group_by):
        for column in selected:
            valid_positions, numbers = [], []
            represented = {}
            precision_lost = False
            for position in positions:
                value = table[column].iloc[position]
                if missing(value):
                    continue
                try:
                    exact = numeric(value)
                    number = exact if method == "range" else float(exact)
                    if method != "range" and not math.isfinite(number):
                        raise ArithmeticError("overflow in numeric conversion")
                except ArithmeticError:
                    report.add(
                        "NON_FINITE",
                        "error",
                        column=column,
                        position=position,
                        reason="Non-finite or numerically unrepresentable value.",
                    )
                    continue
                except ValueError:
                    report.add(
                        "NON_NUMERIC",
                        "error",
                        column=column,
                        position=position,
                        reason="Outlier detection requires numeric values; no coercion was applied.",
                    )
                    continue
                if method != "range":
                    if (exact != 0 and number == 0) or (
                        number in represented and represented[number] != exact
                    ):
                        precision_lost = True
                        report.add(
                            "NUMERICAL_LIMIT",
                            "warning",
                            column=column,
                            position=position,
                            reason="Distinct exact values collapsed to the same float, or a nonzero value "
                            "underflowed to zero; no statistical baseline was used.",
                        )
                    represented[number] = exact
                valid_positions.append(position)
                numbers.append(number)
            values = numbers if method == "range" else np.asarray(numbers, dtype=float)
            detail = {"column": column, "group": key, "valid_count": len(values), "method": method}
            if precision_lost:
                detail["insufficient"] = True
                thresholds.append(detail)
                continue
            if method != "range" and len(values) < 3:
                detail["insufficient"] = True
                if len(table):
                    report.add(
                        "INSUFFICIENT_BASELINE",
                        "warning",
                        column=column,
                        reason=(
                            f"Group {key!r} has fewer than 3 finite values; no {method} threshold estimated."
                        ),
                    )
                thresholds.append(detail)
                continue
            if method == "range":
                lower, upper = parsed_bounds[column]
                detail.update(lower=lower, upper=upper)
                flags = np.array(
                    [(lower is not None and v < lower) or (upper is not None and v > upper) for v in values],
                    dtype=bool,
                )
            else:
                try:
                    flags, stats = _statistical_flags(values, method, multiplier, mad_threshold)
                except (FloatingPointError, OverflowError):
                    detail["insufficient"] = True
                    report.add(
                        "NUMERICAL_LIMIT",
                        "warning",
                        column=column,
                        reason=f"{method} calculation exceeded float precision/range for group {key!r}; "
                        "no statistical verdict was issued. Consider explicit physical bounds.",
                    )
                    thresholds.append(detail)
                    continue
                detail.update(stats)
            thresholds.append(detail)
            for position, flag in zip(valid_positions, flags, strict=True):
                if flag:
                    report.add(
                        f"OUTLIER_{method.upper()}",
                        "warning",
                        column=column,
                        position=position,
                        reason=f"Outside the declared/estimated {method} rule for group {key!r}. "
                        "Suspicious observation only; retained for researcher review.",
                    )
    return report.finish({"thresholds": thresholds, "modified": False})
