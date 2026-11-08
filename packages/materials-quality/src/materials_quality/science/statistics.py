"""Design-aware statistics and leakage-free predictive models.

No estimator is returned in Data. Fitted pipelines use skops with a narrowly
enumerated trusted-type list, checksummed JSON manifests and verified reloads.
"""

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .contracts import NodeResult, numeric_matrix, require_table
from .plot_style import plot_operation


def _method(config, allowed, default):
    method = config.get("method", default)
    if method not in allowed:
        raise ValueError(f"method must be one of {sorted(allowed)}")
    return method


def _finite(value):
    value = float(value)
    return value if np.isfinite(value) else None


def _finite_tree(value):
    """Keep result payloads strictly JSON-serializable: non-finite numbers become null."""
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, list):
        return [_finite_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: _finite_tree(item) for key, item in value.items()}
    return value


def _alpha(c):
    alpha = float(c.get("alpha", 0.05))
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    return alpha


def _groups(table, c, minimum=2):
    group, column = c.get("group"), c.get("column")
    frame = require_table(table, [group, column])
    if c.get("pair_id") and c.get("method") != "paired_t":
        raise ValueError(
            "pair_id declares paired observations; select paired_t or remove the pairing declaration"
        )
    numeric_matrix(frame, [column])
    if frame[group].isna().any():
        raise ValueError("group labels cannot be missing")
    selected = c.get("groups")
    labels = list(pd.unique(frame[group])) if selected is None else list(selected)
    if len(labels) < 2 or len(set(labels)) != len(labels):
        raise ValueError("at least two distinct groups required")
    values = [frame.loc[frame[group] == label, column].to_numpy(dtype=float) for label in labels]
    if any(len(v) < minimum for v in values):
        raise ValueError(f"each group needs at least {minimum} observations")
    subject = c.get("subject")
    if subject and c.get("method") != "paired_t":
        require_table(frame, [subject])
        if frame[subject].isna().any() or frame[subject].duplicated().any():
            raise ValueError(
                "independent tests require unique experimental-unit subject IDs; aggregate replicates"
            )
    return frame, labels, values


def grouped(table=None, *, config=None, data=None, tables=None):
    from .grouped_stats import grouped_summary
    from .preprocessing import table_units

    frame = require_table(table)
    frame.attrs["units"] = table_units(frame, data)
    return grouped_summary(frame, config)


@plot_operation
def distribution(table=None, *, config=None, data=None, tables=None):
    c = config or {}
    column = c.get("column")
    frame = require_table(table, [column], min_rows=3)
    v = numeric_matrix(frame, [column])[:, 0]
    if np.ptp(v) == 0:
        raise ValueError("normality check requires nonconstant observations")
    bins = c.get("bins", "auto")
    counts, edges = np.histogram(v, bins=bins)
    if int(counts.sum()) != len(v):
        raise ValueError(
            "histogram bins must cover all observations; filter the table upstream to restrict range"
        )
    (theoretical, ordered), (slope, intercept, r) = stats.probplot(v, dist="norm")
    shapiro = stats.shapiro(v)
    from .visualization import _figure, _finish

    fig, ax = _figure(c)
    ax.hist(v, bins=edges, color="#236B8E", edgecolor="white")
    from .visualization import _label

    ax.set(xlabel=_label(column, c), ylabel="Count", title="Distribution")
    histogram = _finish(
        fig,
        c,
        "distribution-histogram",
        {
            "method": "histogram",
            "plot_data": {"values": v.tolist(), "count": counts.tolist(), "edges": edges.tolist()},
            "observations_displayed": len(v),
            "statistical_definition": "Counts of all supplied observations",
        },
    )
    fig, ax = _figure(c)
    ax.scatter(theoretical, ordered, s=24)
    ax.plot(theoretical, slope * theoretical + intercept, color="#C8543D")
    ax.set(xlabel="Theoretical normal quantile", ylabel=_label(column, c), title="Normal Q-Q plot")
    qq = _finish(
        fig,
        c,
        "distribution-qq",
        {
            "method": "normal_qq",
            "plot_data": {"theoretical": theoretical.tolist(), "ordered": ordered.tolist()},
            "observations_displayed": len(v),
            "statistical_definition": "Normal quantiles; fitted reference line",
        },
    )
    warnings = ["Shapiro p-values may be inaccurate for n > 5000."] if len(v) > 5000 else []
    return NodeResult(
        data={
            "method": "histogram_qq_shapiro",
            "figure_previews": histogram.data["figure_previews"] + qq.data["figure_previews"],
            "figures": [histogram.data, qq.data],
            "n": len(v),
            "histogram": {"count": counts.tolist(), "edges": edges.tolist()},
            "qq": {
                "theoretical": theoretical.tolist(),
                "ordered": ordered.tolist(),
                "slope": float(slope),
                "intercept": float(intercept),
                "r": float(r),
            },
            "shapiro": {"statistic": float(shapiro.statistic), "pvalue": float(shapiro.pvalue)},
            "assumptions": ["Independent observations; normality is a model check, not proof."],
        },
        artifacts=histogram.artifacts + qq.artifacts,
        warnings=warnings + histogram.warnings + qq.warnings,
    )


