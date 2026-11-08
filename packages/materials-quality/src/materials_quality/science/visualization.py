"""Numerical figures and verified table/report exports; raw inputs stay intact."""

import hashlib
import json
from numbers import Integral
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
import pandas as pd

from materials_quality.common import numeric
from materials_quality.units import _unit

from .contracts import NodeResult, artifact_path, numeric_matrix, require_table
from .plot_style import PALETTE as _COLORS
from .plot_style import figure as _figure
from .plot_style import finish as _finish
from .plot_style import legend, plot_operation, styled_series


def _safe(value):
    def fallback(x):
        if isinstance(x, np.ndarray):
            return x.tolist()
        if isinstance(x, np.generic):
            return x.item()
        return str(x)

    return json.loads(json.dumps(value, default=fallback, allow_nan=False))


def _method(c, methods, default):
    method = c.get("method", default)
    if method not in methods:
        raise ValueError(f"method must be one of {sorted(methods)}")
    return method


def _label(column, c):
    unit = c.get("units", {}).get(column)
    label = c.get("labels", {}).get(column, column)
    return f"{label} ({unit})" if unit else str(label)


def _grouped(frame, c):
    group = c.get("group")
    if group:
        require_table(frame, [group])
        if frame[group].isna().any():
            raise ValueError("group labels cannot be missing")
        return [(str(label), block) for label, block in frame.groupby(group, sort=False, observed=True)]
    return [("all", frame)]


@plot_operation
def performance(table=None, *, config=None, data=None, tables=None):
    c = config or {}
    method = _method(c, {"scatter", "bar", "box", "violin"}, "scatter")
    x, y = c.get("x"), c.get("y")
    frame = require_table(table, [y])
    numeric_matrix(frame, [y])
    if method == "scatter":
        numeric_matrix(frame, [x])
    blocks = _grouped(frame, c)
    if method == "violin" and any(len(b) < 2 or np.ptp(b[y].to_numpy(float)) == 0 for _, b in blocks):
        raise ValueError("violin requires at least two varying values in each group")
    fig, ax = _figure(c)
    group_data = []
    for i, (label, block) in enumerate(blocks):
        style = styled_series(label, c)
        values = block[y].to_numpy(float)
        record = {"label": label, "n": len(block), "y": values.tolist(), "mean": float(values.mean())}
        if method == "scatter":
            xx = block[x].to_numpy(float)
            ax.scatter(
                xx,
                values,
                s=30,
                alpha=0.85,
                label=label,
                color=style["color"],
                marker=style["marker"],
                edgecolors="white",
                linewidths=0.4,
                rasterized=len(values) > 2000,
                zorder=3,
            )
            record["x"] = xx.tolist()
        elif method == "bar":
            # Error bars express observed sample spread, never significance.
            error = float(values.std(ddof=1)) if len(values) > 1 else 0.0
            ax.bar(
                i,
                values.mean(),
                yerr=error,
                capsize=4,
                color=style["color"],
                alpha=0.4,
                edgecolor=style["color"],
                error_kw={"ecolor": "#243746", "linewidth": 1.1},
            )
            record["error"] = error
        group_data.append(record)
    if method == "box":
        boxes = ax.boxplot(
            [b[y].to_numpy(float) for _, b in blocks],
            tick_labels=[label for label, _ in blocks],
            patch_artist=True,
            showfliers=False,
            medianprops={"color": "#243746", "linewidth": 1.5},
        )
        for box, (label, _) in zip(boxes["boxes"], blocks, strict=True):
            box.set(facecolor=styled_series(label, c)["color"], alpha=0.3)
    elif method == "violin":
        parts = ax.violinplot([b[y].to_numpy(float) for _, b in blocks], showmeans=True, showextrema=True)
        for body, (label, _) in zip(parts["bodies"], blocks, strict=True):
            body.set_facecolor(styled_series(label, c)["color"])
            body.set_alpha(0.25)
        ax.set_xticks(np.arange(1, len(blocks) + 1), [label for label, _ in blocks])
    elif method == "bar":
        ax.set_xticks(np.arange(len(blocks)), [label for label, _ in blocks])
    if method in {"bar", "box", "violin"}:
        offset = 0 if method == "bar" else 1
        for i, (label, block) in enumerate(blocks):
            values = block[y].to_numpy(float)
            style = styled_series(label, c)
            ax.scatter(
                i + offset + np.linspace(-0.12, 0.12, len(values)),
                values,
                s=16,
                color=style["color"],
                marker=style["marker"],
                alpha=0.8,
                edgecolors="white",
                linewidths=0.3,
                zorder=4,
                rasterized=len(values) > 2000,
            )
        ax.set_xticks(
            np.arange(len(blocks)) + offset, [f"{label}\n(n={len(block)})" for label, block in blocks]
        )
    if c.get("group") and method == "scatter":
        legend(ax)
    labels = {"x": _label(x, c) if method == "scatter" else str(c.get("group", "Group")), "y": _label(y, c)}
    ax.set(xlabel=labels["x"], ylabel=labels["y"], title=str(c.get("title", "Performance comparison")))
    result = _finish(
        fig,
        c,
        f"performance-{method}",
        {
            "method": method,
            "labels": labels,
            "plot_data": {"groups": group_data},
            "error_definition": "sample standard deviation" if method == "bar" else None,
            "observations_displayed": len(frame),
            "statistical_definition": {
                "bar": "Mean ± sample SD; dots: all observations",
                "box": "Median; box: Q1–Q3; whiskers: 1.5×IQR; dots: all observations",
                "violin": "Gaussian KDE and mean; dots: all observations",
                "scatter": "All supplied observations",
            }[method],
        },
    )
    if method == "bar" and any(len(b) == 1 for _, b in blocks):
        result.warnings.append("Singleton groups have no estimated uncertainty; displayed error is zero.")
    if method == "violin" and any(len(b) < 5 for _, b in blocks):
        result.warnings.append("Small-sample KDE is exploratory; inspect all overlaid observations.")
    return result


