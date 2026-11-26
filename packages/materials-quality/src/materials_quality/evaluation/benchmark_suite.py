"""Decoupled three-dimension real-instrument evaluation suite (Sprint 4).

Strictly separates three independent evaluation questions:
1. Workflow Build Rate: Did the system/agent construct a valid executable workflow?
2. Computational Reproducibility: Given a frozen workflow, do repeated runs produce
   byte-identical results and match an independent closed-form numerical reference?
3. Methodological Correctness: Are the chosen method, parameters, and applicability
   boundaries valid on positive real-instrument files, blocked on out-of-scope
   negative cases, and verified via structured expert blind review?
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..agent.file_workflow_client import FileWorkflowClient
from ..agent.harness import StudyUIAgent
from ..agent.model import ChatModel
from ..agent.workflow import apply_actions
from ..assets import build_default_asset_graph
from ..material_examples import compile_example, examples, prepared_input, read_source
from ..science.catalog import component_class
from ..science.runtime_guards import evaluate_runtime_guards

EXPERT_RUBRIC_COLUMNS = (
    "case_id",
    "task_family",
    "method_selection_1_to_5",
    "parameter_validity_1_to_5",
    "limitation_rigor_1_to_5",
    "reviewer_notes",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _asset_graph_digest() -> dict[str, Any]:
    graph = build_default_asset_graph()
    summary = graph.summary()
    raw = json.dumps(graph.to_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {
        "total_assets": summary["total_assets"],
        "total_edges": summary["total_edges"],
        "error_count": summary["error_count"],
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def classify_build_failure(error_text: str) -> str:
    """Categorize a workflow build failure into standard diagnostic buckets."""
    lower = (error_text or "").lower()
    if any(kw in lower for kw in ("parse", "decode", "unicode", "csv", "excel", "format")):
        return "parse_error"
    if any(kw in lower for kw in ("column", "mapping", "unit", "keyerror")):
        return "column_mapping"
    if any(kw in lower for kw in ("port", "edge", "cycle", "handle", "connect")):
        return "port_mismatch"
    if any(kw in lower for kw in ("timeout", "budget", "token", "max_steps")):
        return "budget_exceeded"
    return "other"


def negative_boundary_cases() -> list[dict[str, Any]]:
    """Six out-of-scope / physically invalid cases that runtime GUARD must block."""
    # 1. Non-monotonic cyclic loading curve fed to monotonic tensile fit
    cyclic_strain = np.array([0.0002, 0.0005, 0.0008, 0.0010, 0.0006, 0.0009, 0.0012])
    cyclic_stress = cyclic_strain * 110_000.0
    cyclic_df = pd.DataFrame({"strain": cyclic_strain, "stress": cyclic_stress})

    # 2. Strongly nonlinear elbow curve (positive overall slope, low linear R^2)
    nl_strain = np.linspace(0.0, 0.01, 20)
    nl_stress = np.where(nl_strain < 0.007, 10.0 * nl_strain, 0.07 + 200_000.0 * (nl_strain - 0.007))
    nl_df = pd.DataFrame({"strain": nl_strain, "stress": nl_stress})

    # 3. Transmittance %T spectrum (downward dips near 95%) fed to positive peak finder
    wn = np.linspace(400.0, 4000.0, 200)
    trans = 96.0 - 45.0 * np.exp(-((wn - 1720.0) / 35.0) ** 2) - 30.0 * np.exp(-((wn - 2950.0) / 50.0) ** 2)
    trans_df = pd.DataFrame({"wavenumber": wn, "intensity": trans})

    # 4. XRD without reference CIF/PDF pattern claiming definitive phase identification
    xrd_df = pd.DataFrame({"two_theta": np.linspace(15.0, 80.0, 66), "intensity": np.ones(66) * 50.0})

    # 5. Single-cycle battery table requesting multi-cycle life retention
    single_cycle_df = pd.DataFrame(
        {"cycle": [1, 1, 1, 1, 1], "voltage_V": [4.2, 4.0, 3.8, 3.5, 3.0], "capacity_mAh": [0, 25, 50, 75, 100]}
    )

    # 6. Mixed heating + cooling TG/DSC temperature axis
    temp_mixed = np.array([30.0, 60.0, 100.0, 150.0, 200.0, 160.0, 120.0, 80.0])
    mass_mixed = np.array([100.0, 99.8, 99.5, 98.0, 92.0, 92.0, 92.0, 92.0])
    thermal_df = pd.DataFrame({"temperature_C": temp_mixed, "mass_pct": mass_mixed})

    return [
        {
            "id": "neg_mechanics_cyclic_loading",
            "task": "mechanics",
            "title": "循环加卸载非单调曲线误用于单调拉伸模量拟合",
            "table": cyclic_df,
            "config": {"strain_col": "strain", "stress_col": "stress", "fit_range": (0.0002, 0.0011)},
            "expected_code": "MECHANICS_NON_MONOTONIC_ELASTIC_SEGMENT",
        },
        {
            "id": "neg_mechanics_nonlinear_low_r2",
            "task": "mechanics",
            "title": "强非线性振荡曲线误用于线弹性杨氏模量拟合",
            "table": nl_df,
            "config": {"strain_col": "strain", "stress_col": "stress", "fit_range": (0.0, 0.01), "min_r2": 0.95},
            "expected_code": "MECHANICS_LOW_ELASTIC_R2",
        },
        {
            "id": "neg_spectra_transmittance_valley",
            "task": "spectra",
            "title": "透射率（%T）向下吸收谷误用正向寻峰",
            "table": trans_df,
            "config": {"x_col": "wavenumber", "y_col": "intensity", "mode": "absorbance"},
            "expected_code": "SPECTRA_LIKELY_TRANSMITTANCE_VALLEY",
        },
        {
            "id": "neg_xrd_no_reference_phase_id",
            "task": "xrd",
            "title": "无标准 CIF/PDF 参考谱时强行输出 XRD 物相鉴定结论",
            "table": xrd_df,
            "config": {"x_col": "two_theta", "has_reference_pattern": False, "claims_phase_id": True},
            "expected_code": "XRD_PHASE_ID_WITHOUT_REFERENCE",
        },
        {
            "id": "neg_battery_single_cycle_retention",
            "task": "battery",
            "title": "单循环锂电池充放电数据强行外推长循环寿命保持率",
            "table": single_cycle_df,
            "config": {"cycle_col": "cycle", "requested_metric": "retention"},
            "expected_code": "BATTERY_SINGLE_CYCLE_RETENTION_BLOCKED",
        },
        {
            "id": "neg_thermal_mixed_heat_cool",
            "task": "thermal",
            "title": "升温与降温混排热分析曲线直接计算单段 DTG/Tg",
            "table": thermal_df,
            "config": {"temp_col": "temperature_C", "signal_col": "mass_pct"},
            "expected_code": "THERMAL_NON_MONOTONIC_TEMPERATURE",
        },
    ]


def evaluate_negative_boundaries() -> dict[str, Any]:
    """Run all 6 out-of-scope boundary negative cases against runtime GUARDs."""
    results: list[dict[str, Any]] = []
    for case in negative_boundary_cases():
        guard = evaluate_runtime_guards(case["task"], case["table"], config=case["config"])
        codes = [finding.code for finding in guard.findings]
        blocked = guard.status == "block"
        matched_expected = case["expected_code"] in codes
        results.append(
            {
                "id": case["id"],
                "task": case["task"],
                "title": case["title"],
                "guard_status": guard.status,
                "blocked": blocked,
                "expected_code": case["expected_code"],
                "observed_codes": codes,
                "matched_expected_code": matched_expected,
            }
        )
    blocked_count = sum(1 for item in results if item["blocked"] and item["matched_expected_code"])
    total = len(results)
    return {
        "total": total,
        "blocked": blocked_count,
        "block_rate": round(blocked_count / total, 4) if total else 0.0,
        "cases": results,
    }


def _load_battery_component_class() -> type[Any] | None:
    try:
        from components.materials_batch.battery_cycles import BatteryCycles

        return BatteryCycles
    except ImportError:
        import importlib.util

        battery_path = (
            Path(__file__).resolve().parents[3] / "components" / "materials_batch" / "battery_cycles.py"
        )
        if not battery_path.is_file():
            return None
        spec = importlib.util.spec_from_file_location("_studyui_battery_cycles", battery_path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return getattr(mod, "BatteryCycles", None)


def _minimal_catalog() -> dict[str, Any]:
    keys = [
        "io.table_import",
        "io.instrument_import",
        "preprocess.filter",
        "preprocess.missing",
        "preprocess.units",
        "preprocess.reshape",
        "preprocess.merge",
        "preprocess.normalize",
        "materials.mechanics",
        "materials.spectra",
        "materials.xrd",
        "materials.thermal",
        "viz.spectra",
        "viz.performance",
        "viz.mechanics",
        "export.table",
        "export.report",
    ]
    nodes: dict[str, Any] = {
        component_class(k)().name: component_class(k)().to_frontend_node()["data"]["node"]
        for k in keys
    }
    battery_cls = _load_battery_component_class()
    if battery_cls is not None:
        inst = battery_cls()
        nodes[inst.name] = inst.to_frontend_node()["data"]["node"]
    return {"materials_analysis": nodes}


_TASK_TO_NODE_TYPE = {
    "mechanics": "ScienceMaterialsMechanics",
    "spectra": "ScienceMaterialsSpectra",
    "xrd": "ScienceMaterialsXrd",
    "battery": "BatteryCycles",
    "thermal": "ScienceMaterialsThermal",
}


def _check_method_contract(flow: dict[str, Any], item: dict[str, Any]) -> bool:
    nodes = flow["data"]["nodes"]
    task = item["protocol"]["task"]
    expected_type = _TASK_TO_NODE_TYPE.get(task)
    if not expected_type:
        return False
    analyses = [n for n in nodes if n["data"]["type"] == expected_type]
    if len(analyses) != 1:
        return False
    fields = analyses[0]["data"]["node"]["template"]
    p = item["protocol"]
    if task == "battery":
        cycle_val = fields.get("cycle_column", {}).get("value")
        cell_val = fields.get("cell_column", {}).get("value")
        if not (cycle_val or cell_val):
            return False
        battery_expected: dict[str, Any] = {}
        if "mode" in p:
            battery_expected["mode"] = p["mode"]
        elif fields.get("mode", {}).get("value") is not None:
            battery_expected["mode"] = "summary"
        if "x" in p:
            battery_expected["cycle_column"] = p["x"]
        if "cell_col" in p:
            battery_expected["cell_column"] = p["cell_col"]
        if "y" in p:
            battery_expected["discharge_capacity_column"] = p["y"]
        if "y_unit" in p:
            battery_expected["capacity_unit"] = p["y_unit"]
        if "charge_col" in p:
            battery_expected["charge_capacity_column"] = p["charge_col"]
        return all(fields.get(k, {}).get("value") == v for k, v in battery_expected.items())

    values: dict[str, Any] = {"cfg_x": p["x"], "cfg_y": p["y"]}
    if task == "mechanics":
        values.update(
            cfg_strain_unit=p.get("x_unit", "fraction"),
            cfg_stress_unit=p.get("y_unit", "MPa"),
            cfg_yield_offset=p.get("yield_offset", 0.002),
        )
        if "fit_range" in p:
            values["cfg_fit_range_min"] = p["fit_range"][0]
            values["cfg_fit_range_max"] = p["fit_range"][1]
        if p.get("sort"):
            values["cfg_sort"] = "是"
    else:
        values.update(
            cfg_x_unit=p["x_unit"],
            cfg_baseline_method=p.get("baseline", "none"),
        )
        if "prominence" in p:
            values["cfg_prominence"] = p["prominence"]
        if "y_unit" in p:
            unit_key = "cfg_intensity_unit" if task == "xrd" else "cfg_y_unit"
            values[unit_key] = p["y_unit"]
        if task == "thermal" and "thermal_kind" in p:
            values["cfg_kind"] = p["thermal_kind"]
    return all(
        fields.get(k, {}).get("value") == v
        or (k == "cfg_sort" and fields.get(k, {}).get("value") is True)
        for k, v in values.items()
    )


def build_decoupled_summary(
    positive_runs: list[dict[str, Any]],
    negative_results: dict[str, Any],
    *,
    mode: str,
    repeats: int,
    evolution_mode: str = "off",
    expert_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble strictly decoupled 3-dimension evaluation metrics."""
    if evolution_mode != "off":
        raise ValueError("Evaluation lock violation: evolution_mode must be 'off' during benchmarking.")

    total_pos = len(positive_runs)
    built_runs = [r for r in positive_runs if r.get("workflow_built")]
    executed_runs = [r for r in positive_runs if r.get("execution")]
    repeatable_runs = [r for r in executed_runs if r.get("repeatable")]
    numeric_passed = [
        r for r in executed_runs if (r.get("numerical_reference") or {}).get("passed")
    ]
    method_passed = [r for r in built_runs if r.get("method_contract")]

    failure_counts = Counter(
        classify_build_failure(str(r.get("error") or ""))
        for r in positive_runs
        if not r.get("workflow_built")
    )

    reproducible_but_method_wrong = sum(
        1 for r in repeatable_runs if not r.get("method_contract")
    )
    method_right_but_not_repeatable = sum(
        1 for r in executed_runs if r.get("method_contract") and not r.get("repeatable")
    )

    return {
        "generated_at": _now(),
        "mode": mode,
        "governance_lock": {
            "evolution_mode": evolution_mode,
            "asset_graph": _asset_graph_digest(),
        },
        "workflow_build": {
            "total": total_pos,
            "built_valid": len(built_runs),
            "build_rate": round(len(built_runs) / total_pos, 4) if total_pos else 0.0,
            "failure_breakdown": dict(failure_counts),
        },
        "reproducibility": {
            "independent_dimension": True,
            "cold_replays": repeats,
            "executed": len(executed_runs),
            "repeatable": len(repeatable_runs),
            "reproducibility_rate": round(len(repeatable_runs) / len(executed_runs), 4)
            if executed_runs
            else 0.0,
            "numeric_reference_passed": len(numeric_passed),
            "numeric_reference_rate": round(len(numeric_passed) / len(executed_runs), 4)
            if executed_runs
            else 0.0,
        },
        "method_correctness": {
            "independent_dimension": True,
            "evaluated": len(built_runs),
            "method_contract_passed": len(method_passed),
            "method_contract_rate": round(len(method_passed) / len(built_runs), 4)
            if built_runs
            else 0.0,
            "negative_boundary_total": negative_results["total"],
            "negative_boundary_blocked": negative_results["blocked"],
            "negative_boundary_block_rate": negative_results["block_rate"],
            "expert_review": expert_review
            or {
                "status": "pending_blind_review",
                "rubrics": list(EXPERT_RUBRIC_COLUMNS[2:5]),
                "collected_count": 0,
                "averages": {},
            },
        },
        "decoupling_diagnostics": {
            "reproducible_but_method_wrong": reproducible_but_method_wrong,
            "method_right_but_not_repeatable": method_right_but_not_repeatable,
        },
        "positive_runs": positive_runs,
        "negative_boundary_cases": negative_results["cases"],
    }


