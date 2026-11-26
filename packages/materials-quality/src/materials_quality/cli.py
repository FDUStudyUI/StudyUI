"""Unified StudyUI CLI with structured doctor diagnostics (E01-E06)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from .assets import build_default_asset_graph
from .evaluation import (
    merge_expert_review_scores,
    render_evaluation_markdown,
    run_materials_evaluation_suite,
)
from .science.plugins import pybamm_available, pymatgen_available


def run_doctor(*, runtime_dir: str | Path | None = None) -> dict[str, Any]:
    """Run deterministic environment, asset-graph, and plugin checks (E01-E06)."""
    checks: list[dict[str, Any]] = []

    # E01: Python version check
    py_ok = (3, 10) <= sys.version_info[:2] < (3, 15)
    checks.append(
        {
            "code": "E01",
            "name": "python_version",
            "status": "ok" if py_ok else "error",
            "detail": f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "hint": "" if py_ok else "需要 Python 3.10 至 3.14 环境。",
        }
    )

    # E02: Core scientific dependencies
    core_mods = ("numpy", "pandas", "scipy", "pint", "jsonschema")
    missing_core = [m for m in core_mods if importlib.util.find_spec(m) is None]
    checks.append(
        {
            "code": "E02",
            "name": "core_science_dependencies",
            "status": "ok" if not missing_core else "error",
            "detail": "all core packages present" if not missing_core else f"missing: {missing_core}",
            "hint": "" if not missing_core else "执行 pip install -e 'packages/materials-quality[science]'。",
        }
    )

    # E03: Scientific AssetGraph validation
    graph = build_default_asset_graph()
    summary = graph.summary()
    graph_ok = summary["error_count"] == 0
    checks.append(
        {
            "code": "E03",
            "name": "asset_graph_integrity",
            "status": "ok" if graph_ok else "error",
            "detail": (
                f"{summary['total_assets']} assets, {summary['total_edges']} edges, "
                f"{summary['error_count']} errors"
            ),
            "hint": "" if graph_ok else "运行 pytest tests/test_asset_graph.py 排查资产图谱校验错误。",
        }
    )

    # E04: Built-in real-instrument examples availability
    try:
        from .material_examples import examples

        count = len(examples())
        ex_ok = count > 0
        ex_detail = f"{count} attributed real-instrument example(s) available"
    except Exception as exc:
        ex_ok = False
        ex_detail = str(exc)
    checks.append(
        {
            "code": "E04",
            "name": "real_instrument_examples",
            "status": "ok" if ex_ok else "error",
            "detail": ex_detail,
            "hint": "" if ex_ok else "检查 packages/materials-quality/src/materials_quality/material_examples。",
        }
    )

    # E05: Optional compute solver plugins (warning only when absent)
    pmg = pymatgen_available()
    pbm = pybamm_available()
    checks.append(
        {
            "code": "E05",
            "name": "optional_compute_plugins",
            "status": "ok" if (pmg and pbm) else "warn",
            "detail": f"pymatgen={'installed' if pmg else 'missing'}, pybamm={'installed' if pbm else 'missing'}",
            "hint": (
                ""
                if (pmg and pbm)
                else "可选：执行 pip install 'langflow-materials-quality[compute]' 启用 CIF 理论 XRD 与 PyBaMM 仿真。"
            ),
        }
    )

    # E06: Runtime directory writability
    target_dir = Path(runtime_dir) if runtime_dir is not None else Path(tempfile.gettempdir())
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        probe = target_dir / ".studyui_doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        rw_ok = True
        rw_detail = f"writable: {target_dir}"
    except Exception as exc:
        rw_ok = False
        rw_detail = str(exc)
    checks.append(
        {
            "code": "E06",
            "name": "runtime_storage_writable",
            "status": "ok" if rw_ok else "error",
            "detail": rw_detail,
            "hint": "" if rw_ok else "请确认当前工作目录具有写入权限。",
        }
    )

    error_count = sum(1 for item in checks if item["status"] == "error")
    warn_count = sum(1 for item in checks if item["status"] == "warn")
    return {
        "healthy": error_count == 0,
        "error_count": error_count,
        "warning_count": warn_count,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studyui", description="StudyUI Materials Research CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("doctor", help="Run environment, asset-graph, and plugin diagnostics")
    p_doc.add_argument("--json", action="store_true", dest="as_json")
    p_doc.add_argument("--runtime-dir", default=None)

    p_assets = sub.add_parser("assets", help="Inspect the scientific asset graph")
    p_assets.add_argument("action", choices=["summary"])
    p_assets.add_argument("--json", action="store_true", dest="as_json")

    p_eval = sub.add_parser("eval-suite", help="Run the decoupled 3-dimension evaluation suite")
    p_eval.add_argument("--output", default="artifacts/materials-suite-eval")
    p_eval.add_argument("--mode", choices=["reference", "agent_scripted", "agent_live"], default="reference")
    p_eval.add_argument("--repeats", type=int, choices=range(2, 6), default=3)
    p_eval.add_argument("--skip-replay", action="store_true")
    p_eval.add_argument("--case-ids", default=None, help="Comma-separated subset of instrument case IDs")

    p_merge = sub.add_parser("merge-review", help="Merge expert blind-review CSV scores into evaluation_report.json")
    p_merge.add_argument("--report", required=True, help="Path to evaluation_report.json")
    p_merge.add_argument("--scores", required=True, help="Path to filled expert_review_blind_sheet.csv")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        result = run_doctor(runtime_dir=args.runtime_dir)
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for item in result["checks"]:
                print(f"[{item['code']}] {item['status'].upper():5s} {item['name']}: {item['detail']}")
                if item["hint"]:
                    print(f"      -> {item['hint']}")
        return 0 if result["healthy"] else 1

    if args.command == "assets":
        summary = build_default_asset_graph().summary()
        if args.as_json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(
                f"Assets: {summary['total_assets']} | Edges: {summary['total_edges']} | "
                f"Errors: {summary['error_count']} | By type: {summary['by_type']}"
            )
        return 0 if summary["error_count"] == 0 else 1

    if args.command == "eval-suite":
        case_ids = (
            [item.strip() for item in args.case_ids.split(",") if item.strip()]
            if args.case_ids
            else None
        )
        report = run_materials_evaluation_suite(
            args.output,
            mode=args.mode,
            repeats=args.repeats,
            skip_replay=args.skip_replay,
            case_ids=case_ids,
        )
        print(
            json.dumps(
                {
                    "workflow_build": report["workflow_build"],
                    "reproducibility": report["reproducibility"],
                    "method_correctness": {
                        k: v
                        for k, v in report["method_correctness"].items()
                        if k != "expert_review"
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        all_built = report["workflow_build"]["built_valid"] == report["workflow_build"]["total"]
        all_neg_blocked = (
            report["method_correctness"]["negative_boundary_blocked"]
            == report["method_correctness"]["negative_boundary_total"]
        )
        return 0 if (all_built and all_neg_blocked) else 1

    if args.command == "merge-review":
        report_path = Path(args.report).resolve()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        updated = merge_expert_review_scores(report, args.scores)
        report_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path = report_path.with_name("evaluation_report.md")
        md_path.write_text(render_evaluation_markdown(updated), encoding="utf-8")
        print(json.dumps(updated["method_correctness"]["expert_review"], ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
