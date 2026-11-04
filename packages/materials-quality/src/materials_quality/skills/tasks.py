"""Three allowlisted pipelines reusing the project's scientific implementations."""

from copy import deepcopy
from dataclasses import dataclass, field

import pandas as pd

from materials_quality.science import materials, visualization
from materials_quality.science.contrast_study import contrast_study
from materials_quality.science.spectrum_batch import _identifiers, analyze_spectra

from .spectral_study import band_frame, study


@dataclass
class TaskOutput:
    table: pd.DataFrame
    features: pd.DataFrame
    curves: pd.DataFrame
    groups: pd.DataFrame
    data: dict
    warnings: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)


def _describe(frame, metrics, group="group"):
    rows = []
    grouped = (
        frame.groupby(group, dropna=False, sort=False, observed=True) if group in frame else [("all", frame)]
    )
    for label, block in grouped:
        for metric in metrics:
            values = (
                pd.to_numeric(block[metric], errors="coerce").dropna() if metric in block else pd.Series()
            )
            rows.append(
                {
                    "group": label,
                    "variable": metric,
                    "count": len(values),
                    "mean": float(values.mean()) if len(values) else None,
                    "std": float(values.std(ddof=1)) if len(values) > 1 else None,
                }
            )
    return pd.DataFrame(rows)


def _plot(result, call, frame, config):
    try:
        plotted = call(frame, config=config)
        result.artifacts.extend(plotted.artifacts)
        result.warnings.extend(plotted.warnings)
    except (ValueError, TypeError, ArithmeticError) as exc:
        result.warnings.append(f"图件未生成，数值结果保留：{exc}")


def spectral_task(table, p, output):
    c = {
        "curve_id": p["curve_id"],
        "x": p["x"],
        "y": p["y"],
        "group": p["group"],
        "x_unit": p["x_unit"],
        "intensity_unit": p["y_unit"],
        "lambda10_window_nm": p["peak_window"],
        "lambda10_selection": p["selection_rule"],
        "prominence_mode": p["prominence_mode"],
        "on_error": "continue",
        "baseline": {"method": p["baseline"], "value": p["baseline_value"]},
        "smooth_window": p["smooth_window"] if p["smooth"] else 0,
        "smooth_order": p["smooth_order"],
    }
    if "prominence" in p:
        c["prominence"] = p["prominence"]
    for key in ("noise_window", "noise_multiplier", "peak_distance_x"):
        if key in p:
            c[key] = p[key]
    source = table.copy(deep=True)
    source.attrs = deepcopy(table.attrs)
    # Planning has checked equivalence; harmonize synonyms only on the analysis copy.
    for column, unit in ((p["x"], p["x_unit"]), (p["y"], p["y_unit"])):
        source.attrs.setdefault("units", {})[column] = unit
    r = analyze_spectra(source, c)
    summary = pd.DataFrame(r.data["curve_summary"])
    summary.attrs["units"] = {"lambda10_nm": "nm", "window_candidate_nm": "nm", "peak_position": p["x_unit"]}
    groups, comparison = study(summary, source, p)
    if "experimental_unit" in summary:
        mapping = summary.set_index("curve_id")["experimental_unit"]
        r.features["experimental_unit"] = r.features.curve_id.map(mapping)
        if "curve_id" in r.table:
            r.table["experimental_unit"] = r.table.curve_id.map(mapping)
    r.data["group_inference"] = comparison
    result = TaskOutput(summary, r.features, r.table, groups, r.data, list(r.warnings))
    missing = sum(
        row.get("status") == "completed" and row.get("lambda10_nm") is None for row in r.data["curve_summary"]
    )
    if missing:
        result.warnings.append(f"{missing} 条曲线未检出窗口候选，保留缺失，不计入候选均值。")
    plot_c = {
        "method": "band",
        "x": "x",
        "y": "smoothed",
        "curve_id": "curve_id",
        "band": p["band"],
        "units": {"x": p["x_unit"], "smoothed": p["y_unit"]},
        "data_kind": p["data_kind"],
        "formats": ["png", "svg"],
        "output_dir": str(output),
    }
    if p["group"]:
        plot_c["group"] = "group"
    if len(r.table):
        plot_frame = r.table
        if p["band"] == "ci95":
            try:
                plot_frame = band_frame(r.table, source, p)
                plot_c.update(independence_confirmed=True, small_sample_policy=p["small_sample_policy"])
            except ValueError as exc:
                result.warnings.append(f"未生成置信带：{exc} 数值结果保留，可改用描述带。")
                result.data["confidence_band_status"] = "unavailable_unit_or_sample_conditions"
                plot_frame = None
        if plot_frame is not None:
            _plot(result, visualization.spectra, plot_frame, plot_c)
    return result