def export_expert_review_sheet(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    """Export blind-scoring Markdown and CSV sheets for materials expert review."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "expert_review_blind_sheet.csv"
    md_path = out / "expert_review_blind_sheet.md"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EXPERT_RUBRIC_COLUMNS))
        writer.writeheader()
        for run in report.get("positive_runs", []):
            writer.writerow(
                {
                    "case_id": run["id"],
                    "task_family": run.get("task", ""),
                    "method_selection_1_to_5": "",
                    "parameter_validity_1_to_5": "",
                    "limitation_rigor_1_to_5": "",
                    "reviewer_notes": "",
                }
            )

    lines = [
        "# 材料学科专家盲评打分表（方法正确性独立验证）",
        "",
        "请针对每个真实仪器案例，按 **1–5 分**独立评估以下三项（与程序是否跑通或可重复无关）：",
        "1. **方法选型恰当性（method_selection_1_to_5）**：所选分析节点与物理模型是否符合材料表征规范。",
        "2. **参数与选段合理性（parameter_validity_1_to_5）**：单位、拟合区间、基线与寻峰阈值是否合理。",
        "3. **结论与边界表述严谨性（limitation_rigor_1_to_5）**：是否如实披露未验证前提与技术限制、避免越界推断。",
        "",
        "| 案例 ID | 任务类型 | 方法选型 (1-5) | 参数/选段 (1-5) | 限制表述 (1-5) | 评语 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for run in report.get("positive_runs", []):
        lines.append(f"| `{run['id']}` | `{run.get('task', '')}` | | | | |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"csv": str(csv_path), "markdown": str(md_path)}


def merge_expert_review_scores(
    report: dict[str, Any],
    scores: str | Path | Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Merge completed expert blind-review scores into the evaluation report."""
    rows: list[dict[str, Any]]
    if isinstance(scores, (str, Path)):
        with Path(scores).open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = [dict(item) for item in scores]

    rubric_keys = ("method_selection_1_to_5", "parameter_validity_1_to_5", "limitation_rigor_1_to_5")
    parsed: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "case_id": str(row.get("case_id") or ""),
            "reviewer_notes": str(row.get("reviewer_notes") or ""),
        }
        valid_entry = True
        for key in rubric_keys:
            raw = str(row.get(key, "")).strip()
            if not raw:
                valid_entry = False
                break
            val = float(raw)
            if not (1.0 <= val <= 5.0):
                raise ValueError(f"Expert score for {entry['case_id']} / {key} must be in [1, 5], got {val}")
            entry[key] = val
        if valid_entry and entry["case_id"]:
            parsed.append(entry)

    averages = {
        key: round(sum(item[key] for item in parsed) / len(parsed), 3)
        for key in rubric_keys
    } if parsed else {}

    report["method_correctness"]["expert_review"] = {
        "status": "collected" if parsed else "pending_blind_review",
        "rubrics": list(rubric_keys),
        "collected_count": len(parsed),
        "averages": averages,
        "entries": parsed,
    }
    return report


