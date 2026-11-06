"""A small visual task plan with separate raw and processed summary branches."""

from materials_quality.common import json_value

from .analysis_plan import AnalysisPlanRunner
from .contracts import NodeResult


def plan_steps(c):
    """Editable high-level settings, never arbitrary code or JSON steps."""
    task = c.get("task", "group_summary")
    if task == "group_summary":
        summary = {"group_by": c.get("group_by", ["group"]), "columns": c.get("columns", ["value"])}
        return [
            {"id": "raw_summary", "operation": "stats.grouped", "config": summary},
            {
                "id": "normalize",
                "operation": "preprocess.normalize",
                "config": {
                    "method": c.get("normalization", "zscore"),
                    "columns": summary["columns"],
                    "group_by": c.get("normalize_by", []),
                },
            },
            {
                "id": "processed_summary",
                "operation": "stats.grouped",
                "config": summary,
                "dependencies": ["normalize"],
            },
        ]
    if task == "spectra":
        return [
            {
                "id": "curves",
                "operation": "materials.batch_spectra",
                "config": {
                    "curve_id": c.get("curve_id", "curve_id"),
                    "x": c.get("x", "x"),
                    "y": c.get("y", "y"),
                    "group": c.get("group", "group"),
                    "x_unit": c.get("x_unit"),
                    "intensity_unit": c.get("y_unit"),
                    "baseline": {"method": c.get("baseline", "none")},
                    "prominence": c.get("prominence", 0.1),
                    "prominence_mode": "absolute",
                },
            },
            {
                "id": "primary",
                "operation": "preprocess.filter",
                "dependencies": ["curves"],
                "source_output": "features",
                "config": {
                    "conditions": [{"column": "is_primary", "op": "eq", "value": True}],
                },
            },
            {
                "id": "peak_summary",
                "operation": "stats.grouped",
                "dependencies": ["primary"],
                "config": {"group_by": ["group"], "columns": ["peak_position"]},
            },
        ]
    raise ValueError("task must be spectra or group_summary")


def run_research_plan(table, config=None, previous=None):
    c = dict(config or {})
    steps = plan_steps(c)
    run = AnalysisPlanRunner(max_executions=8).run(steps, {"input": table}, previous=previous)
    records = run.records
    terminal = records[steps[-1]["id"]]
    result = terminal.result if terminal.status in {"success", "reused"} else None
    diagnostics = [
        {key: value for key, value in vars(record).items() if key not in {"result", "_signature"}}
        for record in records.values()
    ]
    warnings = ["统计按曲线或输入行描述；不自动将技术重复认定为独立试验单位。"]
    for name, record in records.items():
        if record.result is not None:
            warnings.extend(f"{name}: {warning}" for warning in record.result.warnings)
    if result is None:
        warnings.append("目标步骤未完成，请查看步骤诊断后修改参数；原始表未修改。")
    features = None
    if "curves" in records and records["curves"].result is not None:
        features = records["curves"].result.features
    elif result is not None:
        features = result.table
    # The status table is useful even when no scientific result exists.
    import pandas as pd

    status_table = pd.DataFrame(
        [{"step": key, "status": value.status, "reason": value.reason} for key, value in records.items()]
    )
    output = NodeResult(
        table=result.table if result is not None and result.table is not None else status_table,
        features=features,
        data={
            "execution_status": "completed" if run.status == "success" else run.status,
            "task": c.get("task", "group_summary"),
            "steps": diagnostics,
            "execution_count": run.execution_count,
            "reuse_count": run.reuse_count,
            "intermediate_results": {
                name: {
                    "row_count": len(record.result.table),
                    "rows": json_value(record.result.table.head(200).to_dict("records")),
                    "units": record.result.table.attrs.get("units", {}),
                    "omitted_rows": max(0, len(record.result.table) - 200),
                }
                for name, record in records.items()
                if record.result is not None and record.result.table is not None
            },
            "automatic_repair": False,
            "retry_scope": "same live component instance or explicit Python AnalysisRun",
            "scientific_validation": "not_established_by_execution_success",
        },
        warnings=warnings + ([] if result is None else result.warnings),
    )
    return output, run


def research_plan(table=None, *, config=None, data=None, tables=None):
    return run_research_plan(table, config)[0]


CATALOG = [
    {
        "key": "materials.analysis_plan",
        "title": "分步分析与局部重算",
        "function": "materials_quality.science.research_plan:research_plan",
        "category": "材料专业分析",
        "requirement": "有界纯计算任务图",
        "default_config": {"task": "group_summary", "group_by": ["group"], "columns": ["value"]},
        "table_input": True,
        "data_input": False,
        "tables_input": False,
    }
]