def correlation(table=None, *, config=None, data=None, tables=None):
    c = config or {}
    method = _method(c, {"pearson", "spearman", "kendall"}, "pearson")
    columns = c.get("columns") or [c.get("x"), c.get("y")]
    if len(columns) < 2:
        raise ValueError("provide at least two columns")
    frame = require_table(table, columns, min_rows=3)
    matrix = numeric_matrix(frame, columns)
    if np.any(np.ptp(matrix, axis=0) == 0):
        raise ValueError("correlation is undefined for a constant column")
    func = {"pearson": stats.pearsonr, "spearman": stats.spearmanr, "kendall": stats.kendalltau}[method]
    rows = []
    for i, j in combinations(range(len(columns)), 2):
        test = func(matrix[:, i], matrix[:, j])
        row = {
            "variable1": columns[i],
            "variable2": columns[j],
            "n": len(frame),
            "coefficient": float(test.statistic),
            "pvalue": float(test.pvalue),
        }
        if method == "pearson":
            ci = test.confidence_interval(confidence_level=1 - _alpha(c))
            row.update(ci_low=_finite(ci.low), ci_high=_finite(ci.high))
        rows.append(row)
    return NodeResult(
        pd.DataFrame(rows),
        {
            "method": method,
            "assumptions": [
                "Independent paired observations; Pearson inference assumes bivariate normality."
            ],
        },
        warnings=["Pairwise p-values are unadjusted; use stats.multiple when testing a family."],
    )


