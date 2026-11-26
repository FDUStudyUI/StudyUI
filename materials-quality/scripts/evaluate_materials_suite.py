"""CLI runner for the Sprint 4 decoupled real-instrument evaluation suite."""

from __future__ import annotations

import argparse
import json

from materials_quality.evaluation import run_materials_evaluation_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/materials-suite-eval")
    parser.add_argument("--repeats", type=int, choices=range(2, 6), default=3)
    parser.add_argument("--skip-replay", action="store_true")
    args = parser.parse_args(argv)

    report = run_materials_evaluation_suite(
        args.output,
        repeats=args.repeats,
        skip_replay=args.skip_replay,
    )
    summary = {
        "workflow_build": report["workflow_build"],
        "reproducibility": report["reproducibility"],
        "method_correctness": {k: v for k, v in report["method_correctness"].items() if k != "expert_review"},
        "decoupling_diagnostics": report["decoupling_diagnostics"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    all_built = report["workflow_build"]["built_valid"] == report["workflow_build"]["total"]
    all_neg_blocked = (
        report["method_correctness"]["negative_boundary_blocked"]
        == report["method_correctness"]["negative_boundary_total"]
    )
    return 0 if (all_built and all_neg_blocked) else 1


if __name__ == "__main__":
    raise SystemExit(main())