def _ordered_curve(block, x, y):
    matrix = numeric_matrix(block, [x, y])
    if len(matrix) < 2 or np.any(np.diff(matrix[:, 0]) <= 0):
        raise ValueError(
            "curves require strictly increasing acquisition coordinates; "
            "select a monotonic loading segment explicitly instead of sorting loading/unloading points"
        )
    return matrix[:, 0], matrix[:, 1]


@plot_operation
def spectra(table=None, *, config=None, data=None, tables=None):
    """Plot spectra; CI95 requires an explicit independent-unit declaration.

    Unlike descriptive IQR/SD, legacy CI95 configurations must now confirm
    independence. The default product policy requires n>=3; model_based is an
    explicit Student-t model opt-in for n=2. It never establishes independence
    from curve count or overrides known repeated-unit/paired contracts.
    """
    c = config or {}
    method = _method(c, {"line", "overlay", "difference", "band"}, "overlay")
    if method == "band":
        from scipy import stats

        x, y, identity = c.get("x"), c.get("y"), c.get("curve_id", "curve_id")
        frame = require_table(table, [x, y, identity], min_rows=2)
        numeric_matrix(frame, [x, y])
        if frame[identity].isna().any() or frame[identity].astype(str).str.strip().eq("").any():
            raise ValueError("whole curve identities must be nonmissing and nonempty")
        group = c.get("group")
        if group:
            require_table(frame, [group])
            if frame[group].isna().any() or frame.groupby(identity, sort=False)[group].nunique().ne(1).any():
                raise ValueError("whole curve identity must belong to exactly one nonmissing group")
        unit_column = c.get("unit_column")
        if unit_column:
            require_table(frame, [unit_column])
            if frame[unit_column].isna().any() or frame[unit_column].nunique() != 1:
                raise ValueError("spectral bands require consistent intensity units across complete curves")
            declared = c.get("units", {}).get(y)
            if declared is not None and _unit(declared) != _unit(frame[unit_column].iloc[0]):
                raise ValueError("intensity unit column conflicts with declared intensity unit")
            c = {**c, "units": {**c.get("units", {}), y: str(frame[unit_column].iloc[0])}}
        band = c.get("band", "iqr")
        if band not in {"iqr", "sd", "ci95"}:
            raise ValueError("band must be iqr, sd or ci95")
        policy = c.get("small_sample_policy", "descriptive")
        if band == "ci95":
            from .table_contract import read_contract

            if c.get("independence_confirmed") is not True:
                raise ValueError(
                    "ci95 requires independence_confirmed=True after validating one curve per "
                    "independent experimental unit; IQR/SD remain descriptive alternatives"
                )
            if type(policy) is not str or policy not in {"descriptive", "model_based"}:
                raise ValueError("small_sample_policy must be descriptive or model_based")
            contract = read_contract(frame)
            if contract is not None:
                if contract["granularity"] != "point":
                    raise ValueError("ci95 complete curves require a point-granularity input contract")
                if contract["experimental_design"]["kind"] == "paired":
                    raise ValueError(
                        "paired experimental-unit designs require a paired analysis; "
                        "independent-curve ci95 cannot override the declared design"
                    )
                unit = contract["roles"].get("experimental_unit")
                if unit is not None:
                    relationships = frame[[identity, unit]].drop_duplicates()
                    if relationships[identity].duplicated().any() or relationships[unit].duplicated().any():
                        raise ValueError(
                            "ci95 requires one complete curve per experimental unit; "
                            "aggregate repeated curves by the declared unit first, or use descriptive IQR/SD"
                        )
        bands = []
        interval_warnings = []
        for label, block in _grouped(frame, c):
            measured = [
                (curve, *_ordered_curve(b, x, y))
                for curve, b in block.groupby(identity, sort=False, observed=True)
            ]
            if len(measured) < 2:
                raise ValueError(
                    "spectral bands require at least two complete curves per group; ci95 unavailable at n=1"
                )
            if band == "ci95" and len(measured) < 3 and policy != "model_based":
                raise ValueError(
                    "ci95 default descriptive product policy requires at least three independent units; "
                    "select IQR/SD, or explicitly opt into model_based assumptions for n=2"
                )
            grids = [row[1] for row in measured]
            equal = all(len(g) == len(grids[0]) and np.array_equal(g, grids[0]) for g in grids[1:])
            explicit = c.get("grid")
            if explicit is not None:
                xx = np.asarray(explicit, dtype=float)
                if xx.ndim != 1 or len(xx) < 2 or not np.isfinite(xx).all() or np.any(np.diff(xx) <= 0):
                    raise ValueError("explicit spectral grid must be finite and strictly increasing")
                if xx.min() < max(g.min() for g in grids) or xx.max() > min(g.max() for g in grids):
                    raise ValueError(
                        "spectral grid must stay within every curve shared range; no extrapolation"
                    )
                matrix = np.stack([np.interp(xx, g, v) for _, g, v in measured])
            elif equal:
                xx = grids[0]
                matrix = np.stack([row[2] for row in measured])
            else:
                raise ValueError("unequal spectral grids require an explicit grid within the shared range")
            mean = matrix.mean(axis=0)
            interval_metadata = {}
            if band == "iqr":
                lower, upper = np.quantile(matrix, [0.25, 0.75], axis=0)
            else:
                deviation = matrix.std(axis=0, ddof=1)
                if band == "ci95":
                    deviation = deviation / np.sqrt(len(matrix)) * stats.t.ppf(0.975, len(matrix) - 1)
                lower, upper = mean - deviation, mean + deviation
                if band == "ci95":
                    zero_variance = np.ptp(matrix, axis=0) == 0
                    status = (
                        "zero_between_unit_variance"
                        if zero_variance.all()
                        else "partially_estimable"
                        if zero_variance.any()
                        else "estimated"
                    )
                    interval_metadata = {
                        "ci_status": status,
                        "ci_reason": "between-unit variance is zero at these coordinates; "
                        "no meaningful empirical precision estimate"
                        if zero_variance.any()
                        else "pointwise Student t interval under the declared independent normal model",
                        "zero_variance_coordinates": int(zero_variance.sum()),
                    }
                    if zero_variance.any():
                        interval_warnings.append(
                            f"{label}: zero between-unit variance at {zero_variance.sum()} coordinates; "
                            "confidence limits are unavailable there, not evidence of population precision."
                        )
                    lower = [
                        None if unavailable else float(value)
                        for value, unavailable in zip(lower, zero_variance, strict=True)
                    ]
                    upper = [
                        None if unavailable else float(value)
                        for value, unavailable in zip(upper, zero_variance, strict=True)
                    ]
            bands.append(
                {
                    "label": label,
                    "x": xx.tolist(),
                    "mean": mean.tolist(),
                    "lower": lower if isinstance(lower, list) else lower.tolist(),
                    "upper": upper if isinstance(upper, list) else upper.tolist(),
                    "n_curves": len(matrix),
                    "curve_ids": [str(row[0]) for row in measured],
                    "band": band,
                    "interpolated": explicit is not None,
                    **(
                        {
                            "n_independent_units": len(matrix),
                            "degrees_of_freedom": len(matrix) - 1,
                            **interval_metadata,
                            "ci_method": "pointwise_student_t",
                            "confidence_level": 0.95,
                            "small_sample_policy": policy,
                            "independence_confirmed": True,
                        }
                        if band == "ci95"
                        else {}
                    ),
                }
            )
        # Validate every group's design, sample count and coordinates before
        # allocating a figure. plot_operation closes owned figures on all paths.
        fig, ax = _figure(c)
        for item in bands:
            style = styled_series(item["label"], c)
            ax.plot(
                item["x"],
                item["mean"],
                label=f"{item['label']} (n={item['n_curves']} curves)",
                color=style["color"],
                linestyle=style["linestyle"],
            )
            ax.fill_between(
                item["x"],
                np.asarray(item["lower"], dtype=float),
                np.asarray(item["upper"], dtype=float),
                color=style["color"],
                alpha=0.22,
                linewidth=0,
            )
        definitions = {
            "iqr": "Mean curve with pointwise observed 25th-75th percentiles across complete curves.",
            "sd": "Mean plus/minus one pointwise sample standard deviation (ddof=1) across complete curves.",
            "ci95": "Pointwise 95% Student t interval for the mean across independent complete curves; "
            "not a simultaneous band.",
        }
        labels = {"x": _label(x, c), "y": c.get("y_label") or _label(y, c)}
        ax.set(xlabel=labels["x"], ylabel=labels["y"], title=str(c.get("title", "Spectral mean and band")))
        legend(ax)
        result = _finish(
            fig,
            c,
            "spectra-band",
            {
                "method": "band",
                "labels": labels,
                "plot_data": {"bands": bands},
                "statistical_definition": definitions[band],
                "assumptions": [
                    *(
                        [
                            "Independent experimental units explicitly confirmed by caller; "
                            "one complete curve per unit.",
                            "Pointwise iid normal-response model with estimated variance; "
                            "small sample size cannot verify normality.",
                        ]
                        if band == "ci95"
                        else [
                            "Complete curves are retained as observations; "
                            "curve count does not establish independence.",
                        ]
                    ),
                    "Interpolation is linear inside the shared measured range only.",
                ],
            },
        )
        result.warnings.extend(interval_warnings)
        return result
    x = c.get("x")
    columns = c.get("columns") or [c.get("y")]
    frame = require_table(table, [x, *columns], min_rows=2)
    numeric_matrix(frame, [x, *columns])
    # Strictly ascending spectra make differences and annotated peak locations
    # unambiguous; independent grids require explicit user resampling upstream.
    xv = frame[x].to_numpy(float)
    if np.any(np.diff(xv) <= 0):
        raise ValueError("spectra require strictly increasing, distinct x coordinates")
    fig, ax = _figure(c)
    curves = []
    if method == "difference":
        if len(columns) != 2:
            raise ValueError("difference requires exactly two intensity columns")
        curves = [
            {
                "label": f"{columns[0]} - {columns[1]}",
                "x": xv.tolist(),
                "y": (frame[columns[0]].to_numpy(float) - frame[columns[1]].to_numpy(float)).tolist(),
            }
        ]
    else:
        for i, col in enumerate(columns):
            offset = float(c.get("offset", 0)) * i if method == "overlay" else 0
            curves.append(
                {
                    "label": str(col),
                    "x": xv.tolist(),
                    "y": (frame[col].to_numpy(float) + offset).tolist(),
                    "display_offset": offset,
                }
            )
    for curve in curves:
        style = styled_series(curve["label"], c)
        ax.plot(
            curve["x"],
            curve["y"],
            label=curve["label"],
            color=style["color"],
            linestyle=style["linestyle"],
            marker=style["marker"],
            markevery=max(1, len(curve["x"]) // 14),
            markersize=3,
        )
    peaks = c.get("peaks", [])
    if peaks:
        ax.margins(y=0.18)
        if all(min(curve["y"]) >= 0 for curve in curves):
            ax.set_ylim(bottom=0)
    for peak in peaks:
        if not isinstance(peak, dict) or "x" not in peak or not np.isfinite(float(peak["x"])):
            raise ValueError("peaks must contain finite x and optional label")
        px = float(peak["x"])
        if not xv.min() <= px <= xv.max():
            raise ValueError("peak annotation lies outside the supplied spectrum")
        py = float(np.interp(px, curves[0]["x"], curves[0]["y"]))
        ax.annotate(
            str(peak.get("label", px)),
            (px, py),
            xytext=(0, 12),
            textcoords="offset points",
            ha="center",
            arrowprops={"arrowstyle": "-", "lw": 0.6},
        )
    labels = {"x": _label(x, c), "y": c.get("y_label", "Intensity")}
    ax.set(xlabel=labels["x"], ylabel=labels["y"], title=str(c.get("title", "Spectrum / diffraction")))
    legend(ax)
    return _finish(
        fig,
        c,
        f"spectra-{method}",
        {"method": method, "labels": labels, "plot_data": {"curves": curves, "peaks": peaks}},
    )


@plot_operation
def _mechanics_plot(table=None, *, config=None, data=None, tables=None):
    c = config or {}
    method = _method(c, {"overlay", "mean_error"}, "overlay")
    x, y, sample = c.get("x"), c.get("y"), c.get("sample")
    frame = require_table(table, [x, y, sample])
    numeric_matrix(frame, [x, y])
    if frame[sample].isna().any():
        raise ValueError("sample identities cannot be missing")
    if c.get("group") and frame.groupby(sample, observed=True)[c["group"]].nunique().gt(1).any():
        raise ValueError("each specimen must belong to one group")
    fig, ax = _figure(c)
    curves = []
    error_type = c.get("error", "std")
    if error_type not in {"std", "sem", "ci95"}:
        raise ValueError("error must be std, sem or ci95")
    from scipy import stats

    for label, block in _grouped(frame, c):
        specimen_curves = [
            (str(s), *_ordered_curve(b, x, y)) for s, b in block.groupby(sample, sort=False, observed=True)
        ]
        if method == "overlay":
            for specimen, xx, yy in specimen_curves:
                identity = label if c.get("group") else specimen
                style = styled_series(identity, c)
                ax.plot(
                    xx,
                    yy,
                    label=f"{label}: {specimen}" if c.get("group") else specimen,
                    alpha=0.8,
                    color=style["color"],
                    linestyle=style["linestyle"],
                )
                curves.append({"label": label, "sample": specimen, "x": xx.tolist(), "y": yy.tolist()})
        else:
            if len(specimen_curves) < 2:
                raise ValueError(
                    "mean error bands require at least two independent specimen curves per group"
                )
            grids = [item[1] for item in specimen_curves]
            equal_grids = not any(
                len(g) != len(grids[0]) or not np.allclose(g, grids[0], rtol=1e-10, atol=1e-12)
                for g in grids[1:]
            )
            grid = c.get("grid")
            if grid is not None:
                xx = np.asarray(grid, float)
                if xx.ndim != 1 or len(xx) < 2 or not np.isfinite(xx).all() or np.any(np.diff(xx) <= 0):
                    raise ValueError("interpolation grid must be finite and strictly increasing")
                if xx.min() < max(g.min() for g in grids) or xx.max() > min(g.max() for g in grids):
                    raise ValueError(
                        "interpolation grid must stay inside the shared specimen range; no extrapolation"
                    )
                matrix = np.stack([np.interp(xx, gx, gy) for _, gx, gy in specimen_curves])
            elif equal_grids:
                xx = grids[0]
                matrix = np.stack([item[2] for item in specimen_curves])
            else:
                raise ValueError(
                    "unequal strain grids require explicit interpolation grid within all specimens' range"
                )
            mean, error = matrix.mean(axis=0), matrix.std(axis=0, ddof=1)
            if error_type in {"sem", "ci95"}:
                error /= np.sqrt(len(matrix))
            if error_type == "ci95":
                error *= stats.t.ppf(0.975, len(matrix) - 1)
            style = styled_series(label, c)
            color = style["color"]
            ax.plot(
                xx,
                mean,
                label=f"{label} (n={len(matrix)} specimens)",
                color=color,
                linestyle=style["linestyle"],
                marker=style["marker"],
                markevery=max(1, len(xx) // 14),
                markersize=3,
            )
            ax.fill_between(xx, mean - error, mean + error, alpha=0.18, color=color)
            curves.append(
                {
                    "label": label,
                    "x": xx.tolist(),
                    "y": mean.tolist(),
                    "error": error.tolist(),
                    "n_specimens": len(matrix),
                    "sample_ids": [s[0] for s in specimen_curves],
                    "interpolation": "explicit_grid" if grid is not None else "none",
                }
            )
    labels = {"x": _label(x, c), "y": _label(y, c)}
    ax.set(xlabel=labels["x"], ylabel=labels["y"], title=str(c.get("title", "Stress–strain response")))
    legend(ax)
    return _finish(
        fig,
        c,
        f"mechanics-{method}",
        {
            "method": method,
            "labels": labels,
            "error_definition": error_type if method == "mean_error" else None,
            "statistical_definition": (
                {
                    "std": "Mean ± sample SD across specimen curves",
                    "sem": "Mean ± SEM across specimen curves",
                    "ci95": "Mean and pointwise 95% Student t CI across specimen curves",
                }[error_type]
                if method == "mean_error"
                else "Individual specimen curves"
            ),
            "plot_data": {"curves": curves},
        },
    )


def _mechanics_column_error(requested, columns):
    available = ", ".join(columns) if columns else "<empty>"
    details = ", ".join(f"{key}={value!r}" for key, value in requested.items() if value not in columns)
    hints = []
    if "strain_fraction" in columns and "stress_MPa" in columns:
        hints.append(
            "input looks like a mechanics result table: set x='strain_fraction', y='stress_MPa' (cfg_x/cfg_y)"
        )
    hints.append(
        "set x/y/sample (cfg_x/cfg_y/cfg_sample) to actual column names or connect the raw import table"
    )
    return ValueError(
        f"viz.mechanics column mismatch: {details} not found. Available columns: [{available}]. "
        + "; ".join(hints)
        + "。请填写实际列名；力学结果表请使用 strain_fraction/stress_MPa，"
        "或改为连接含 strain/stress/sample_id 的原始导入表。"
    )


def _mechanics_unit_error(unknown, columns):
    available = ", ".join(columns) if columns else "<empty>"
    if "strain_fraction" in columns and "stress_MPa" in columns:
        format_hint = '{"strain_fraction": "1", "stress_MPa": "MPa"}'
    else:
        format_hint = '{"<column>": "<unit>"}'
    return ValueError(
        "viz.mechanics unit declarations (cfg_units) must name existing columns; "
        f"unknown keys: {unknown}. Available columns: [{available}]. "
        'Expected mapping format {"<column>": "<unit>"}, e.g. ' + format_hint + ". "
        '列单位声明必须使用实际列名；请按 {"<列名>": "<单位>"} 填写，'
        "例如对力学结果表使用 strain_fraction/stress_MPa 的单位。"
    )


def _validate_mechanics_inputs(table, config):
    if not isinstance(table, pd.DataFrame):
        return
    columns = [str(column) for column in table.columns]
    c = dict(config or {})
    requested = {"x": c.get("x"), "y": c.get("y"), "sample": c.get("sample")}
    if c.get("group"):
        requested["group"] = c.get("group")
    if any(value not in columns for value in requested.values()):
        raise _mechanics_column_error(requested, columns)
    units = c.get("units")
    if units is None:
        return
    if not isinstance(units, dict):
        raise _mechanics_unit_error([], columns)
    unknown = [str(key) for key in units if key not in columns]
    if unknown:
        raise _mechanics_unit_error(unknown, columns)


def mechanics(table=None, *, config=None, data=None, tables=None):
    """Plot specimen curves after validating column/unit declarations with actionable failures."""
    _validate_mechanics_inputs(table, config)
    return _mechanics_plot(table, config=config, data=data, tables=tables)


@plot_operation
def statistics_plot(table=None, *, config=None, data=None, tables=None):
    c = config or {}
    method = _method(c, {"histogram", "correlation", "residual", "prediction"}, "histogram")
    frame = require_table(table)
    fig, ax = _figure(c)
    if method == "histogram":
        col = c.get("column")
        values = numeric_matrix(frame, [col])[:, 0]
        count, edges, _ = ax.hist(values, bins=c.get("bins", "auto"), color=_COLORS[0], edgecolor="white")
        if int(count.sum()) != len(values):
            raise ValueError(
                "histogram bins must cover all observations; filter the table upstream to restrict range"
            )
        payload = {"count": count.astype(int).tolist(), "edges": edges.tolist(), "values": values.tolist()}
        ax.set(xlabel=_label(col, c), ylabel="Count")
    elif method == "correlation":
        columns = c.get("columns")
        values = numeric_matrix(frame, columns)
        if len(frame) < 3 or np.any(np.ptp(values, axis=0) == 0):
            raise ValueError("correlation heatmap needs at least three observations and varying columns")
        corr_method = c.get("correlation_method", "pearson")
        if corr_method not in {"pearson", "spearman", "kendall"}:
            raise ValueError("correlation_method must be pearson, spearman, or kendall")
        matrix = pd.DataFrame(values, columns=columns).corr(method=corr_method).to_numpy()
        image = ax.imshow(matrix, vmin=-1, vmax=1, cmap="RdBu_r")
        fig.colorbar(
            image,
            ax=ax,
            label={"pearson": "Pearson r", "spearman": "Spearman ρ", "kendall": "Kendall τ"}[corr_method],
        )
        ax.set_xticks(range(len(columns)), columns, rotation=30)
        ax.set_yticks(range(len(columns)), columns)
        ax.grid(False)
        for i in range(len(columns)):
            for j in range(len(columns)):
                ax.text(
                    j,
                    i,
                    f"{matrix[i, j]:.2f}",
                    ha="center",
                    va="center",
                    color="white" if abs(matrix[i, j]) > 0.55 else "black",
                )
        payload = {"columns": columns, "matrix": matrix.tolist(), "method": corr_method}
    else:
        true_col, pred_col = c.get("y_true", "y_true"), c.get("y_pred", "y_pred")
        unit_true, unit_pred = c.get("units", {}).get(true_col), c.get("units", {}).get(pred_col)
        if (unit_true is None) != (unit_pred is None) or (
            unit_true is not None and unit_true != unit_pred and _unit(unit_true) != _unit(unit_pred)
        ):
            raise ValueError(
                "declare matching units for observed and predicted values; convert units upstream"
            )
        observed, predicted = numeric_matrix(frame, [true_col, pred_col]).T
        if method == "residual":
            residual = observed - predicted
            ax.scatter(predicted, residual, color=_COLORS[0], s=28)
            ax.axhline(0, color="#52606D", lw=1, linestyle="--")
            unit = c.get("units", {}).get(true_col)
            ax.set(
                xlabel="Predicted" + (f" ({unit})" if unit else ""),
                ylabel="Residual: observed − predicted" + (f" ({unit})" if unit else ""),
            )
            payload = {
                "y_true": observed.tolist(),
                "y_pred": predicted.tolist(),
                "residual": residual.tolist(),
            }
        else:
            ax.scatter(observed, predicted, color=_COLORS[0], s=28)
            low, high = min(observed.min(), predicted.min()), max(observed.max(), predicted.max())
            ax.plot([low, high], [low, high], "--", color="#52606D", lw=1, label="Identity")
            unit = c.get("units", {}).get(true_col)
            ax.set(
                xlabel="Observed" + (f" ({unit})" if unit else ""),
                ylabel="Predicted" + (f" ({unit})" if unit else ""),
            )
            ax.set_aspect("equal", adjustable="box")
            payload = {"y_true": observed.tolist(), "y_pred": predicted.tolist()}
    ax.set_title(str(c.get("title", method.replace("_", " ").title())))
    return _finish(fig, c, f"statistics-{method}", {"method": method, "plot_data": payload})


def export_table(table=None, *, config=None, data=None, tables=None):
    from .preprocessing import table_units

    c = config or {}
    frame = require_table(table, min_rows=0)
    format = c.get("format", "csv")
    if format not in {"csv", "excel", "xlsx"}:
        raise ValueError("table format must be csv or excel")
    ids = c.get("id_columns", [])
    if ids:
        require_table(frame, ids, min_rows=0)
    units = table_units(frame, data, c.get("units"))
    frame.attrs["units"] = units
    if format != "csv":
        for col in frame:
            if pd.api.types.is_numeric_dtype(frame[col].dtype) and not pd.api.types.is_bool_dtype(
                frame[col].dtype
            ):
                numbers = pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype=float)
                if np.isinf(numbers).any():
                    raise ValueError(
                        f"{col}: Excel cannot represent non-finite floats (inf/-inf) exactly; "
                        "use CSV or replace them before export"
                    )
            if any(isinstance(v, Integral) and abs(int(v)) >= 10**15 for v in frame[col]):
                raise ValueError(
                    f"{col}: Excel's 15-digit precision cannot guarantee exact integers; "
                    "use CSV or convert these values to text before export"
                )
    extension = "csv" if format == "csv" else "xlsx"
    filename = c.get("filename", f"results.{extension}")
    if Path(filename).suffix.lower() != f".{extension}":
        raise ValueError(f"filename must end in .{extension}")
    # Export never overwrites a possibly raw file, even if a caller passes the
    # generic artifact overwrite option.
    path = artifact_path({**c, "overwrite": False}, filename)
    text_columns = [
        col
        for col in frame.columns
        if col in ids
        or pd.api.types.is_string_dtype(frame[col])
        or pd.api.types.is_bool_dtype(frame[col])
        or frame[col].dtype == object
    ]
    csv_readback = {"dtype": {col: "str" for col in text_columns}, "keep_default_na": False}
    if format == "csv":
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        back = pd.read_csv(path, **csv_readback)
    else:
        from openpyxl import Workbook, load_workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Results"
        ws.append([str(col) for col in frame.columns])
        for row in frame.itertuples(index=False, name=None):
            ws.append([None if pd.isna(value) else value for value in row])
        meta_sheet = wb.create_sheet("Metadata")
        meta_sheet.append(["field", "unit", "is_sample_id"])
        for col in frame.columns:
            meta_sheet.append([str(col), str(units.get(col, "")), col in ids])
        # Headers, metadata, units and table bodies all contain caller text.
        # Preserve that text as actual Excel strings, never executable formulas.
        expected_text = []
        for sheet in wb:
            for row in sheet:
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
                        expected_text.append((sheet.title, cell.coordinate, cell.value))
        wb.save(path)
        read_wb = load_workbook(path, data_only=False, read_only=True)
        try:
            for sheet, coordinate, value in expected_text:
                restored = read_wb[sheet][coordinate]
                if value and (restored.value != value or restored.data_type != "s"):
                    raise ValueError(f"Excel readback changed text value/type at {sheet}!{coordinate}")
                if restored.data_type == "f":
                    raise ValueError(f"Excel readback introduced a formula at {sheet}!{coordinate}")
            raw_rows = list(read_wb["Results"].values)
            back = pd.DataFrame(raw_rows[1:], columns=raw_rows[0])
        finally:
            read_wb.close()
    if list(back.columns) != list(frame.columns) or len(back) != len(frame):
        raise ValueError("export readback changed the table shape or columns")
    for col in frame.columns:
        original = frame[col]
        if col in text_columns:

            def export_text(value):
                if pd.api.types.is_scalar(value) and pd.isna(value):
                    return ""
                return str(value)

            a = original.map(export_text).tolist()
            b = back[col].map(export_text).tolist()
            if a != b:
                raise ValueError(f"export readback changed text or identifiers in {col}")
        elif pd.api.types.is_integer_dtype(original.dtype):
            for before, after in zip(original, back[col], strict=True):
                if pd.isna(before):
                    equal = pd.isna(after) or after == ""
                else:
                    try:
                        equal = numeric(after) == int(before)
                    except (ValueError, ArithmeticError):
                        equal = False
                if not equal:
                    raise ValueError(f"export readback changed an integer in {col}")
        elif pd.api.types.is_numeric_dtype(original.dtype):
            np.testing.assert_allclose(
                pd.to_numeric(back[col].replace("", np.nan)).to_numpy(float),
                original.to_numpy(float),
                equal_nan=True,
            )
    metadata = {
        "columns": list(frame.columns),
        "units": units,
        "id_columns": ids,
        "dtypes": {str(k): str(v) for k, v in frame.dtypes.items()},
        "rows": len(frame),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "csv_readback": csv_readback,
    }
    meta_path = artifact_path({"output_dir": str(path.parent)}, f"{path.stem}.metadata.json")
    meta_path.write_text(json.dumps(_safe(metadata), ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(meta_path.read_text(encoding="utf-8"))
    return NodeResult(
        frame,
        {
            "format": format,
            "file_path": str(path),
            "metadata_path": str(meta_path),
            "verified": True,
            "units": units,
            "id_columns": ids,
        },
        [str(path), str(meta_path)],
        ["CSV identifier types and units require the accompanying metadata when reopening."]
        if format == "csv"
        else [],
    )


def export_report(table=None, *, config=None, data=None, tables=None):
    from .viz_report import build_report

    return build_report(table, config or {}, data or {})


_ENTRIES = [
    ("viz.performance", "性能对比图", "performance", {"method": "scatter", "x": "x", "y": "y"}),
    ("viz.spectra", "光谱或衍射图", "spectra", {"method": "overlay", "x": "x", "columns": ["intensity"]}),
    (
        "viz.mechanics",
        "应力—应变图",
        "mechanics",
        {"method": "overlay", "x": "strain", "y": "stress", "sample": "sample_id"},
    ),
    ("viz.statistics", "统计图表", "statistics_plot", {"method": "histogram", "column": "value"}),
    ("export.table", "结果表导出", "export_table", {"format": "csv"}),
    ("export.report", "分析报告生成", "export_report", {"format": "html"}),
]
CATALOG = [
    {
        "key": key,
        "title": title,
        "function": f"materials_quality.science.visualization:{name}",
        "category": "可视化与报告",
        "requirement": title,
        "table_input": True,
        "data_input": name in {"export_report", "export_table"},
        "tables_input": False,
        "default_config": default,
    }
    for key, title, name, default in _ENTRIES
]
