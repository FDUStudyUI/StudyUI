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
    c = config or {}
    method = _method(c, {"line", "overlay", "difference"}, "overlay")
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
def mechanics(table=None, *, config=None, data=None, tables=None):
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
        if col in ids or pd.api.types.is_string_dtype(frame[col]) or frame[col].dtype == object
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
            a = original.map(lambda v: "" if pd.isna(v) else str(v)).tolist()
            b = back[col].map(lambda v: "" if pd.isna(v) else str(v)).tolist()
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
