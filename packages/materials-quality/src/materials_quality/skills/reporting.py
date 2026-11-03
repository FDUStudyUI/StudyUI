"""Escaped, self-contained reports with original values and content-hashed exports."""

import base64
import hashlib
import html
import json
from pathlib import Path

from materials_quality.common import json_value


def write_json(path, value):
    text = json.dumps(json_value(value), ensure_ascii=False, indent=2, allow_nan=False)
    path.write_text(text, encoding="utf-8")
    if path.read_text(encoding="utf-8") != text:
        raise OSError("report readback mismatch")


def deliver(result, report, output, summary):
    paths = list(result.artifacts)
    sections = []
    labels = {
        "table": "逐样品/试验单位结果",
        "features": "结构化特征与检验",
        "curves": "处理后曲线",
        "groups": "分组描述统计",
    }
    for name, label in labels.items():
        table = getattr(result, name)
        if not len(table.columns):
            continue
        path = output / f"{name}.csv"
        table.to_csv(path, index=False, encoding="utf-8-sig")
        paths.append(str(path))
        sections.append(
            f"<h2>{label}（{len(table)} 行，预览前 20 行）</h2>"
            + table.head(20).to_html(index=False, escape=True, border=0)
        )
    images = []
    for path in result.artifacts:
        if Path(path).suffix == ".png":
            encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            images.append(f'<figure><img alt="分析图件" src="data:image/png;base64,{encoded}"></figure>')
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>StudyUI 科研分析报告</title>'
    document += (
        "<style>body{max-width:1100px;margin:36px auto;padding:0 20px;font:16px/1.6 system-ui;"
        "color:#243642}table{border-collapse:collapse;display:block;overflow:auto}td,th{padding:6px;"
        "border-bottom:1px solid #ccd7db}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        "img{max-width:100%}h1,h2{color:#1d607b}</style><body><h1>StudyUI 科研分析报告</h1>"
    )
    document += f"<p>{html.escape(summary)}</p><h2>警告与适用范围</h2><ul>"
    document += "".join(f"<li>{html.escape(str(w))}</li>" for w in report["warnings"]) + "</ul>"
    document += "".join(sections + images)
    document += (
        "<h2>方法、参数与来源</h2><pre>"
        + html.escape(json.dumps(json_value(report), ensure_ascii=False, indent=2, allow_nan=False))
        + "</pre></body></html>"
    )
    path = output / "report.html"
    path.write_text(document, encoding="utf-8")
    paths.append(str(path))
    path = output / "report.json"
    write_json(path, report)
    paths.append(str(path))
    files = [
        {
            "path": str(Path(p).resolve()),
            "bytes": Path(p).stat().st_size,
            "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest(),
        }
        for p in paths
    ]
    path = output / "manifest.json"
    write_json(
        path, {"schema_version": "research-files/1", "files": files, "manifest_excluded_from_self_hash": True}
    )
    return [*paths, str(path)]