def significance(table=None, *, config=None, data=None, tables=None):
    c = config or {}
    method = _method(c, {"independent_t", "paired_t", "welch", "mannwhitney", "anova", "kruskal"}, "welch")
    alpha = _alpha(c)
    frame, labels, values = _groups(table, c)
    if method not in {"anova", "kruskal"} and len(values) != 2:
        raise ValueError("this method requires exactly two groups")
    assumptions = [
        "Observations represent independent experimental units; technical replicates must be aggregated."
    ]
    warnings = []
    out = {
        "method": method,
        "groups": [str(x) for x in labels],
        "n": [len(v) for v in values],
        "alpha": alpha,
        "assumptions": assumptions,
    }
    if method == "paired_t":
        pair = c.get("pair_id")
        if not pair:
            raise ValueError("paired_t requires explicit pair_id")
        require_table(frame, [pair])
        selected = frame[frame[c["group"]].isin(labels)]
        if selected[pair].isna().any() or selected.duplicated([pair, c["group"]]).any():
            raise ValueError("missing pair IDs or duplicate pair/group replicates")
        pivot = selected.pivot(index=pair, columns=c["group"], values=c["column"])
        complete = pivot[labels].dropna()
        if len(complete) != len(pivot) and c.get("incomplete_pairs", "error") != "drop":
            raise ValueError(
                "complete pairs required; set incomplete_pairs='drop' explicitly to discard missing pairs"
            )
        if len(complete) < 2:
            raise ValueError("at least two complete pairs required")
        a, b = complete[labels[0]].to_numpy(float), complete[labels[1]].to_numpy(float)
        d = a - b
        if np.std(d, ddof=1) == 0:
            raise ValueError("paired differences must have nonzero variance")
        result = stats.ttest_rel(a, b)
        se = stats.sem(d)
        margin = stats.t.ppf(1 - alpha / 2, len(d) - 1) * se
        out.update(
            n_pairs=len(d),
            pair_ids=[str(x) for x in complete.index],
            dropped_pairs=len(pivot) - len(complete),
            mean_difference=float(d.mean()),
            confidence_interval=[float(d.mean() - margin), float(d.mean() + margin)],
            effect={"name": "absolute_cohen_dz", "value": float(abs(d.mean() / d.std(ddof=1)))},
        )
        assumptions[:] = [
            "Within-pair differences approximately normal; pairs independent; paired by explicit IDs."
        ]
    elif method in {"independent_t", "welch"}:
        a, b = values
        s1, s2 = a.var(ddof=1), b.var(ddof=1)
        if s1 + s2 == 0:
            raise ValueError("test requires nonzero within-group variance")
        equal = method == "independent_t"
        result = stats.ttest_ind(a, b, equal_var=equal)
        pooled = ((len(a) - 1) * s1 + (len(b) - 1) * s2) / (len(a) + len(b) - 2)
        if equal:
            se, df = np.sqrt(pooled * (1 / len(a) + 1 / len(b))), len(a) + len(b) - 2
            assumptions.append("Groups normally distributed with equal population variances.")
        else:
            se = np.sqrt(s1 / len(a) + s2 / len(b))
            df = (s1 / len(a) + s2 / len(b)) ** 2 / (
                (s1 / len(a)) ** 2 / (len(a) - 1) + (s2 / len(b)) ** 2 / (len(b) - 1)
            )
            assumptions.append("Groups approximately normal; variances may differ.")
        difference = float(a.mean() - b.mean())
        margin = float(stats.t.ppf(1 - alpha / 2, df) * se)
        out.update(
            mean_difference=difference,
            df=float(df),
            confidence_interval=[difference - margin, difference + margin],
            effect={"name": "absolute_cohen_d", "value": float(abs(difference / np.sqrt(pooled)))},
        )
    elif method == "mannwhitney":
        a, b = values
        result = stats.mannwhitneyu(a, b, alternative="two-sided", method="auto")
        out["effect"] = {
            "name": "absolute_rank_biserial",
            "value": float(abs(2 * result.statistic / (len(a) * len(b)) - 1)),
        }
        assumptions.append(
            "Ordinal or continuous outcomes; location interpretation requires similarly shaped distributions."
        )
    elif method == "anova":
        total = np.concatenate(values)
        within = sum(float(np.sum((v - v.mean()) ** 2)) for v in values)
        if within == 0:
            raise ValueError("ANOVA requires nonzero within-group variance")
        between = sum(len(v) * float((v.mean() - total.mean()) ** 2) for v in values)
        result = stats.f_oneway(*values)
        out["effect"] = {"name": "eta_squared", "value": float(between / (between + within))}
        assumptions.append("Normal group residuals and equal group variances; independent groups.")
    else:
        if np.ptp(np.concatenate(values)) == 0:
            raise ValueError("Kruskal requires nonidentical observations")
        result = stats.kruskal(*values)
        n, k = sum(map(len, values)), len(values)
        out["effect"] = {
            "name": "epsilon_squared",
            "value": float(max(0, (result.statistic - k + 1) / (n - k))),
        }
        assumptions.append(
            "Independent ordinal outcomes; location interpretation requires similarly shaped distributions."
        )
    if not np.isfinite(result.statistic) or not np.isfinite(result.pvalue):
        raise ValueError("degenerate data produced undefined test; inspect within-group variance")
    out.update(
        statistic=float(result.statistic), pvalue=float(result.pvalue), reject=bool(result.pvalue < alpha)
    )
    out = _finite_tree(out)
    return NodeResult(
        pd.DataFrame(
            [
                {
                    "method": method,
                    "statistic": out["statistic"],
                    "pvalue": out["pvalue"],
                    "reject": out["reject"],
                }
            ]
        ),
        out,
        warnings=warnings,
    )


