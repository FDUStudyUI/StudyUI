"""Run independently generated design simulations and real statistical extraction."""

import argparse
import json

from materials_quality.evaluation.design import (
    DEFAULT_REPETITIONS,
    DEFAULT_SEED,
    build_trials,
    run_design_evaluation,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Fresh artifact directory")
    parser.add_argument(
        "--repetitions",
        type=int,
        default=DEFAULT_REPETITIONS,
        help="Independent trials per design stratum; 16 strata",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    summary = run_design_evaluation(
        args.output, trials=build_trials(repetitions=args.repetitions, seed=args.seed)
    )
    print(
        json.dumps(
            {
                "output": args.output,
                "independent_trials": summary["independent_trials"],
                "oracle_mismatches": summary["oracle_mismatches"],
                "pipeline_failures": summary["pipeline_failures"],
                "wall_seconds": summary["wall_seconds"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if summary["oracle_mismatches"] or summary["pipeline_failures"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
