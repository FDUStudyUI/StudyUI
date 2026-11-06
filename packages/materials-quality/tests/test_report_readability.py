"""HTML prioritizes readable outputs while preserving complete escaped evidence."""

import copy
import html
from pathlib import Path

import pandas as pd
from PIL import Image

from materials_quality.science.viz_report import build_report


def test_html_shows_figures_and_existing_scalar_results_before_collapsed_trace(tmp_path):
    image = tmp_path / "plot.png"
    Image.new("RGB", (80, 60), "white").save(image)
    data = {
        "title": "Demo <script>alert(1)</script>",
        "sources": [{"raw_source": "source-line\n" * 500}],
        "parameters": {"fit_range": [0, 0.0008]},
        "results": [
            {
                "operation": "materials.mechanics",
                "data": {
                    "elastic_modulus_MPa": 200000,
                    "fit_source_rows": list(range(17)),
                },
            }
        ],
        "warnings": ["演示单位，非验证实验。", "<img src=x onerror=alert(1)>"],
        "figures": [{"path": str(image), "caption": "Curve <script>bad</script>"}],
    }
    original = copy.deepcopy(data)
    result = build_report(pd.DataFrame({"value": [1, 2]}), {"output_dir": str(tmp_path)}, data)
    text = Path(result.artifacts[0]).read_text(encoding="utf-8")
    assert text.index("<h2>Figures</h2>") < text.index("<h2>Results</h2>")
    assert text.index("<h2>Results</h2>") < text.index("<summary>Data sources</summary>")
    assert "<td>elastic_modulus_MPa</td><td>200000</td>" in text
    assert "<details><summary>Data sources</summary>" in text
    assert "<details><summary>Node parameters</summary>" in text
    assert "<details><summary>Complete results</summary>" in text
    assert '<ul class="warnings">' in text
    assert all("<li>" + html.escape(warning) + "</li>" in text for warning in data["warnings"])
    assert "<script>" not in text
    assert "<img src=x" not in text
    assert "source-line\\n" in text
    assert data == original
    assert result.data["sections"] == ["Data sources", "Node parameters", "Results", "Warnings"]


def test_html_keeps_readable_evidence_groups_and_markdown_order(tmp_path):
    data = {
        "sources": ["original"],
        "parameters": {"x": 1},
        "results": {"mean": 2},
        "warnings": ["check assumptions"],
        "evidence_bundle": {
            "claims": [{"kind": "observation", "text": "Measured < 3", "status": "observed"}]
        },
    }
    output = build_report(None, {"output_dir": str(tmp_path)}, data)
    text = Path(output.artifacts[0]).read_text(encoding="utf-8")
    assert 'data-evidence-kind="observation"' in text
    assert "Measured &lt; 3" in text
    assert "查看结果行、来源与指纹" in text
    markdown = build_report(None, {"output_dir": str(tmp_path), "format": "markdown"}, data)
    md = Path(markdown.artifacts[0]).read_text(encoding="utf-8")
    assert md.index("## Data sources") < md.index("## Node parameters") < md.index("## Results")
    assert "## Warnings" in md
    assert "## Evidence-linked claims" in md
