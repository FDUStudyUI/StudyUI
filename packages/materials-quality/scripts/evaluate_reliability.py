"""Run frozen independent analytic evaluation; no output directory is overwritten."""

import argparse
import json

from materials_quality.evaluation.spectral import STRATEGIES, build_pool, run_evaluation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Fresh artifact directory")
    parser.add_argument("--split", choices=("all", "dev", "holdout"), default="all")
    parser.add_argument("--strategy", choices=("all", *STRATEGIES), default="all")
    args = parser.parse_args()
    cases = [c for c in build_pool() if args.split == "all" or c.split == args.split]
    strategies = STRATEGIES if args.strategy == "all" else (args.strategy,)
    summary = run_evaluation(args.output, cases=cases, strategies=strategies)
    print(
        json.dumps(
            {
                "output": args.output,
                "overall": summary["overall"],
                "failure_curve_runs": summary["failure_curve_runs"],
                "uncertainty": summary["uncertainty"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
