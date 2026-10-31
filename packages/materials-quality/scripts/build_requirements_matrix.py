"""Keep every source requirement verbatim and map it to implementation/evidence."""

import json
import re
from pathlib import Path

from materials_quality.science.catalog import entries

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ["schema", "missing", "types", "units", "duplicates", "outliers"]
TESTS = {
    1: ["test_science_io.py"],
    2: ["test_science_extract.py"],
    3: [
        "test_checks.py",
        "test_units_outliers.py",
        "test_quality_extensions.py",
        "test_science_preprocessing_review.py",
    ],
    4: ["test_science_preprocessing.py", "test_science_preprocessing_review.py"],
    5: ["test_science_materials.py", "test_science_materials_review.py"],
    6: ["test_science_stats.py"],
    7: ["test_science_viz.py"],
    8: ["test_science_literature.py", "test_science_literature_http.py", "test_science_literature_review.py"],
}
DOCS = {
    1: "science-io.md",
    2: "science-io.md",
    3: "../README.md",
    4: "science-preprocessing.md",
    5: "science-materials.md",
    6: "science-statistics.md",
    7: "science-visualization.md",
    8: "science-literature.md",
}


def build():
    source = (ROOT / "docs/reference-workflow-nodes.md").read_text(encoding="utf-8")
    rows, section, sequence = [], 0, 0
    for line in source.splitlines():
        if match := re.match(r"## (\d+)\. (.+)", line):
            section, sequence = int(match[1]), 0
        if match := re.match(r"- \*\*(.+?)\*\*：(.+)", line):
            title, methods = match.groups()
            sequence += 1
            item = next((e for e in entries() if e["requirement"] == title), None)
            if item is None and section != 3:
                raise ValueError(f"Unmapped source requirement: {title}")
            rows.append(
                {
                    "id": f"{section}.{sequence}",
                    "category": section,
                    "title": title,
                    "source_methods": methods,
                    "submethods": methods.rstrip("。").split("；"),
                    "operation": item["key"] if item else "quality." + QUALITY[sequence - 1],
                    "implementation": item["function"]
                    if item
                    else {
                        "schema": "materials_quality.checks:check_schema",
                        "missing": "materials_quality.checks:check_missing",
                        "types": "materials_quality.checks:check_types",
                        "units": "materials_quality.units:check_units",
                        "duplicates": "materials_quality.checks:check_duplicates",
                        "outliers": "materials_quality.outliers:check_outliers",
                    }[QUALITY[sequence - 1]],
                    "test_files": ["tests/" + f for f in TESTS[section]],
                    "method_manual": "docs/" + DOCS[section],
                }
            )
    if len(rows) != 50:
        raise ValueError(f"Source count changed: {len(rows)}")
    return rows


def main():
    rows = build()
    (ROOT / "docs/requirements-matrix.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    text = (
        "# 原文要求与实现对照\n\n50 项要求逐项保留原文。方法选择、必要输入和验证见对应手册；"
        "不能仅根据节点数量判断科学结论可靠。机器可读版本为 requirements-matrix.json。\n\n"
        "| 编号 | 要求 | 操作 | 原文方法 | 方法说明 |\n|---|---|---|---|---|\n"
    )
    for row in rows:
        manual = row["method_manual"].removeprefix("docs/")
        text += (
            f"| {row['id']} | {row['title']} | `{row['operation']}` | "
            f"{row['source_methods']} | [手册]({manual}) |\n"
        )
    (ROOT / "docs/requirements-matrix.md").write_text(text, encoding="utf-8", newline="\n")
    print("Mapped all 50 original entries")


if __name__ == "__main__":
    main()
