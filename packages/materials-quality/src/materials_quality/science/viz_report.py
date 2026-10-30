"""Self-contained, escaped analytical report templates and verified images."""

import base64
import hashlib
import html
import io
import json
from pathlib import Path

from PIL import Image

from .contracts import NodeResult, artifact_path, require_table


def _text(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False)
    return str(value)


def _md(value):
    # Markdown permits raw HTML; encode it and escape markdown syntax so source
    # text cannot manufacture links, headings or images in this report.
    text = html.escape(_text(value))
    for token in ["\\", "`", "*", "_", "[", "]", "#", "|", "!"]:
        text = text.replace(token, "\\" + token)
    return text


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
        path = Path(item.get("path") if isinstance(item, dict) else item).expanduser().resolve()
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
    if format == "html":
        body = "\n".join(
            f"<section><h2>{name}</h2><pre>{html.escape(_text(value))}</pre></section>"
            for name, value in sections
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
            "img{max-width:100%;height:auto}figure{margin:24px 0}</style><body><h1>"
            + html.escape(str(title))
            + "</h1>"
            + body
            + "<section><h2>Result table</h2>"
            + table_html
            + "</section><section><h2>Figures</h2>"
            + plots
            + "</section></body></html>"
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
