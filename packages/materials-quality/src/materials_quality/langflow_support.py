"""Native port definitions and shared adapter helpers for the seven components."""

import json

from lfx.io import DataFrameInput, DataInput, IntInput, Output
from lfx.schema import Data, DataFrame

from materials_quality.common import FINDING_COLUMNS
from materials_quality.context import run_check


def parse_json(value, name, expected_type):
    def reject_constant(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")

    try:
        result = json.loads(value, parse_constant=reject_constant)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: provide valid JSON ({exc})") from exc
    if not isinstance(result, expected_type):
        raise ValueError(f"{name}: expected a JSON {expected_type.__name__}")
    return result


def column_list(value, name="columns_json"):
    parsed = parse_json(value, name, list)
    if any(not isinstance(x, str) or not x.strip() for x in parsed):
        raise ValueError(f"{name}: column names must be non-empty strings")
    return parsed or None


def check_inputs(extra=None):
    return [
        DataFrameInput(
            name="input_table",
            display_name="输入表格",
            required=True,
            info="接入 Langflow Table/DataFrame；检查不修改原始数据。",
        ),
        DataInput(
            name="quality_context", display_name="共享规则与来源", required=False, value=None,
            info="可选：连接数据规则与追溯节点。连接后共享规则优先，忽略本节点独立规则。",
        ),
        *(extra or []),
        IntInput(
            name="finding_limit",
            display_name="问题明细上限",
            value=500,
            advanced=True,
            info="1–10000；限制明细预览，不影响完整计数和检查结论。",
        ),
    ]


def check_outputs():
    return [
        Output(name="table_out", display_name="原始表格", method="pass_table", group_outputs=True),
        Output(name="findings", display_name="问题明细", method="build_findings", group_outputs=True),
        Output(name="report", display_name="检查报告", method="build_report", group_outputs=True),
    ]


def report_data(node, check, **parameters):
    context = getattr(node, "quality_context", None)
    if context is not None and not isinstance(context, Data):
        raise ValueError("quality_context must be a native Langflow Data object")
    result = run_check(
        node.input_table, check.__name__.removeprefix("check_"), parameters=parameters,
        context=context.data if context is not None else None, finding_limit=node.finding_limit,
    )
    verdict = "未发现所检查的问题" if result["passed"] else "需要复核"
    node.status = f"检查完成；{verdict}；问题数 {result['total_findings']}"
    return Data(data=result)


def original_table(node):
    return DataFrame(node.input_table.copy(deep=True))


def findings_table(report):
    return DataFrame(report["findings"], columns=FINDING_COLUMNS)
