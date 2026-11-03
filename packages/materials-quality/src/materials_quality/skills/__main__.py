"""Command-line research tasks; ordinary use requires flags rather than JSON."""

import argparse
import json
import sys

import pandas as pd

from .planning import make_plan
from .registry import inspect_skill, list_skills


def main(argv=None):
    parser = argparse.ArgumentParser(description="StudyUI 科研技能：预览计划、受控分析和追溯导出")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="列出随项目交付的技能")
    inspect = commands.add_parser("inspect", help="只读预览本地技能，不授权执行")
    inspect.add_argument("directory")
    for command in ("plan", "run"):
        p = commands.add_parser(command)
        p.add_argument("file")
        p.add_argument("--task", choices=["auto", "spectra", "mechanics", "contrast"], default="auto")
        p.add_argument("--request", default="")
        p.add_argument("--output")
        p.add_argument("--model", action="store_true", help="显式开启环境变量配置的模型建议")
        for field in (
            "curve-id",
            "x",
            "y",
            "group",
            "x-unit",
            "y-unit",
            "sample-id",
            "strain",
            "stress",
            "strain-unit",
            "stress-unit",
            "variable",
            "value",
            "experimental-unit",
            "design",
            "strategy",
            "correction",
            "value-unit",
            "baseline",
            "data-kind",
            "band",
            "selection-rule",
            "prominence-mode",
            "unit-mode",
            "small-sample-policy",
        ):
            p.add_argument("--" + field)
        for field in ("peak-window", "fit-range", "noise-window"):
            p.add_argument("--" + field, type=float, nargs=2)
        for field in (
            "baseline-value",
            "prominence",
            "yield-offset",
            "alpha",
            "noise-multiplier",
            "peak-distance-x",
        ):
            p.add_argument("--" + field, type=float)
        for field in ("smooth-window", "smooth-order"):
            p.add_argument("--" + field, type=int)
        p.add_argument("--single-sample", action="store_true", default=None)
        p.add_argument("--smooth", action="store_true", default=None)
        p.add_argument("--unit-confirmed", action="store_true", default=None)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "list":
            value = list_skills()
        elif command == "inspect":
            value = inspect_skill(args["directory"])
        else:
            from .execution import execute_plan

            path = args.pop("file")
            # CSV is textual: preserve identifiers exactly, including 001 and literal NA.
            # Numeric conversion belongs to the scientific operation on its own copy.
            table = pd.read_csv(
                path, sep=None, engine="python", encoding="utf-8-sig", dtype=str, keep_default_na=False
            )
            task, request, output, model = (args.pop(k) for k in ("task", "request", "output", "model"))
            parameters = {k: v for k, v in args.items() if v is not None}
            if model:
                from .model import suggest_plan

                plan = suggest_plan(table, request, task=task, parameters=parameters)
            else:
                plan = make_plan(table, task=task, request=request, parameters=parameters)
            if command == "plan":
                value = plan
            else:
                r = execute_plan(table, plan, output_dir=output)
                value = {"summary": r.summary, "status": r.report["status"], "artifacts": r.artifacts}
        print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if command != "run" or value["status"] == "completed" else 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"操作未完成：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
