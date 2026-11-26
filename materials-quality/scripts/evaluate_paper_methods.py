"""Fixed decision tests and optional Corn/Tecator integration reference, no model calls."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from materials_quality.science.chemometrics import chemometrics
from materials_quality.science.method_cards import recommend_methods
from materials_quality.science.research_plan import run_research_plan
from scripts.build_paper_examples import regression_table


def _prediction_reference(table, features):
    config = {
        "method": "pls",
        "feature_columns": features,
        "sample_column": "sample_id",
        "split_column": "split",
        "target_column": "target",
        "n_components": 4,
    }
    actual = chemometrics(table, config=config)
    train = table["split"] == "train"
    reference = make_pipeline(
        StandardScaler(), PLSRegression(n_components=4, scale=False, max_iter=1000, tol=1e-6)
    )
    reference.fit(table.loc[train, features], table.loc[train, "target"])
    predicted = reference.predict(table[features]).ravel()
    difference = float(np.max(np.abs(predicted - actual.table["prediction"].to_numpy())))
    changed = table.copy()
    changed.loc[~train, features] = changed.loc[~train, features] * 100 + 500
    other = chemometrics(changed, config=config)
    isolated = actual.data["model"] == other.data["model"]
    return {
        "max_abs_reference_difference": difference,
        "test_changes_leave_model_unchanged": isolated,
        "metrics": actual.data["metrics"],
        "train_ids": actual.data["train_sample_ids"],
        "test_ids": actual.data["test_sample_ids"],
        "passed": difference < 1e-9 and isolated,
    }


def evaluate(data_root=None):
    cases = []
    for name, query, facts, expected in [
        ("unknown_signal", "SNV", {}, "missing"),
        (
            "retain_absolute_intensity",
            "SNV",
            {
                "signal_type": "darkfield_intensity",
                "x_unit": "nm",
                "y_unit": "counts",
                "allow_intensity_loss": False,
            },
            "blocked",
        ),
        (
            "nonuniform_derivative",
            "sg_first_derivative",
            {"signal_type": "raman_intensity", "x_unit": "nm", "y_unit": "counts", "equally_spaced": False},
            "blocked",
        ),
        ("unrelated_query", "unrelated_control_739284", {}, "no_match"),
    ]:
        result = recommend_methods(config={"query": query, **facts})
        statuses = [row["status"] for row in result.data["candidates"]]
        actual = "no_match" if not statuses else expected if expected in statuses else statuses[0]
        cases.append(
            {
                "case": name,
                "input": {"query": query, **facts},
                "expected": expected,
                "actual_statuses": statuses,
                "passed": actual == expected,
            }
        )
    reference = _prediction_reference(regression_table(), [f"band_{i}" for i in range(6)])
    cases.append({"case": "synthetic_pls_reference_and_isolation", **reference})
    table = pd.DataFrame({"group": ["a", "a", "b", "b"], "value": [1.0, 2, 5, 8]})
    _, before = run_research_plan(table, {"normalization": "invalid"})
    repaired, _ = run_research_plan(table, previous=before)
    cases.append(
        {
            "case": "local_repair",
            "expected_reuse": 1,
            "actual_reuse": repaired.data["reuse_count"],
            "passed": repaired.data["reuse_count"] == 1 and repaired.data["execution_status"] == "completed",
        }
    )
    external = []
    if data_root:
        root = Path(data_root)
        for dataset, xf, yf in [
            ("corn", "corn_data.npy", "protein_label.npy"),
            ("tecator", "tecator_data.npy", "tecator_label.npy"),
        ]:
            paths = [root / dataset / xf, root / dataset / yf]
            x, y = (np.load(path, allow_pickle=False) for path in paths)
            y = y.ravel()
            if x.ndim != 2 or len(x) != len(y):
                raise ValueError("external dataset shapes are inconsistent")
            features = [f"band_{i}" for i in range(x.shape[1])]
            frame = pd.DataFrame(x, columns=features)
            frame["target"] = y
            frame["sample_id"] = [f"{dataset}-{i}" for i in range(len(x))]
            _, test = train_test_split(np.arange(len(x)), test_size=0.2, random_state=42)
            frame["split"] = "train"
            frame.loc[test, "split"] = "test"
            external.append(
                {
                    "dataset": dataset,
                    "files": [
                        {"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths
                    ],
                    "scope": (
                        "assumed single instrument; row-based IDs and fixed split; "
                        "specimen/instrument identities and label units not verified from arrays"
                    ),
                    **_prediction_reference(frame, features),
                }
            )
    return {
        "scope": "deterministic integration and analysis decisions; not online LLM or BLADE benchmark",
        "reference": (
            "Independent caller of the same sklearn algorithm; tests integration, not algorithm novelty"
        ),
        "cases": cases,
        "external_data": external,
        "passed": all(case["passed"] for case in [*cases, *external]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.data_root)
    raw = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, "utf-8")
    print(raw)
    raise SystemExit(0 if report["passed"] else 1)