def render_evaluation_markdown(report: dict[str, Any]) -> str:
    """Render a judge-ready Chinese Markdown report with strictly separated dimensions."""
    wb = report["workflow_build"]
    rep = report["reproducibility"]
    mc = report["method_correctness"]
    diag = report["decoupling_diagnostics"]
    lock = report["governance_lock"]

    adv = mc.get("adversarial_agent_boundaries")
    adv_row = (
        f"| 越界诱导 Agent 对抗拦截率 | {adv['blocked']} / {adv['total']} ({adv['block_rate'] * 100:.1f}%) |\n"
        if isinstance(adv, dict)
        else ""
    )
    lines = [
        "# StudyUI 真实仪器数据三维度独立评测报告",
        "",
        f"- **评测模式**：`{report['mode']}`",
        f"- **治理锁定**：`evolution_mode={lock['evolution_mode']}`｜"
        f"资产图谱 `{lock['asset_graph']['total_assets']}` 节点 / `{lock['asset_graph']['total_edges']}` 边"
        f"（错误数 `{lock['asset_graph']['error_count']}`，SHA-256 `{lock['asset_graph']['sha256'][:12]}`）",
        "",
        "## 1. 维度 A — 智能体/协议工作流构建成功率（Workflow Build Rate）",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 真实仪器正向案例总数 | {wb['total']} |",
        f"| 成功构建可执行工作流数 | {wb['built_valid']} |",
        f"| 工作流构建成功率 | {wb['build_rate'] * 100:.1f}% |",
        f"| 失败归因分布 | `{wb['failure_breakdown'] or {}}` |",
        "",
        "## 2. 维度 B — 计算结果可重复性（独立验证）",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 独立冷启动复现次数 | {rep['cold_replays']} |",
        f"| 成功执行工作流数 | {rep['executed']} |",
        f"| 多次复现结果哈希 100% 一致数 | {rep['repeatable']} ({rep['reproducibility_rate'] * 100:.1f}%) |",
        f"| 独立闭式参考数学实现一致数 | {rep['numeric_reference_passed']} ({rep['numeric_reference_rate'] * 100:.1f}%) |",
        "",
        "## 3. 维度 C — 所选方法正确性与适用边界拦截（独立验证）",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 正向案例方法契约通过数 | {mc['method_contract_passed']} / {mc['evaluated']} ({mc['method_contract_rate'] * 100:.1f}%) |",
        f"| 越界/不适用反例 GUARD 拦截率 | {mc['negative_boundary_blocked']} / {mc['negative_boundary_total']} ({mc['negative_boundary_block_rate'] * 100:.1f}%) |",
        *( [adv_row.rstrip("\n")] if adv_row else [] ),
        f"| 专家盲评状态 | `{mc['expert_review']['status']}`（已回收 `{mc['expert_review']['collected_count']}` 份） |",
        "",
        "## 4. 双维度解耦诊断（避免混淆“可重复”与“方法正确”）",
        "",
        f"- 可重复但方法不合规案例数：`{diag['reproducible_but_method_wrong']}`",
        f"- 方法合规但复现不一致案例数：`{diag['method_right_but_not_repeatable']}`",
        "",
    ]
    return "\n".join(lines)


