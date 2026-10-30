"""Run every required statistics/modeling submethod on labeled synthetic data.

From the package root: python examples/science/statistics/run_demo.py
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from materials_quality.science import statistics as nodes


def run(output_dir):
    source = Path(__file__).resolve().parent
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    groups = pd.read_csv(source / "groups.csv", dtype={"sample": str})
    pairs = pd.read_csv(source / "paired.csv")
    x = np.linspace(-3, 3, 60)
    modeling = pd.DataFrame({"sample": [f"s{i:03d}" for i in range(60)], "x": x, "y": 2 * x + 3})
    records = []

    def invoke(name, method, table, config=None, data=None):
        config = {"data_kind": "synthetic", **(config or {}), "output_dir": str(output / f"{name}-{method}")}
        result = getattr(nodes, name)(table, config=config, data=data)
        records.append(
            {
                "node": f"stats.{name}",
                "method": method,
                "config": config,
                "data": result.data,
                "artifacts": result.artifacts,
                "warnings": result.warnings,
                "table": result.table.to_dict("records") if result.table is not None else None,
            }
        )
        return result

    invoke("grouped", "all_descriptors", groups, {"group": "group", "columns": ["value"]})
    invoke("distribution", "histogram_qq_shapiro", groups, {"column": "value"})
    for method in ["pearson", "spearman", "kendall"]:
        invoke("correlation", method, groups, {"columns": ["x", "y"], "method": method})
    for method in ["independent_t", "welch", "mannwhitney", "anova", "kruskal"]:
        frame = groups if method in {"anova", "kruskal"} else groups[groups.group != "b"]
        invoke(
            "significance",
            method,
            frame,
            {"group": "group", "column": "value", "method": method, "subject": "sample"},
        )
    invoke(
        "significance",
        "paired_t",
        pairs,
        {"group": "group", "column": "value", "method": "paired_t", "pair_id": "pair_id"},
    )
    for method in ["tukey", "dunn"]:
        invoke("multiple", method, groups, {"group": "group", "column": "value", "method": method})
    for method in ["holm", "fdr"]:
        invoke("multiple", method, pd.DataFrame({"pvalue": [0.01, 0.04, 0.03]}), {"method": method})
    fitted = None
    for method in ["linear", "polynomial", "ridge", "lasso", "random_forest", "gradient_boosting", "svr"]:
        name = "regression" if method in ["linear", "polynomial", "ridge", "lasso"] else "predict"
        fitted = invoke(
            name,
            method,
            modeling,
            {
                "features": ["x"],
                "target": "y",
                "method": method,
                "alpha": 0.001,
                "id_column": "sample",
                "seed": 42,
            },
        )
    invoke("predict", "saved_model", modeling, {"model_path": fitted.data["model_path"]}, fitted.data)
    heldout = modeling.iloc[fitted.data["test_positions"]]
    for operation in ["predict", "evaluate"]:
        frame = modeling if operation == "predict" else heldout
        invoke(operation, "config_manifest", frame, {"manifest_path": fitted.data["manifest_path"]})
        invoke(operation, "upstream_manifest", frame, {}, {"manifest_path": fitted.data["manifest_path"]})
    for method in ["holdout", "cv"]:
        invoke(
            "evaluate",
            method,
            modeling,
            {
                "features": ["x"],
                "target": "y",
                "method": method,
                "model_method": "linear",
                "seed": 42,
                "folds": 5,
            },
        )
    invoke("evaluate", "explicit_predictions", None, {}, {"y_true": [1, 2, 3], "y_pred": [1, 3, 2]})
    manifest = output / "statistics-demo.json"
    manifest.write_text(
        json.dumps({"synthetic": True, "runs": records}, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    json.loads(manifest.read_text(encoding="utf-8"))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="artifacts/science-statistics-demo")
    print(run(parser.parse_args().output_dir))
