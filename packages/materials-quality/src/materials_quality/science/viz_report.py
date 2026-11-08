"""Self-contained, escaped analytical report templates and verified images."""

import base64
import hashlib
import html
import io
import json
import math
from pathlib import Path

from PIL import Image

from .contracts import NodeResult, artifact_path, require_table


def _json_safe(value):
    """Strict-JSON payload with non-finite numbers rendered as null, never a crash."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _text(value):
    if isinstance(value, (dict, list)):
        return json.dumps(_json_safe(value), ensure_ascii=False, indent=2, default=str, allow_nan=False)
    return str(value)


def _md(value):
    # Markdown permits raw HTML; encode it and escape markdown syntax so source
    # text cannot manufacture links, headings or images in this report.
    text = html.escape(_text(value))
    for token in ["\\", "`", "*", "_", "[", "]", "#", "|", "!"]:
        text = text.replace(token, "\\" + token)
    return text


def _evidence_html(bundle):
    """Readable claim groups with an expandable machine-auditable snapshot."""
    groups = []
    for kind, title in [
        ("observation", "数据观察"),
        ("literature_explanation", "文献解释（待复核）"),
        ("hypothesis", "待验证推测"),
    ]:
        rows = [claim for claim in bundle.get("claims", []) if claim.get("kind") == kind]
        if not rows:
            continue
        items = "".join(
            f'<li data-evidence-kind="{kind}"><p>{html.escape(str(claim.get("text", "")))}</p>'
            f"<small>{html.escape(str(claim.get('status', '')))}</small></li>"
            for claim in rows
        )
        groups.append(f'<h3>{title}</h3><ul class="claims">{items}</ul>')
    return (
        "<section><h2>Evidence-linked claims</h2>"
        + "".join(groups)
        + "<details><summary>查看结果行、来源与指纹</summary><pre>"
        + html.escape(_text(bundle))
        + "</pre></details></section>"
    )


def _results_html(results):
    """Present existing scalar values; retain the complete payload in a disclosure."""
    entries = results if isinstance(results, list) else [{"data": results}]
    summaries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        values = entry.get("data", entry)
        if not isinstance(values, dict):
            continue
        rows = "".join(
            "<tr><td>" + html.escape(str(key)) + "</td><td>" + html.escape(_text(value)) + "</td></tr>"
            for key, value in values.items()
            if (value is None or isinstance(value, (str, int, float, bool))) and len(_text(value)) <= 160
        )
        if rows:
            label = html.escape(str(entry.get("operation", "Results")))
            summaries.append(f'<h3>{label}</h3><div class="report-table"><table>{rows}</table></div>')
    return (
        "<section><h2>Results</h2>"
        + "".join(summaries)
        + "<details><summary>Complete results</summary><pre>"
        + html.escape(_text(results))
        + "</pre></details></section>"
    )


def build_report(table, c, data):
    if not isinstance(data, dict):
        raise ValueError(
            "report data must be an object with sources, parameters, results, figures and warnings"
        )
    format = c.get("format", "html")
    if format not in {"html", "markdown", "md"}:
        raise ValueError("report format must be html or markdown")
    title = data.get("title", c.get("title", "Materials analysis report"))
    sources = data.get("sources", [])
    parameters = data.get("parameters", {})
    results = data.get("results", {})
    warnings = data.get("warnings", [])
    figures = data.get("figures", [])
    if not isinstance(figures, list) or not isinstance(warnings, list):
        raise ValueError("figures and warnings must be lists")
    verified = []
    for item in figures:
        raw_path = item.get("path") if isinstance(item, dict) else item
        if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
            raise ValueError("each report figure must be a path string or an object with a nonempty path")
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"report figure missing: {path}")
        raw = path.read_bytes()
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            preview = im.convert("RGB")
            out = io.BytesIO()
            preview.save(out, format="PNG")
            encoded = base64.b64encode(out.getvalue()).decode("ascii")
        # Decode the actual embedded bytes, not merely the source file.
        with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as reread:
            reread.load()
            size = list(reread.size)
        verified.append(
            {
                "source": str(path),
                "data": encoded,
                "size": size,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "caption": item.get("caption", path.stem) if isinstance(item, dict) else path.stem,
            }
        )
    table_html, table_markdown = "", ""
    if table is not None:
        frame = require_table(table, min_rows=0)
        table_html = frame.to_html(index=False, escape=True, border=0)
        headers = "| " + " | ".join(_md(col) for col in frame.columns) + " |"
        divider = "| " + " | ".join("---" for _ in frame.columns) + " |"
        rows = [
            "| " + " | ".join(_md(v) for v in row) + " |" for row in frame.itertuples(index=False, name=None)
        ]
        table_markdown = "\n".join([headers, divider, *rows])
    sections = [
        ("Data sources", sources),
        ("Node parameters", parameters),
        ("Results", results),
        ("Warnings", warnings),
    ]
    if data.get("evidence_bundle") is not None:
        sections.append(("Evidence-linked claims", data["evidence_bundle"]))
    if format == "html":
        trace = "\n".join(
            f"<details><summary>{name}</summary><pre>{html.escape(_text(value))}</pre></details>"
            for name, value in (("Data sources", sources), ("Node parameters", parameters))
        )
        warning_html = (
            '<section><h2>Warnings</h2><ul class="warnings">'
            + "".join("<li>" + html.escape(_text(warning)) + "</li>" for warning in warnings)
            + "</ul></section>"
        )
        plots = "\n".join(
            f'<figure><img alt="{html.escape(str(f["caption"]), quote=True)}" '
            f'src="data:image/png;base64,{f["data"]}"><figcaption>'
            f"{html.escape(str(f['caption']))}</figcaption></figure>"
            for f in verified
        )
        content = (
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>'
            + html.escape(str(title))
            + "</title><style>body{max-width:1000px;margin:40px auto;font:16px/1.6 system-ui;color:#243642;"
            "padding:0 24px}h1,h2{color:#1d607b}pre{white-space:pre-wrap;background:#f4f7f8;padding:16px;"
            "overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}"
            "td,th{padding:8px;border-bottom:1px solid #ccd7db}"
            ".claims{max-height:480px;overflow:auto}details{margin:12px 0}summary{cursor:pointer;"
            "font-weight:600}small{color:#536773}.report-table{overflow:auto;max-height:560px}"
            "img{max-width:100%;max-height:65vh;object-fit:contain;height:auto}figure{margin:24px 0}"
            ".warnings li{margin:8px 0;white-space:pre-wrap;overflow-wrap:anywhere}"
            "details pre{max-height:480px;overflow:auto}</style><body><h1>"
            + html.escape(str(title))
            + "</h1>"
            + ("<section><h2>Figures</h2>" + plots + "</section>" if plots else "")
            + (
                '<section><h2>Result table</h2><div class="report-table">' + table_html + "</div></section>"
                if table_html
                else ""
            )
            + _results_html(results)
            + (_evidence_html(data["evidence_bundle"]) if data.get("evidence_bundle") is not None else "")
            + warning_html
            + trace
            + "</body></html>"
        )
        extension = "html"
    else:
        content = "# " + _md(title) + "\n\n"
        content += "\n\n".join("## " + name + "\n\n" + _md(value) for name, value in sections)
        content += "\n\n## Result table\n\n" + table_markdown + "\n\n## Figures\n\n"
        content += "\n\n".join(f"![{_md(f['caption'])}](data:image/png;base64,{f['data']})" for f in verified)
        extension = "md"
    filename = c.get("filename", f"analysis-report.{extension}")
    if Path(filename).suffix != "." + extension:
        raise ValueError("report filename extension must match its format")
    path = artifact_path({**c, "overwrite": False}, filename)
    path.write_text(content, encoding="utf-8")
    if path.read_text(encoding="utf-8") != content:
        raise ValueError("report readback failed")
    return NodeResult(
        data={
            "file_path": str(path),
            "format": format,
            "verified": True,
            "embedded_figures_verified": len(verified),
            "figures": [{k: v for k, v in item.items() if k != "data"} for item in verified],
            "sections": [name for name, _ in sections],
        },
        artifacts=[str(path)],
        warnings=[str(x) for x in warnings],
    )
