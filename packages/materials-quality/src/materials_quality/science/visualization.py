"""Numerical figures and verified table/report exports; raw inputs stay intact."""

import hashlib
import json
from numbers import Integral
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from PIL import Image

from materials_quality.common import numeric

from .contracts import NodeResult, artifact_path, numeric_matrix, require_table

_COLORS = ["#236B8E", "#C8543D", "#548B55", "#8064A2", "#BD8B26", "#398D96"]


def _figure(c):
    width, height = c.get("figsize", [7, 4.6])
    if not 2 <= float(width) <= 30 or not 2 <= float(height) <= 30:
        raise ValueError("figure size must be between 2 and 30 inches per dimension")
    fig, ax = plt.subplots(figsize=(width, height), layout="constrained")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.16)
    return fig, ax


def _safe(value):
    def fallback(x):
        if isinstance(x, np.ndarray):
            return x.tolist()
        if isinstance(x, np.generic):
            return x.item()
        return str(x)

    return json.loads(json.dumps(value, default=fallback, allow_nan=False))


def _finish(fig, c, name, payload):
    formats = c.get("formats", ["png"])
    if not isinstance(formats, list) or not formats or set(formats) - {"png", "svg", "pdf"}:
        plt.close(fig)
        raise ValueError("formats must be a nonempty list of png/svg/pdf")
    # Always retain a raster preview to inspect exports consistently.
    formats = ["png"] + [f for f in formats if f != "png"]
    paths, verified = [], []
    directory = c.get("output_dir")
    try:
        for fmt in formats:
            path = artifact_path({**c, **({"output_dir": directory} if directory else {})}, f"{name}.{fmt}")
            directory = str(path.parent)
            fig.savefig(path, dpi=int(c.get("dpi", 150)), format=fmt, facecolor="white")
            if fmt == "png":
                with Image.open(path) as image:
                    image.load()
                    arr = np.asarray(image.convert("RGB"))
                    if min(image.size) < 100 or float(arr.std()) < 1:
                        raise ValueError("exported figure is empty or unreadable")
                    verified.append(
                        {
                            "path": str(path),
                            "size": list(image.size),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                    )
            elif fmt == "svg":
                import xml.etree.ElementTree as ET

                if not ET.parse(path).getroot().tag.endswith("svg"):
                    raise ValueError("invalid SVG export")
            elif not path.read_bytes().startswith(b"%PDF"):
                raise ValueError("invalid PDF export")
            paths.append(str(path))
    finally:
        plt.close(fig)
    payload = _safe({**payload, "figure_verification": verified})
    return NodeResult(data=payload, artifacts=paths)


def _method(c, methods, default):
    method = c.get("method", default)
    if method not in methods:
        raise ValueError(f"method must be one of {sorted(methods)}")
    return method


def _label(column, c):
    unit = c.get("units", {}).get(column)
    return f"{column} ({unit})" if unit else str(column)


def _grouped(frame, c):
    group = c.get("group")
    if group:
        require_table(frame, [group])
        if frame[group].isna().any():
            raise ValueError("group labels cannot be missing")
        return [(str(label), block) for label, block in frame.groupby(group, sort=False, observed=True)]
    return [("all", frame)]


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
        values = block[y].to_numpy(float)
        record = {"label": label, "n": len(block), "y": values.tolist(), "mean": float(values.mean())}
        if method == "scatter":
            xx = block[x].to_numpy(float)
            ax.scatter(xx, values, s=30, alpha=0.8, label=label, color=_COLORS[i % len(_COLORS)])
            record["x"] = xx.tolist()
        elif method == "bar":
            # Error bars express observed sample spread, never significance.
            error = float(values.std(ddof=1)) if len(values) > 1 else 0.0
            ax.bar(i, values.mean(), yerr=error, capsize=4, color=_COLORS[i % len(_COLORS)], alpha=0.85)
            record["error"] = error
        group_data.append(record)
    if method == "box":
        ax.boxplot(
            [b[y].to_numpy(float) for _, b in blocks],
            tick_labels=[label for label, _ in blocks],
            patch_artist=True,
            boxprops={"facecolor": "#C7DEE9"},
        )
    elif method == "violin":
        parts = ax.violinplot([b[y].to_numpy(float) for _, b in blocks], showmeans=True, showextrema=True)
        for body in parts["bodies"]:
            body.set_facecolor(_COLORS[0])
        ax.set_xticks(np.arange(1, len(blocks) + 1), [label for label, _ in blocks])
    elif method == "bar":
        ax.set_xticks(np.arange(len(blocks)), [label for label, _ in blocks])
    if c.get("group") and method == "scatter":
        ax.legend(frameon=False)
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
        },
    )
    if method == "bar" and any(len(b) == 1 for _, b in blocks):
        result.warnings.append("Singleton groups have no estimated uncertainty; displayed error is zero.")
    return result


