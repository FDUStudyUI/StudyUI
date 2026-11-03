"""Execute only a current, validated plan using fixed scientific operations."""

import platform
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import pandas as pd

from materials_quality import __version__
from materials_quality.common import json_value

from .planning import input_identity, validate_plan
from .registry import load_skill
from .reporting import deliver
from .tasks import TASKS


@dataclass
class ResearchResult:
    table: pd.DataFrame
    features: pd.DataFrame
    curves: pd.DataFrame
    groups: pd.DataFrame
    report: dict
    artifacts: list
    summary: str


def execute_plan(table, plan, output_dir=None):
    plan = validate_plan(table, plan)
    started = perf_counter()
    if output_dir is not None:
        parent = Path(output_dir).expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="research-", dir=parent))
    else:
        output = Path(tempfile.mkdtemp(prefix="studyui-research-"))
    result = TASKS[plan["task"]](table.copy(deep=True), plan["parameters"], output)
    if input_identity(table) != plan["input"]:
        raise RuntimeError("input changed during execution")
    counts = result.data["counts"]
    status = result.data["execution_status"]
    title = load_skill(plan["task"])["title"]
    summary = (
        f"{title}：状态 {status}；共 {counts['total']} 项，完成 {counts['completed']}，"
        f"失败/不可估计 {counts['failed']}。"
    )
    if plan["task"] == "spectra":
        valid = sum(row.get("lambda10_nm") is not None for row in result.data["curve_summary"])
        summary += f" 检出 {valid} 条窗口候选；峰特征 {len(result.features)} 行。"
    elif plan["task"] == "mechanics" and "elastic_modulus_MPa" in result.table:
        values = result.table["elastic_modulus_MPa"].dropna()
        if len(values):
            summary += f" 弹性模量范围 {values.min():.6g}–{values.max():.6g} MPa。"
    else:
        summary += " 统计单位为技术重复聚合后的独立试验单位。"
    warnings = list(dict.fromkeys([*plan["warnings"], *result.warnings]))
    report = json_value(
        {
            "schema_version": "research-result/1",
            "task": plan["task"],
            "status": status,
            "counts": counts,
            "summary": summary,
            "warnings": warnings,
            "data": result.data,
            "tables": {
                name: {
                    "rows": len(getattr(result, name)),
                    "columns": list(getattr(result, name).columns),
                    "units": getattr(result, name).attrs.get("units", {}),
                    "available": bool(len(getattr(result, name).columns)),
                    "preview": getattr(result, name).head(20).to_dict("records"),
                }
                for name in ("table", "features", "curves", "groups")
            },
            "plan": plan,
            "provenance": {
                "input": plan["input"],
                "plan_sha256": plan["plan_sha256"],
                "skill": plan["skill"],
                "sources": load_skill(plan["task"])["sources"],
                "parameters": plan["parameters"],
                "raw_preserved": True,
                "package_version": __version__,
                "python": platform.python_version(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": perf_counter() - started,
            },
        }
    )
    artifacts = deliver(result, report, output, summary)
    return ResearchResult(
        result.table, result.features, result.curves, result.groups, report, artifacts, summary
    )