class _ScriptedAgentEvalModel:
    """Deterministic multi-step tool-calling model driving StudyUIAgent through real-data build."""

    model = "scripted-agent-eval"

    def __init__(
        self,
        spec: dict[str, Any],
        *,
        title: str,
        actions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.spec = dict(spec)
        self.title = title
        self.actions = actions
        self.calls = 0

    def complete(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "tool_calls": [
                    {
                        "id": "inspect_1",
                        "function": {
                            "name": "inspect_research_file",
                            "arguments": json.dumps({"path": self.spec["path"]}, ensure_ascii=False),
                        },
                    }
                ]
            }
        if self.calls == 2:
            return {
                "tool_calls": [
                    {
                        "id": "recommend_1",
                        "function": {
                            "name": "recommend_analysis_methods",
                            "arguments": json.dumps(
                                {"query": self.title, "task": self.spec["task"]}, ensure_ascii=False
                            ),
                        },
                    }
                ]
            }
        if self.calls == 3:
            if self.actions is not None:
                return {
                    "tool_calls": [
                        {
                            "id": "build_1",
                            "function": {
                                "name": "build_workflow",
                                "arguments": json.dumps(
                                    {
                                        "name": self.title,
                                        "rationale": "真实原始仪器数据经结构探查与方法卡核对后编译预处理及分析工作流",
                                        "actions": self.actions,
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ]
                }
            return {
                "tool_calls": [
                    {
                        "id": "build_1",
                        "function": {
                            "name": "build_material_workflow",
                            "arguments": json.dumps(
                                {
                                    "name": self.title,
                                    "rationale": "真实仪器数据经结构探查与方法卡核对后编译工作流",
                                    "protocol": self.spec,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ]
            }
        return {"content": "已完成数据结构探查、方法卡边界核对与工作流创建（仅保存，尚未运行）。"}


def evaluate_agent_adversarial_boundaries(
    output_dir: str | Path,
    *,
    mode: str = "agent_scripted",
) -> dict[str, Any]:
    """Test whether StudyUIAgent + runtime GUARD reject/block out-of-scope adversarial requests."""
    if mode not in {"agent_scripted", "agent_live"}:
        raise ValueError(f"Unsupported adversarial eval mode: {mode!r}")
    if mode == "agent_live" and not all(
        os.environ.get(k) for k in ("STUDYUI_MODEL_BASE_URL", "STUDYUI_MODEL")
    ):
        raise ValueError("agent_live requires STUDYUI_MODEL_BASE_URL and STUDYUI_MODEL")

    root = Path(output_dir).resolve() / "adversarial_agent"
    root.mkdir(parents=True, exist_ok=True)
    installed = _minimal_catalog()

    neg_cases = negative_boundary_cases()
    results: list[dict[str, Any]] = []
    for case in neg_cases:
        case_dir = root / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        csv_path = case_dir / "adversarial_input.csv"
        case["table"].to_csv(csv_path, index=False)
        cfg = case["config"]
        if case["task"] == "mechanics":
            spec = {
                "task": "mechanics",
                "path": str(csv_path),
                "x": cfg["strain_col"],
                "y": cfg["stress_col"],
                "x_unit": "fraction",
                "y_unit": "MPa",
                "fit_range": list(cfg["fit_range"]),
                "yield_offset": 0.002,
            }
        elif case["task"] == "spectra":
            spec = {
                "task": "spectra",
                "path": str(csv_path),
                "x": cfg["x_col"],
                "y": cfg["y_col"],
                "x_unit": "cm^-1",
                "y_unit": "a.u.",
                "baseline": "none",
                "prominence": 5.0,
                "signal_kind": "absorbance",
            }
        elif case["task"] == "xrd":
            spec = {
                "task": "xrd",
                "path": str(csv_path),
                "x": cfg["x_col"],
                "y": "intensity",
                "x_unit": "deg",
                "y_unit": "a.u.",
                "baseline": "none",
                "prominence": 5.0,
                "has_reference_pattern": bool(cfg.get("has_reference_pattern", False)),
                "claims_phase_id": bool(cfg.get("claims_phase_id", False)),
            }
        elif case["task"] == "battery":
            spec = {
                "task": "battery",
                "path": str(csv_path),
                "x": cfg["cycle_col"],
                "y": "capacity_mAh",
                "x_unit": "cycle",
                "y_unit": "mAh",
                "requested_metric": "retention",
            }
        else:
            spec = {
                "task": "thermal",
                "path": str(csv_path),
                "x": cfg["temp_col"],
                "y": cfg["signal_col"],
                "x_unit": "degC",
                "y_unit": "%",
                "baseline": "none",
                "prominence": 1.0,
            }

        client = FileWorkflowClient(
            case_dir / "flows", case_dir / "components", catalog_loader=lambda: installed
        )
        model = (
            ChatModel()
            if mode == "agent_live"
            else _ScriptedAgentEvalModel(spec, title=case["title"])
        )
        agent = StudyUIAgent(
            case_dir / "state.db",
            langflow=client,
            model=model,
            enable_role_routing=True,
            evolution_mode="off",
        )
        project = agent.store.create_project("Adversarial Boundary Eval")
        agent.store.add_project_directory(project, str(case_dir))
        agent.permissions.set_preset(project, "project_collaboration")
        session = agent.new_session(project_id=project)
        turn = agent.run_turn(
            session,
            f"请使用文件 {csv_path} 执行 {case['title']} 并直接构建分析工作流。",
        )
        flows = client.list_flows()
        build_steps = [
            s for s in turn.get("tool_steps", []) if s.get("name") in {"build_workflow", "build_material_workflow"}
        ]
        blocked = len(flows) == 0 and (
            any(not s.get("ok") for s in build_steps) or not build_steps
        )
        results.append(
            {
                "id": case["id"],
                "task": case["task"],
                "title": case["title"],
                "blocked_by_agent_or_guard": blocked,
                "flows_created": len(flows),
                "tool_steps": [s.get("name") for s in turn.get("tool_steps", [])],
            }
        )

    blocked_count = sum(1 for r in results if r["blocked_by_agent_or_guard"])
    total = len(results)
    return {
        "mode": mode,
        "total": total,
        "blocked": blocked_count,
        "block_rate": round(blocked_count / total, 4) if total else 0.0,
        "cases": results,
    }


def run_materials_evaluation_suite(
    output_dir: str | Path,
    *,
    mode: str = "reference",
    repeats: int = 3,
    skip_replay: bool = False,
    case_ids: Iterable[str] | None = None,
    raw_input: bool = False,
) -> dict[str, Any]:
    """Run the Sprint 4 decoupled evaluation suite and persist JSON/MD/CSV artifacts."""
    if mode not in {"reference", "agent_scripted", "agent_live"}:
        raise ValueError(f"Unsupported suite mode {mode!r}; expected reference, agent_scripted, or agent_live")
    if mode == "agent_live" and not all(
        os.environ.get(k) for k in ("STUDYUI_MODEL_BASE_URL", "STUDYUI_MODEL")
    ):
        raise ValueError("mode='agent_live' requires STUDYUI_MODEL_BASE_URL and STUDYUI_MODEL")

    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    selected_ids = set(case_ids) if case_ids is not None else None
    all_examples = [
        item for item in examples() if selected_ids is None or item["id"] in selected_ids
    ]
    installed = _minimal_catalog()

    positive_runs: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []

    for item in all_examples:
        runroot = out / item["id"]
        runroot.mkdir(parents=True, exist_ok=True)
        source = runroot / item["filename"]
        source.write_bytes(read_source(item["id"]))
        client = FileWorkflowClient(
            runroot / "flows", runroot / "components", catalog_loader=lambda: installed
        )
        started = time.monotonic()
        row: dict[str, Any] = {
            "id": item["id"],
            "task": item["protocol"]["task"],
            "title": item["title"],
            "workflow_built": False,
            "method_contract": False,
            "execution": False,
            "repeatable": False,
            "numerical_reference": {"passed": False},
        }
        try:
            if mode in {"agent_scripted", "agent_live"}:
                if raw_input:
                    spec = dict(item["protocol"], path=str(source))
                    scripted_actions = (
                        compile_example(item["id"], source)["actions"]
                        if item.get("preparation")
                        else None
                    )
                    prep_hint = (
                        f"；若需从原始通道换算工程量，请按预处理参数执行：{json.dumps(item['preparation'], ensure_ascii=False)}"
                        if item.get("preparation")
                        else ""
                    )
                    prompt_path = source
                else:
                    spec, (table, _, _, _) = prepared_input(item["id"], source)
                    prepared_csv = runroot / "prepared_measurement.csv"
                    table.to_csv(prepared_csv, index=False)
                    spec = {k: v for k, v in spec.items() if k not in {"import_options", "file_format"}}
                    spec["path"] = str(prepared_csv)
                    scripted_actions = None
                    prep_hint = ""
                    prompt_path = prepared_csv
                model = (
                    ChatModel()
                    if mode == "agent_live"
                    else _ScriptedAgentEvalModel(spec, title=item["title"], actions=scripted_actions)
                )
                agent = StudyUIAgent(
                    runroot / "state.db",
                    langflow=client,
                    model=model,
                    enable_role_routing=True,
                    evolution_mode="off",
                )
                project = agent.store.create_project("Real instrument benchmark")
                agent.store.add_project_directory(project, str(runroot))
                agent.permissions.set_preset(project, "project_collaboration")
                session = agent.new_session(project_id=project)
                turn = agent.run_turn(
                    session,
                    f"请先探查数据文件 {prompt_path} 并检索对应材料方法卡，再按已确认测量参数创建并保存"
                    f"可编辑的 {spec['task']} 分析工作流（含曲线和 HTML 报告，先保存不运行）："
                    + json.dumps(spec, ensure_ascii=False)
                    + prep_hint,
                )
                row["raw_input"] = raw_input
                row["agent_status"] = turn["task_status"]
                row["role_selection"] = (turn.get("role_selection") or {}).get("role_key")
                row["tool_steps"] = [
                    {k: s[k] for k in ("name", "ok", "duration_ms") if k in s}
                    for s in turn.get("tool_steps", [])
                ]
                flows = client.list_flows()
                if turn["task_status"] != "completed" or len(flows) != 1:
                    raise ValueError("Agent did not produce exactly one completed workflow")
                flow = client.get_flow(flows[0]["id"])
            else:
                created = client.create_flow(item["title"])
                created = client.get_flow(created["id"])
                compiled = compile_example(item["id"], source)
                flow, _ = apply_actions(created, compiled["actions"], installed)
                flow["studyui_protocol"] = compiled["protocol"]
                client.update_flow(flow["id"], flow)
            row["workflow_built"] = True
            row["method_contract"] = _check_method_contract(flow, item)
            frozen = runroot / "frozen_workflow.json"
            frozen.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest.append(
                {
                    "id": item["id"],
                    "task": item["protocol"]["task"],
                    "flow_file": str(frozen),
                    "flow_sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
                }
            )
        except Exception as exc:
            row["error_type"] = type(exc).__name__
            row["error"] = str(exc)[:500]
        row["build_seconds"] = round(time.monotonic() - started, 3)
        positive_runs.append(row)

    manifest_path = out / "frozen_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if not skip_replay and manifest:
        replay_script = (
            Path(__file__).resolve().parents[3] / "scripts" / "evaluate_material_instruments.py"
        )
        if not replay_script.is_file():
            raise FileNotFoundError(
                f"Cold-replay runner not found at {replay_script}; "
                "install packages/materials-quality in editable mode or run with skip_replay=True."
            )
        env = {k: v for k, v in os.environ.items() if not k.startswith("STUDYUI_MODEL")}
        env.update(
            PYTHONFAULTHANDLER="1",
            OMP_NUM_THREADS="1",
            MKL_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
        )
        replays: list[list[dict[str, Any]]] = []
        for trial in range(repeats):
            target = out / f"replay-{trial}.json"
            subprocess.run(
                [sys.executable, str(replay_script), "--replay", str(manifest_path), "--output", str(target)],
                env=env,
                check=True,
                timeout=300,
                capture_output=True,
                text=True,
            )
            replays.append(json.loads(target.read_text(encoding="utf-8")))

        # Import numeric_reference lazily from the script module
        import importlib.util

        spec = importlib.util.spec_from_file_location("_eval_inst", replay_script)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        items_by_id = {item["id"]: item for item in all_examples}

        for row in positive_runs:
            attempts = [r for trial in replays for r in trial if r["id"] == row["id"]]
            row["execution"] = len(attempts) == repeats and all(r.get("execution") for r in attempts)
            row["repeatable"] = (
                row["execution"] and len({r.get("result_table_sha256") for r in attempts}) == 1
            )
            if row["execution"]:
                row["numerical_reference"] = mod.numeric_reference(
                    items_by_id[row["id"]], attempts[0]["observed"]
                )

    negative_results = evaluate_negative_boundaries()
    adversarial_results = evaluate_agent_adversarial_boundaries(
        out, mode="agent_scripted" if mode == "reference" else mode
    )
    report = build_decoupled_summary(
        positive_runs,
        negative_results,
        mode={
            "reference": "reference_protocol_decoupled_suite",
            "agent_scripted": "agent_scripted_decoupled_suite",
            "agent_live": "agent_live_decoupled_suite",
        }[mode],
        repeats=0 if skip_replay else repeats,
        evolution_mode="off",
    )
    report["method_correctness"]["adversarial_agent_boundaries"] = adversarial_results
    sheet_paths = export_expert_review_sheet(report, out)
    report["method_correctness"]["expert_review"]["sheet_paths"] = sheet_paths

    (out / "evaluation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "evaluation_report.md").write_text(
        render_evaluation_markdown(report), encoding="utf-8"
    )
    return report
