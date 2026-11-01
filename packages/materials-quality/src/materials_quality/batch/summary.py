"""Collect one row per specimen, including failures, and a standalone HTML report."""

import base64
import html
import json
from pathlib import Path

import pandas as pd

from materials_quality.common import json_value
from materials_quality.science.contracts import NodeResult, artifact_path

from .packet import unpack_table, validate_batch


def summarize_batch(packet, config=None):
    validate_batch(packet)
    rows, files, peaks = [], [], []
    for item in packet["items"]:
        row = {
            "batch_item_id": item["id"],
            "batch_label": item["label"],
            "status": item["status"],
            "needs_review": bool(item.get("needs_review")),
            "error": (item["error"] or {}).get("message", ""),
            "source_name": item["source"].get("source_name", ""),
            "source_sha256": item["source"].get("source_sha256", ""),
        }
        reserved = set(row)
        for report in [*item["history"], item["report"]]:
            if not isinstance(report, dict):
                continue
            for key, value in report.get("data", {}).items():
                if key in reserved:
                    continue
                if isinstance(value, (str, int, float, bool)) or value is None:
                    row[key] = value
            files.extend({"batch_item_id": item["id"], "path": path} for path in report.get("artifacts", []))
        if "quality" in item:
            row["quality_findings"] = item["quality"]["total_findings"]
            row["quality_checks"] = item["quality"]["metrics"]["completed_checks"]
        rows.append(row)
        if item.get("features") is not None:
            feature = unpack_table(item["features"])
            feature["batch_item_id"], feature["batch_label"] = item["id"], item["label"]
            peaks.append(feature)
    table = pd.DataFrame(rows)
    data = {
        "schema_version": "materials-batch-summary/1",
        "batch_id": packet["batch_id"],
        "counts": packet["counts"],
        "execution_status": packet["execution_status"],
        "files": files,
        "items": json_value(rows),
        "scope": "仅汇总已接入并执行的检查和分析。失败与跳过的样品保留在汇总表中。",
    }
    path = artifact_path(config, "batch-summary.html")
    payload = html.escape(json.dumps(json_value(packet), ensure_ascii=False, indent=2))
    figures = []
    for record in files:
        image = Path(record["path"])
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(image.suffix.lower())
        if mime and image.is_file():
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            figures.append(
                "<figure><img style='max-width:100%' src='data:"
                + mime
                + ";base64,"
                + encoded
                + "'><figcaption>"
                + html.escape(record["batch_item_id"] + " · " + image.name)
                + "</figcaption></figure>"
            )
    path.write_text(
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
        "<title>批量分析报告</title><style>body{font:15px system-ui;margin:32px}"
        "table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:6px}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"
        "<h1>批量分析报告</h1><p>"
        + html.escape(data["scope"])
        + "</p>"
        + table.to_html(index=False, escape=True)
        + "".join(figures)
        + "<details><summary>完整来源、参数与运行记录</summary><pre>"
        + payload
        + "</pre></details></html>",
        encoding="utf-8",
    )
    return NodeResult(
        table=table,
        data=data,
        artifacts=[str(path)],
        features=pd.concat(peaks, ignore_index=True) if peaks else None,
    )
