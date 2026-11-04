"""Unit-aware two/multi-group studies with declared design and one correction family."""

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.oneway import anova_oneway

from materials_quality.units import _unit

from .contracts import NodeResult, numeric_matrix, require_table
from .table_contract import attach_contract, make_contract, read_contract, restore_contract_units


def _number(value):
    value = float(value)
    return value if np.isfinite(value) else None


def contrast_study(table=None, *, config=None, data=None, tables=None):
    c = dict(config or {})
    group, variable, value, unit, sample = (
        c.get(k, k) for k in ("group", "variable", "value", "experimental_unit", "sample_id")
    )
    if len({group, variable, value}) != 3 or {group, variable, value} & {unit, sample}:
        raise ValueError("measurement/group/variable roles must be distinct from entity identifiers")
    f = require_table(table, list(dict.fromkeys([group, variable, value, unit, sample])))
    contract = read_contract(table)
    if contract is not None:
        f = restore_contract_units(f, contract)
        if contract["granularity"] not in {"measurement", "curve", "sample", "experimental_unit"}:
            raise ValueError("数据契约粒度不支持组间推断；请先提取每曲线/样品特征或声明标量测量表。")
        declared = contract["roles"].get("experimental_unit")
        if declared is not None and declared != unit:
            raise ValueError("experimental_unit conflicts with the incoming table contract")
        declared_design = contract["experimental_design"]
        if declared_design["confirmed"] and declared_design["kind"] != c.get("design", "independent"):
            raise ValueError("design conflicts with the incoming table contract")
        intended = {
            "group": group,
            "variable": variable,
            "response": value,
            "value": value,
            "technical_replicate": sample,
        }
        for role, column in intended.items():
            if role in contract["roles"] and contract["roles"][role] != column:
                raise ValueError(f"{role} conflicts with the incoming table contract")
        if "technical_replicate" not in contract["roles"]:
            if "sample_id" in contract["roles"] and contract["roles"]["sample_id"] != sample:
                raise ValueError("sample_id conflicts with the incoming table contract")
    numeric_matrix(f, [value])
    declared_unit = c.get("value_unit")
    stored_unit = f.attrs.get("units", {}).get(value)
    if declared_unit is not None:
        if not isinstance(declared_unit, str) or not declared_unit.strip():
            raise ValueError("value_unit must be a nonempty unit declaration")
        if stored_unit is not None and _unit(stored_unit) != _unit(declared_unit):
            raise ValueError("value_unit conflicts with source units; convert values explicitly first")
    for name in (group, variable, unit, sample):
        if f[name].isna().any() or f[name].astype(str).str.strip().eq("").any():
            raise ValueError(f"{name} must have nonmissing nonempty identifiers")
    if f.duplicated([group, variable, unit, sample]).any():
        raise ValueError("duplicate sample identity within experimental unit and variable")
    design = c.get("design", "independent")
    strategy = c.get("strategy", "parametric")
    if design not in {"independent", "paired"} or strategy not in {"parametric", "nonparametric"}:
        raise ValueError("design must be independent/paired and strategy parametric/nonparametric")
    correction = c.get("correction", "holm")
    if correction not in {"holm", "fdr_bh"}:
        raise ValueError("correction must be holm or fdr_bh")
    alpha = float(c.get("alpha", 0.05))
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie between 0 and 1")
    small_sample_policy = c.get("small_sample_policy", "descriptive")
    if small_sample_policy not in {"descriptive", "model_based"}:
        raise ValueError("small_sample_policy must be descriptive/model_based")
    # Technical measurements contribute only their unit mean to inference.
    aggregated = (
        f.groupby([variable, group, unit], sort=False, observed=True)[value]
        .agg(["mean", "size"])
        .reset_index()
    )
    aggregated = aggregated.rename(columns={"mean": value, "size": "technical_replicates"})
    descriptives = []
    pairwise = []
    omnibus = []
    warnings = []
    for var, block in aggregated.groupby(variable, sort=False, observed=True):
        labels = list(pd.unique(block[group]))
        if len(labels) < 2:
            raise ValueError("each variable requires at least two groups")
        if design == "paired" and len(labels) != 2:
            raise ValueError("paired design currently supports exactly two groups")
        if design == "independent" and (block.groupby(unit, sort=False)[group].nunique() > 1).any():
            raise ValueError("independent design requires disjoint experimental units across groups")
        arrays = []
        for label in labels:
            v = block.loc[block[group] == label, value].to_numpy(dtype=float)
            arrays.append(v)
            descriptives.append(
                {
                    "variable": var,
                    "group": label,
                    "count": len(v),
                    "mean": float(v.mean()),
                    "std": float(v.std(ddof=1)) if len(v) > 1 else None,
                    "median": float(np.median(v)),
                    "q25": float(np.quantile(v, 0.25)),
                    "q75": float(np.quantile(v, 0.75)),
                    "min": float(v.min()),
                    "max": float(v.max()),
                }
            )
        if len(labels) > 2:
            if any(len(v) < (3 if small_sample_policy == "descriptive" else 2) for v in arrays):
                omnibus.append(
                    {
                        "variable": var,
                        "method": "descriptive_only",
                        "statistic": None,
                        "p_raw": None,
                        "status": "descriptive_only_small_n",
                    }
                )
            elif strategy == "parametric":
                if any(np.var(v, ddof=1) == 0 for v in arrays):
                    omnibus.append(
                        {
                            "variable": var,
                            "method": "welch_anova",
                            "statistic": None,
                            "p_raw": None,
                            "status": "undefined_zero_group_variance",
                        }
                    )
                else:
                    result = anova_oneway(arrays, use_var="unequal")
                    omnibus.append(
                        {
                            "variable": var,
                            "method": "welch_anova",
                            "statistic": _number(result.statistic),
                            "p_raw": _number(result.pvalue),
                            "df": list(map(float, result.df)),
                        }
                    )
            else:
                if np.ptp(np.concatenate(arrays)) == 0:
                    omnibus.append(
                        {
                            "variable": var,
                            "method": "kruskal",
                            "statistic": None,
                            "p_raw": None,
                            "status": "undefined_all_identical",
                        }
                    )
                else:
                    result = stats.kruskal(*arrays)
                    omnibus.append(
                        {
                            "variable": var,
                            "method": "kruskal",
                            "statistic": _number(result.statistic),
                            "p_raw": _number(result.pvalue),
                        }
                    )
        for i, j in combinations(range(len(labels)), 2):
            a, b = arrays[i], arrays[j]
            n_pairs = None
            if design == "paired":
                left = block.loc[block[group] == labels[i]].set_index(unit)[value]
                right = block.loc[block[group] == labels[j]].set_index(unit)[value]
                if set(left.index) != set(right.index):
                    raise ValueError("paired inference requires matching experimental units in both groups")
                a = left.to_numpy(dtype=float)
                b = right.reindex(left.index).to_numpy(dtype=float)
                n_pairs = len(a)
            low_n = min(len(a), len(b)) < 2 or (
                min(len(a), len(b)) < 3 and small_sample_policy == "descriptive"
            )
            if low_n:
                pairwise.append(
                    {
                        "variable": var,
                        "group_a": labels[i],
                        "group_b": labels[j],
                        "method": "descriptive_only",
                        "n_a": len(a),
                        "n_b": len(b),
                        "n_pairs": n_pairs,
                        "mean_difference": float(a.mean() - b.mean()),
                        "statistic": None,
                        "p_raw": None,
                        "p_adjusted": None,
                        "reject": None,
                        "effect_name": None,
                        "effect_size": None,
                        "direction": "group_a minus group_b; positive rank effect favors group_a",
                        "status": "descriptive_only_small_n",
                        "mean_difference_ci_low": None,
                        "mean_difference_ci_high": None,
                        "ci_method": None,
                        "ci_status": "not_estimated_small_n_policy",
                        "confidence_level": 1 - alpha,
                    }
                )
                continue
            if design == "paired":
                difference = a - b
                if strategy == "parametric":
                    test = stats.ttest_rel(a, b)
                    method = "paired_t"
                    effect_name = "cohens_dz"
                    sd = difference.std(ddof=1)
                    effect = float(difference.mean() / sd) if sd > 0 else None
                else:
                    method = "wilcoxon"
                    effect_name = "matched_rank_biserial"
                    if np.all(difference == 0):
                        test = None
                        effect = None
                    else:
                        test = stats.wilcoxon(a, b, zero_method="wilcox", alternative="two-sided")
                        nonzero = difference[difference != 0]
                        ranks = stats.rankdata(abs(nonzero))
                        effect = float(np.sum(ranks * np.sign(nonzero)) / ranks.sum())
            elif strategy == "parametric":
                method = "welch_t"
                test = stats.ttest_ind(a, b, equal_var=False)
                effect_name = "hedges_g"
                df = len(a) + len(b) - 2
                pooled = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / df)
                effect = (
                    float((1 - 3 / (4 * df - 1)) * (a.mean() - b.mean()) / pooled) if pooled > 0 else None
                )
            else:
                method = "mann_whitney"
                test = stats.mannwhitneyu(a, b, alternative="two-sided")
                effect_name = "rank_biserial"
                effect = float(2 * test.statistic / (len(a) * len(b)) - 1)
            statistic = _number(test.statistic) if test is not None else None
            p = _number(test.pvalue) if test is not None else None
            # Degenerate parametric tests lack a variance-supported reference distribution.
            degenerate = strategy == "parametric" and (
                (design == "paired" and np.var(a - b, ddof=1) == 0)
                or (design == "independent" and a.var(ddof=1) == 0 and b.var(ddof=1) == 0)
            )
            if degenerate:
                statistic = p = None
            status = "completed" if p is not None else "undefined_degenerate_variance_or_all_zero_differences"
            low, high, ci_method = None, None, None
            ci_status = "not_estimated_rank_strategy"
            if strategy == "parametric":
                ci_status = "not_estimated_degenerate" if degenerate else "estimated"
                if not degenerate and test is not None:
                    interval = test.confidence_interval(confidence_level=1 - alpha)
                    low, high = _number(interval.low), _number(interval.high)
                    ci_method = method
                    if low is None or high is None:
                        ci_status = "not_estimated_nonfinite"
                    elif min(len(a), len(b)) < 3:
                        ci_status = "estimated_small_n_model_assumptions"
            pairwise.append(
                {
                    "variable": var,
                    "group_a": labels[i],
                    "group_b": labels[j],
                    "method": method,
                    "n_a": len(a),
                    "n_b": len(b),
                    "n_pairs": n_pairs,
                    "mean_difference": float(a.mean() - b.mean()),
                    "statistic": statistic,
                    "p_raw": p,
                    "p_adjusted": None,
                    "reject": None,
                    "effect_name": effect_name,
                    "effect_size": effect,
                    "direction": "group_a minus group_b; positive rank effect favors group_a",
                    "status": status,
                    "mean_difference_ci_low": low,
                    "mean_difference_ci_high": high,
                    "ci_method": ci_method,
                    "ci_status": ci_status,
                    "confidence_level": 1 - alpha,
                }
            )
        if len(labels) == 2:
            pair = pairwise[-1]
            omnibus.append(
                {
                    "variable": var,
                    "method": pair["method"],
                    "statistic": pair["statistic"],
                    "p_raw": pair["p_raw"],
                    "status": pair["status"],
                }
            )
    valid = [i for i, row in enumerate(pairwise) if row["p_raw"] is not None]
    if valid:
        rejected, adjusted, _, _ = multipletests(
            [pairwise[i]["p_raw"] for i in valid], alpha=alpha, method=correction
        )
        for i, p, reject in zip(valid, adjusted, rejected, strict=True):
            pairwise[i]["p_adjusted"] = float(p)
            pairwise[i]["reject"] = bool(reject)
    if any(row["status"] != "completed" for row in pairwise):
        warnings.append(
            "Small-sample policy or degenerate contrasts can withhold inference; "
            "inspect each comparison status. Zero-variance effect sizes remain unavailable."
        )
    warnings.append(
        "Technical replicates were averaged within variable/group/experimental unit before all inference. "
        "Independence or pairing must reflect the experiment."
    )
    warnings.append(
        "Omnibus p-values are raw; adjusted pairwise p-values share one family across all supplied "
        "variables and group pairs. No automatic normality pretest is used."
    )
    result = NodeResult(
        table=aggregated,
        features=pd.DataFrame(pairwise),
        data={
            "descriptives": descriptives,
            "omnibus": omnibus,
            "pairwise": pairwise,
            "design": design,
            "strategy": strategy,
            "correction": correction,
            "correction_family": "all variable/group-pair contrasts",
            "alpha": alpha,
            "experimental_unit": unit,
            "aggregation": "arithmetic mean of technical replicates",
            "parameters": c,
            "small_sample_policy": small_sample_policy,
            "interval_scope": "individual unadjusted mean-difference intervals; not simultaneous intervals",
        },
        warnings=warnings,
    )
    known_unit = f.attrs.get("units", {}).get(value) or c.get("value_unit")
    result.table.attrs = {"units": {value: known_unit} if known_unit else {}}
    result.features.attrs = {
        "units": {
            key: known_unit
            for key in ("mean_difference", "mean_difference_ci_low", "mean_difference_ci_high")
        }
        if known_unit
        else {}
    }
    result.table = attach_contract(
        result.table,
        make_contract(
            result.table,
            granularity="experimental_unit",
            roles={"experimental_unit": unit, "group": group, "variable": variable, "response": value},
            experimental_design={
                "kind": design,
                "confirmed": bool(contract and contract["experimental_design"]["confirmed"]),
            },
            aggregation=[{"operation": "mean_technical_replicates", "parameters": {"unit": unit}}],
            derived_from=[{"operation": "contrast_study", "contract_sha256": contract["contract_sha256"]}]
            if contract
            else [],
        ),
    )
    result.features = attach_contract(
        result.features,
        make_contract(
            result.features,
            granularity="group_summary",
            roles={"variable": "variable", "response": "mean_difference"},
            aggregation=[{"operation": "declared_group_contrasts", "parameters": {"design": design}}],
        ),
    )
    return result