def multiple(table=None, *, config=None, data=None, tables=None):
    c = config or {}
    method = _method(c, {"tukey", "dunn", "holm", "fdr"}, "holm")
    alpha = _alpha(c)
    if method in {"holm", "fdr"}:
        column = c.get("column", "pvalue")
        frame = require_table(table, [column])
        p = numeric_matrix(frame, [column])[:, 0]
        if np.any((p < 0) | (p > 1)):
            raise ValueError("p-values must be in [0,1]")
        reject, adjusted, _, _ = multipletests(
            p, alpha=alpha, method="holm" if method == "holm" else "fdr_bh"
        )
        frame["p_adjusted"], frame["reject"] = adjusted, reject
        return NodeResult(frame, {"method": method, "alpha": alpha, "family_size": len(p)})
    _, labels, values = _groups(table, c)
    rows = []
    if method == "tukey":
        if sum(float(v.var()) for v in values) == 0:
            raise ValueError("Tukey requires within-group variance")
        test = stats.tukey_hsd(*values)
        ci = test.confidence_interval(confidence_level=1 - alpha)
        for i, j in combinations(range(len(values)), 2):
            rows.append(
                {
                    "group1": labels[i],
                    "group2": labels[j],
                    "mean_difference": float(test.statistic[i, j]),
                    "p_adjusted": float(test.pvalue[i, j]),
                    "ci_low": float(ci.low[i, j]),
                    "ci_high": float(ci.high[i, j]),
                    "reject": bool(test.pvalue[i, j] < alpha),
                }
            )
        assumptions = ["Independent, normal groups with common variance; Tukey-Kramer for unequal sizes."]
    else:
        merged = np.concatenate(values)
        ranks = stats.rankdata(merged)
        n = len(merged)
        _, ties = np.unique(merged, return_counts=True)
        variance = n * (n + 1) / 12 - sum(t**3 - t for t in ties) / (12 * (n - 1))
        if variance <= 0:
            raise ValueError("Dunn requires nonidentical observations")
        starts = np.r_[0, np.cumsum([len(v) for v in values])]
        means = [ranks[starts[i] : starts[i + 1]].mean() for i in range(len(values))]
        for i, j in combinations(range(len(values)), 2):
            z = (means[i] - means[j]) / np.sqrt(variance * (1 / len(values[i]) + 1 / len(values[j])))
            rows.append(
                {
                    "group1": labels[i],
                    "group2": labels[j],
                    "z": float(z),
                    "pvalue": float(2 * stats.norm.sf(abs(z))),
                }
            )
        correction = c.get("correction", "holm")
        if correction not in {"holm", "fdr"}:
            raise ValueError("Dunn correction must be holm or fdr")
        reject, p, _, _ = multipletests(
            [r["pvalue"] for r in rows], alpha=alpha, method="holm" if correction == "holm" else "fdr_bh"
        )
        for row, adj, rejected in zip(rows, p, reject, strict=True):
            row.update(p_adjusted=float(adj), reject=bool(rejected))
        assumptions = [
            "Independent ordinal groups; Dunn uses pooled ranks and a tie-corrected normal approximation."
        ]
    return NodeResult(
        pd.DataFrame(rows),
        {
            "method": method,
            "alpha": alpha,
            "assumptions": assumptions,
            "correction": c.get("correction", "holm") if method == "dunn" else "tukey",
        },
    )


def regression(table=None, *, config=None, data=None, tables=None):
    from .stats_models import fit_model

    c = dict(config or {})
    _method(c, {"linear", "polynomial", "ridge", "lasso"}, "linear")
    return fit_model(table, c, default="linear")


def predict(table=None, *, config=None, data=None, tables=None):
    from .stats_models import fit_model, has_saved_model, predict_saved

    c = config or {}
    if has_saved_model(c, data):
        return predict_saved(table, c, data or {})
    _method(c, {"random_forest", "gradient_boosting", "svr"}, "random_forest")
    return fit_model(table, c, default="random_forest")


def evaluate(table=None, *, config=None, data=None, tables=None):
    from .stats_models import evaluate_model, has_saved_model

    config, data = config or {}, data or {}
    provided = ("y_true" in data and "y_pred" in data) or (config.get("y_true") and config.get("y_pred"))
    if config.get("models") and not provided and not has_saved_model(config, data):
        from .model_comparison import compare_models

        return compare_models(table, config)
    return evaluate_model(table, config, data)


_ENTRIES = [
    ("grouped", "分组统计", {"group": "group", "columns": ["value"]}),
    ("distribution", "分布检查", {"column": "value", "bins": "auto"}),
    ("correlation", "相关性分析", {"columns": ["x", "y"], "method": "pearson"}),
    ("significance", "显著性检验", {"group": "group", "column": "value", "method": "welch"}),
    ("multiple", "多重比较", {"column": "pvalue", "method": "holm"}),
    ("regression", "回归分析", {"features": ["x"], "target": "y", "method": "linear", "seed": 42}),
    ("predict", "预测模型", {"features": ["x"], "target": "y", "method": "random_forest", "seed": 42}),
    (
        "evaluate",
        "模型评估",
        {"features": ["x"], "target": "y", "method": "cv", "model_method": "linear", "seed": 42},
    ),
]
CATALOG = [
    {
        "key": f"stats.{name}",
        "title": title,
        "function": f"materials_quality.science.statistics:{name}",
        "category": "统计与建模",
        "requirement": title,
        "table_input": True,
        "data_input": name in {"predict", "evaluate"},
        "tables_input": False,
        "default_config": default,
    }
    for name, title, default in _ENTRIES
]