def mechanics_task(table, p, output):
    source = table.copy(deep=True)
    key = p["sample_id"]
    if key is None:
        key = "__studyui_sample__"
        while key in source:
            key += "_"
        source[key] = "single-sample"
    _identifiers(source[key], "sample_id")
    if p["single_sample"] and source[key].nunique() != 1:
        raise ValueError("单样品声明与输入中多个样品编号矛盾")
    group = p.get("group")
    if group:
        _identifiers(source[group], "group")
        if source.groupby(key, sort=False, observed=True)[group].nunique().gt(1).any():
            raise ValueError("每个样品必须仅属于一个组")
    rows, curves, warnings = [], [], []
    for identifier, block in source.groupby(key, sort=False, observed=True):
        row = {"sample_id": identifier, "group": block[group].iloc[0] if group else "all"}
        try:
            r = materials.mechanics(
                block,
                config={
                    "x": p["strain"],
                    "y": p["stress"],
                    "strain_unit": p["strain_unit"],
                    "stress_unit": p["stress_unit"],
                    "fit_range": p["fit_range"],
                    "yield_offset": p["yield_offset"],
                },
            )
            row.update(status="completed", error=None, **r.data)
            c = r.table.copy()
            c["sample_id"], c["group"] = identifier, row["group"]
            c.attrs = {}
            curves.append(c)
            warnings.extend(f"样品 {identifier}: {w}" for w in r.warnings)
        except (ValueError, TypeError, ArithmeticError) as exc:
            row.update(status="failed", error=str(exc))
        rows.append(row)
    summary = pd.DataFrame(rows)
    combined = pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()
    if len(combined):
        combined.attrs["units"] = {
            "strain_fraction": "1",
            "stress_MPa": "MPa",
            "elastic_fit_MPa": "MPa",
            "offset_line_MPa": "MPa",
        }
    summary.attrs["units"] = {
        k: "MPa" for k in ("elastic_modulus_MPa", "yield_stress_MPa", "ultimate_strength_MPa") if k in summary
    }
    groups = _describe(summary, ["elastic_modulus_MPa", "yield_stress_MPa", "ultimate_strength_MPa"])
    counts = {"total": len(rows), "completed": sum(r["status"] == "completed" for r in rows)}
    counts["failed"] = counts["total"] - counts["completed"]
    counts["skipped"] = 0
    status = "completed" if not counts["failed"] else ("partial_failed" if counts["completed"] else "failed")
    result = TaskOutput(
        summary,
        summary.copy(deep=True),
        combined,
        groups,
        {"counts": counts, "execution_status": status},
        warnings,
    )
    if len(combined):
        _plot(
            result,
            visualization.mechanics,
            combined,
            {
                "method": "overlay",
                "x": "strain_fraction",
                "y": "stress_MPa",
                "sample": "sample_id",
                "data_kind": p["data_kind"],
                "units": {"strain_fraction": "1", "stress_MPa": "MPa"},
                "formats": ["png", "svg"],
                "output_dir": str(output),
            },
        )
    return result


def contrast_task(table, p, output):
    c = {
        k: p[k]
        for k in (
            "group",
            "variable",
            "value",
            "sample_id",
            "experimental_unit",
            "design",
            "strategy",
            "correction",
            "alpha",
            "small_sample_policy",
        )
    }
    source = table.copy(deep=True)
    source[p["value"]] = pd.to_numeric(source[p["value"]], errors="raise")
    r = contrast_study(source, config=c)
    result = TaskOutput(
        r.table, r.features, pd.DataFrame(), pd.DataFrame(r.data["descriptives"]), r.data, list(r.warnings)
    )
    undefined = int(r.features["p_adjusted"].isna().sum())
    descriptive = int(r.features["status"].eq("descriptive_only_small_n").sum())
    result.data.update(
        execution_status="descriptive_only"
        if descriptive == len(r.features)
        else ("needs_review" if undefined else "completed"),
        counts={
            "total": len(r.features),
            "completed": len(r.features) - undefined,
            "failed": undefined - descriptive,
            "skipped": 0,
            "descriptive": descriptive,
        },
    )
    result.table.attrs["units"] = {p["value"]: p["value_unit"]}
    result.features.attrs["units"] = {
        key: p["value_unit"]
        for key in ("mean_difference", "mean_difference_ci_low", "mean_difference_ci_high")
        if key in result.features
    }
    result.groups.attrs["units"] = {
        key: p["value_unit"]
        for key in ("mean", "std", "median", "q25", "q75", "min", "max")
        if key in result.groups
    }
    for index, (_, block) in enumerate(r.table.groupby(p["variable"], sort=False, observed=True)):
        _plot(
            result,
            visualization.performance,
            block,
            {
                "method": "box",
                "y": p["value"],
                "group": p["group"],
                "units": {p["value"]: p["value_unit"]},
                "data_kind": p["data_kind"],
                "formats": ["png", "svg"],
                "output_dir": str(output / f"variable-{index + 1}"),
            },
        )
    return result


TASKS = {"spectra": spectral_task, "mechanics": mechanics_task, "contrast": contrast_task}
