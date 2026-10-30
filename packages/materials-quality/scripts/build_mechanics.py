"""Export self-contained synthetic tensile-data audit workflows."""

import hashlib
import json
from pathlib import Path

import pandas as pd
from lfx.graph import Graph

from components.materials_quality import (
    MaterialDuplicateCheck,
    MaterialMissingCheck,
    MaterialOutlierCheck,
    MaterialQualityContext,
    MaterialQualitySummary,
    MaterialSchemaCheck,
    MaterialTypeCheck,
    MaterialUnitCheck,
)
from examples.demo_source import MaterialDemoTable
from scripts.build_example import SUMMARY_ID

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples" / "mechanics"


def create_mechanics_payload(case="dirty"):
    if case not in {"clean", "dirty", "corrected"}:
        raise ValueError("case must be clean, dirty or corrected")
    csv = CASES / f"{case}.csv"
    records = pd.read_csv(csv, keep_default_na=False).to_json(orient="records", force_ascii=False)
    source = MaterialDemoTable().set(records_json=records)
    source.set_id("MaterialDemoTable-mechanics")
    context = MaterialQualityContext()
    context.set_id("MaterialQualityContext-mechanics")
    context.set(
        input_table=source.build_table,
        rules_json=(CASES / "rules.json").read_text(encoding="utf-8"),
        rule_set_id="synthetic-tensile-review",
        rule_set_version="1.0",
        dataset_id=f"synthetic-tensile-{case}",
        source_name=f"{case}.csv",
        source_sha256=hashlib.sha256(csv.read_bytes()).hexdigest(),
    )
    nodes = [
        cls()
        for cls in (
            MaterialSchemaCheck,
            MaterialMissingCheck,
            MaterialTypeCheck,
            MaterialUnitCheck,
            MaterialDuplicateCheck,
            MaterialOutlierCheck,
        )
    ]
    for node in nodes:
        node.set_id(f"{node.name}-mechanics")
        node.set(input_table=context.pass_table, quality_context=context.build_context)
    summary = MaterialQualitySummary()
    summary.set_id(SUMMARY_ID)
    summary.set(reports=[node.build_report for node in nodes])
    name = f"材料力学测试质检（模拟）-{case}"
    graph = Graph(start=source, end=summary, flow_name=name)
    payload = graph.dump(
        name=name, description="模拟拉伸测试数据：共享规则、来源追溯、实验分组与人工修订后复核。非真实实验。"
    )
    positions = {
        source.get_id(): {"x": 0, "y": 700},
        context.get_id(): {"x": 550, "y": 700},
        summary.get_id(): {"x": 2300, "y": 700},
    }
    # A two-column, three-row check area fits native UI's minimum zoom on laptops.
    positions.update(
        {node.get_id(): {"x": 1100 + (i // 3) * 600, "y": (i % 3) * 700} for i, node in enumerate(nodes)}
    )
    for node in payload["data"]["nodes"]:
        node["position"] = positions[node["id"]]
        node["type"] = "genericNode"
    return payload


def main():
    for case in ("clean", "dirty", "corrected"):
        path = CASES / f"{case}_flow.json"
        payload = create_mechanics_payload(case)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8", newline="\n"
        )
        print(path)


if __name__ == "__main__":
    main()
