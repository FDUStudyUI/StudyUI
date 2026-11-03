"""Descriptive detection denominators and explicitly declared sample-level contrasts."""

import pandas as pd

from materials_quality.science.contrast_study import contrast_study
from materials_quality.science.table_contract import attach_contract, make_contract, read_contract


def study(summary, source, p):
    if "window_candidate_nm" not in summary:
        summary["window_candidate_nm"] = float("nan")
    if "ambiguous" not in summary:
        summary["ambiguous"] = False
    group_rows = []
    for label, block in summary.groupby("group", dropna=False, sort=False, observed=True):
        eligible = block.status.eq("completed")
        detected = eligible & pd.to_numeric(block.window_candidate_nm, errors="coerce").notna()
        values = block.loc[detected, "window_candidate_nm"]
        group_rows.append(
            {
                "group": label,
                "variable": "window_candidate_nm",
                "count": len(values),
                "mean": float(values.mean()) if len(values) else None,
                "std": float(values.std(ddof=1)) if len(values) > 1 else None,
                "n_total": len(block),
                "n_eligible": int(eligible.sum()),
                "n_detected": int(detected.sum()),
                "n_ambiguous": int((detected & block.ambiguous.fillna(False)).sum()),
                "n_failed": int(block.status.eq("failed").sum()),
                "n_skipped": int(block.status.eq("skipped").sum()),
                "observed_detection_fraction": float(detected.sum() / eligible.sum())
                if eligible.any()
                else None,
                "mean_scope": "conditional on eligible curves with a window candidate",
            }
        )
    groups = pd.DataFrame(group_rows)
    groups.attrs["units"] = {"mean": "nm", "std": "nm"}
    known = read_contract(source)
    unit_column = p["curve_id"] if p["unit_mode"] == "curve" else p.get("experimental_unit")
    if unit_column is None and known:
        unit_column = known["roles"].get("experimental_unit")
    if unit_column is None:
        return groups, {"status": "descriptive_only_no_independence_declaration", "pairwise": [], "units": []}
    mapping = {}
    for curve_id, frame in source.groupby(p["curve_id"], sort=False, observed=True):
        values = frame[unit_column].drop_duplicates()
        if len(values) != 1 or values.isna().any():
            raise ValueError("每条曲线必须属于一个明确的独立试验单位。")
        mapping[curve_id] = values.iloc[0]
    summary["experimental_unit"] = summary.curve_id.map(mapping)
    if p["unit_mode"] == "descriptive":
        return groups, {
            "status": "descriptive_only_no_independence_declaration",
            "pairwise": [],
            "units": [],
            "n_known_units": int(summary.experimental_unit.nunique()),
        }
    valid = summary.loc[summary.status.eq("completed") & summary.window_candidate_nm.notna()].copy()
    if valid.empty:
        return groups, {"status": "descriptive_only_no_candidates", "pairwise": [], "units": []}
    if (
        valid.groupby("experimental_unit", sort=False, observed=True)["group"]
        .nunique(dropna=False)
        .gt(1)
        .any()
    ):
        raise ValueError("独立试验单位不能跨越多个组别；配对数据请使用组间研究任务。")
    if valid["group"].isna().any() or valid["group"].nunique() < 2:
        return groups, {"status": "descriptive_only_fewer_than_two_groups", "pairwise": [], "units": []}
    inference = valid[["curve_id", "group", "experimental_unit", "window_candidate_nm"]].rename(
        columns={"curve_id": "sample_id", "window_candidate_nm": "value"}
    )
    inference["variable"] = "window_candidate_nm"
    comparison = contrast_study(inference, config={"small_sample_policy": p["small_sample_policy"]})
    info = comparison.data
    info["units"] = comparison.table.to_dict("records")
    info["status"] = (
        "estimated"
        if all(r["p_raw"] is not None for r in info["pairwise"])
        else "needs_review_or_descriptive"
    )
    info["mean_scope"] = "unit means conditional on detected candidates; missing candidates remain missing"
    info["declared_unit_mode"] = p["unit_mode"]
    info["n_all_declared_units"] = int(summary.experimental_unit.nunique())
    info["n_units_with_candidates"] = int(valid.experimental_unit.nunique())
    for item in info["descriptives"]:
        mask = groups.group.eq(item["group"])
        groups.loc[mask, "unit_count"] = item["count"]
        groups.loc[mask, "unit_mean"] = item["mean"]
        groups.loc[mask, "unit_std"] = item["std"]
    groups.attrs["units"].update(unit_mean="nm", unit_std="nm")
    return groups, info


def band_frame(curves, source, p):
    """Build one whole mean curve per declared independent sample for t bands."""
    if p["unit_mode"] == "descriptive" or p["unit_confirmed"] is not True:
        raise ValueError("置信带需要明确的独立试验单位。")
    unit_column = p["curve_id"] if p["unit_mode"] == "curve" else p["experimental_unit"]
    identities = (
        source[[p["curve_id"], unit_column]].loc[:, lambda f: ~f.columns.duplicated()].drop_duplicates()
    )
    if p["unit_mode"] == "curve":
        mapping = {value: value for value in identities[p["curve_id"]]}
    else:
        if identities[p["curve_id"]].duplicated().any():
            raise ValueError("一条曲线不能属于多个独立单位。")
        mapping = identities.set_index(p["curve_id"])[unit_column].to_dict()
    frame = curves.copy(deep=True)
    reference = None
    for _, block in frame.groupby("curve_id", sort=False, observed=True):
        grid = block.x.tolist()
        if reference is not None and grid != reference:
            raise ValueError("样品均值置信带要求一致的测量网格；请先显式对齐共同区间。")
        reference = grid
    frame["analysis_unit"] = frame.curve_id.map(mapping)
    keys = ["analysis_unit", "x"] + (["group"] if p.get("group") else [])
    frame = frame.groupby(keys, observed=True, sort=False)["smoothed"].mean().reset_index()
    frame = frame.rename(columns={"analysis_unit": "curve_id"})
    sizes = (
        frame.groupby("group", observed=True).curve_id.nunique()
        if p.get("group")
        else pd.Series([frame.curve_id.nunique()])
    )
    minimum = 2 if p["small_sample_policy"] == "model_based" else 3
    if sizes.min() < minimum:
        raise ValueError(f"所选小样本政策要求每组至少 {minimum} 个完整独立单位，当前仅作描述。")
    roles = {"curve_id": "curve_id", "experimental_unit": "curve_id", "x": "x", "response": "smoothed"}
    if p.get("group"):
        roles["group"] = "group"
    contract = make_contract(
        frame,
        granularity="point",
        roles=roles,
        experimental_design={"kind": "independent", "confirmed": True},
        aggregation=[{"operation": "within_unit_mean_curve", "parameters": {}}],
    )
    return attach_contract(frame, contract)
