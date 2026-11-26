"""Offline local repair demonstration; no file writes or external services.

From repository root:
  .superpowers/run-tests.ps1 examples/analysis_plan_demo.py
"""

import json

import pandas as pd

from materials_quality.science.analysis_plan import AnalysisPlanRunner


def main():
    source = pd.DataFrame({"sample": ["a", "b", "c"], "stress": [1.0, 2.0, 3.0]})
    source.attrs["units"] = {"stress": "MPa"}
    steps = [
        {"id": "source", "operation": "preprocess.filter"},
        {
            "id": "convert",
            "operation": "preprocess.units",
            "dependencies": ["source"],
            "config": {"target_units": {"stress": "K"}},
        },
        {
            "id": "independent",
            "operation": "preprocess.filter",
            "dependencies": ["source"],
            "config": {"columns": ["sample", "stress"]},
        },
        {"id": "downstream", "operation": "preprocess.filter", "dependencies": ["convert", "independent"]},
    ]
    runner = AnalysisPlanRunner(max_steps=4, max_executions=4)
    failed = runner.run(steps, {"input": source})
    assert failed.records["convert"].status == "failed"
    assert failed.records["downstream"].status == "blocked"
    assert failed.execution_count == 3
    # Explicit scientific repair: kelvin is incompatible with stress.
    steps[1]["config"]["target_units"]["stress"] = "Pa"
    repaired = runner.run(steps, {"input": source}, previous=failed)
    assert repaired.execution_count == 2 and repaired.reuse_count == 2
    assert repaired.records["downstream"].result.table.stress.tolist() == [1e6, 2e6, 3e6]
    unchanged = runner.run(steps, {"input": source}, previous=repaired)
    assert unchanged.execution_count == 0 and unchanged.reuse_count == 4
    assert source.stress.tolist() == [1.0, 2.0, 3.0]
    print(
        json.dumps(
            {
                "first": {k: r.status for k, r in failed.records.items()},
                "repaired": {k: r.status for k, r in repaired.records.items()},
                "counts": {
                    "first": failed.execution_count,
                    "repair": repaired.execution_count,
                    "unchanged": unchanged.execution_count,
                },
                "stress_Pa": repaired.records["downstream"].result.table.stress.tolist(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
