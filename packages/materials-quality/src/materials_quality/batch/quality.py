"""Apply one shared ruleset independently, without rewriting measurements."""

from copy import deepcopy

from materials_quality.aggregate import aggregate_reports
from materials_quality.context import make_context, run_check

from .packet import make_batch, unpack_table, validate_batch


def quality_batch(packet, rules, *, finding_limit=500, skip_on_issues=False):
    validate_batch(packet)
    if rules.get("checks", {}).get("units", {}).get("convert_values"):
        raise ValueError("批量质量检查不换算数据；请使用单位换算预处理节点。")
    items = []
    for original in packet["items"]:
        item = deepcopy(original)
        if item["status"] == "completed":
            try:
                if item["table"] is None:
                    raise ValueError("请先连接批量表格导入，再执行质量检查。")
                frame = unpack_table(item["table"])
                source = {
                    k: v
                    for k, v in item["source"].items()
                    if k in {"dataset_id", "source_name", "source_sha256"}
                }
                context = make_context(frame, rules, source=source)
                reports = [
                    run_check(frame, name, context=context, finding_limit=finding_limit)
                    for name in context["rules"]["checks"]
                ]
                item["quality"] = aggregate_reports(reports, finding_limit=finding_limit)
                item["needs_review"] = not item["quality"]["passed"]
                if skip_on_issues and item["needs_review"]:
                    item["status"] = "skipped"
                    item["skip_reason"] = "所选质量检查发现问题，按设置跳过后续分析。"
            except Exception as error:
                if packet["on_error"] == "stop":
                    raise ValueError(f"{item['label']}：{error}") from error
                item["status"] = "failed"
                item["error"] = {"stage": "batch.quality", "message": str(error)}
        items.append(item)
    output = make_batch(items, batch_id=packet["batch_id"], on_error=packet["on_error"])
    for key in ("artifacts", "rename_columns"):
        if key in packet:
            output[key] = deepcopy(packet[key])
    return output
