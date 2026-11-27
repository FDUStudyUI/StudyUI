#!/usr/bin/env python3
"""Merge one or more harness-bench output directories into one summary.

The hard suite is run in one-repetition chunks when a single multi-repetition
process would exceed the local command time limit.  This utility preserves the
per-run logs and recomputes the same deterministic aggregate/report that the
evaluator produces for one run.

Usage:
    python materials-quality/scripts/merge_harness_runs.py \
        --output materials-quality/artifacts/harness-bench/hard-final-3rep \
        --run-dir materials-quality/artifacts/harness-bench/hard-final-r1 \
        --run-dir materials-quality/artifacts/harness-bench/hard-final-r2 \
        --run-dir materials-quality/artifacts/harness-bench/hard-final-r3
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "evaluate_harnesses.py"
spec = importlib.util.spec_from_file_location("evaluate_harnesses", SCRIPT)
if spec is None or spec.loader is None:
    raise SystemExit(f"cannot load {SCRIPT}")
bench = importlib.util.module_from_spec(spec)
sys.modules["evaluate_harnesses"] = bench
spec.loader.exec_module(bench)


def load_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def runs_from_dir(run_dir: Path, tasks: dict[str, dict] | None = None) -> list[dict]:
    jsonl = run_dir / "runs.jsonl"
    if jsonl.is_file():
        rows = []
        try:
            for line in jsonl.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows = []
        if rows:
            for row in rows:
                task = (tasks or {}).get(row.get("task_id"))
                # Artifact bytes are not stored in result.json; keep the
                # original artifact-aware score for report-delivery tasks.
                if task and not task.get("artifacts"):
                    row["score"] = bench.score_run(task, row.get("result") or {})
            return rows
    # Fallback for a process interrupted before it wrote runs.jsonl.
    rows = []
    for result_path in sorted((run_dir / "runs").glob("*/*/rep-*/result.json")):
        score_path = result_path.with_name("score.json")
        if not score_path.is_file():
            continue
        relative = result_path.relative_to(run_dir / "runs")
        harness, task_id, repeat_dir = relative.parts[:3]
        repeat = int(repeat_dir.split("-")[-1])
        result = load_json(result_path, {})
        score = load_json(score_path, {})
        task = (tasks or {}).get(task_id)
        if task and not task.get("artifacts"):
            score = bench.score_run(task, result)
        rows.append(
            {
                "harness": harness,
                "task_id": task_id,
                "repeat": repeat,
                "result": result,
                "score": score,
                "paths": {
                    "run_dir": str(result_path.parent),
                    "result": str(result_path),
                    "score": str(score_path),
                },
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    run_dirs = [path.resolve() for path in args.run_dir]
    first_summary = load_json(run_dirs[0] / "summary.json", {})
    runs: list[dict] = []
    tasks_file = Path(first_summary.get("tasks_file") or "").expanduser()
    tasks: dict[str, dict] = {}
    if tasks_file and tasks_file.is_file():
        tasks = {
            task["id"]: task
            for task in json.loads(tasks_file.read_text(encoding="utf-8")).get("tasks", [])
        }
    for run_dir in run_dirs:
        rows = runs_from_dir(run_dir, tasks)
        if not rows:
            raise SystemExit(f"no runs found under {run_dir}")
        runs.extend(rows)
    manifest = {
        key: first_summary.get(key)
        for key in (
            "git",
            "platform",
            "python",
            "model",
            "model_label",
            "base_url",
            "model_probe",
            "tasks_file",
            "suite",
            "tasks",
            "harnesses_requested",
            "studyui_source",
            "max_turns",
        )
        if key in first_summary
    }
    repeats = {}
    for run in runs:
        repeats[(run["harness"], run["task_id"])] = repeats.get((run["harness"], run["task_id"]), 0) + 1
    manifest.update(
        run_id=output.name,
        timestamp=bench.datetime.now(bench.timezone.utc).isoformat(timespec="seconds"),
        repeats=max(repeats.values()) if repeats else 0,
        runs_dirs=[str(path) for path in run_dirs],
        merged_from=len(run_dirs),
        harnesses_run=sorted({run["harness"] for run in runs}),
        harnesses_skipped=[],
    )
    harnesses = []
    for row in first_summary.get("harnesses") or []:
        allowed = {
            key: row.get(key)
            for key in ("name", "available", "detail", "reason", "command", "model", "extras")
            if key in row
        }
        harnesses.append(bench.HarnessInfo(**allowed))
    if not harnesses:
        raise SystemExit(f"no harness metadata in {run_dirs[0] / 'summary.json'}")
    bench.write_outputs(output, runs, manifest, harnesses)
    summary = bench.aggregate(runs)
    print(f"merged {len(runs)} runs from {len(run_dirs)} directories into {output}")
    for harness in bench.HARNESS_ORDER:
        row = summary["overall"].get(harness)
        if row:
            print(
                f"{harness:12s} n={row['n']:3d} success={row['success_rate']:.3f} "
                f"partial={row['partial_score']:.3f} tool={row['tool_use_rate']:.3f} "
                f"latency={row['mean_latency_s']}s"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