def _ordered_curve(block, x, y):
    matrix = numeric_matrix(block, [x, y])
    if len(matrix) < 2 or np.any(np.diff(matrix[:, 0]) <= 0):
        raise ValueError(
            "curves require strictly increasing acquisition coordinates; "
            "select a monotonic loading segment explicitly instead of sorting loading/unloading points"
        )
    return matrix[:, 0], matrix[:, 1]


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
    for i, curve in enumerate(curves):
        ax.plot(curve["x"], curve["y"], label=curve["label"], color=_COLORS[i % len(_COLORS)])
    peaks = c.get("peaks", [])
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
    ax.legend(frameon=False)
    return _finish(
        fig,
        c,
        f"spectra-{method}",
        {"method": method, "labels": labels, "plot_data": {"curves": curves, "peaks": peaks}},
    )


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

    for gi, (label, block) in enumerate(_grouped(frame, c)):
        specimen_curves = [
            (str(s), *_ordered_curve(b, x, y)) for s, b in block.groupby(sample, sort=False, observed=True)
        ]
        if method == "overlay":
            for specimen, xx, yy in specimen_curves:
                ax.plot(xx, yy, label=f"{label}: {specimen}", alpha=0.8, color=_COLORS[gi % len(_COLORS)])
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
            color = _COLORS[gi % len(_COLORS)]
            ax.plot(xx, mean, label=label, color=color)
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
    ax.legend(frameon=False)
    return _finish(
        fig,
        c,
        f"mechanics-{method}",
        {
            "method": method,
            "labels": labels,
            "error_definition": error_type if method == "mean_error" else None,
            "plot_data": {"curves": curves},
        },
    )


def statistics_plot(table=None, *, config=None, data=None, tables=None):
    c = config or {}
    method = _method(c, {"histogram", "correlation", "residual", "prediction"}, "histogram")
    frame = require_table(table)
    fig, ax = _figure(c)
    if method == "histogram":
        col = c.get("column")
        values = numeric_matrix(frame, [col])[:, 0]
        count, edges, _ = ax.hist(values, bins=c.get("bins", "auto"), color=_COLORS[0], edgecolor="white")
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
        fig.colorbar(image, ax=ax, label=f"{corr_method} correlation")
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
        observed, predicted = numeric_matrix(frame, [true_col, pred_col]).T
        if method == "residual":
            residual = observed - predicted
            ax.scatter(predicted, residual, color=_COLORS[0], s=28)
            ax.axhline(0, color=_COLORS[1], lw=1)
            ax.set(xlabel="Predicted", ylabel="Residual (observed − predicted)")
            payload = {
                "y_true": observed.tolist(),
                "y_pred": predicted.tolist(),
                "residual": residual.tolist(),
            }
        else:
            ax.scatter(observed, predicted, color=_COLORS[0], s=28)
            low, high = min(observed.min(), predicted.min()), max(observed.max(), predicted.max())
            ax.plot([low, high], [low, high], "--", color=_COLORS[1], lw=1)
            ax.set(xlabel="Observed", ylabel="Predicted")
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
