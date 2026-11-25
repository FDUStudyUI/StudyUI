"""Generate importable UI flows using the native runtime's graph serializer."""

import argparse
import json
from pathlib import Path

import pandas as pd
from lfx.graph import Graph

from components.materials_quality import (
    MaterialDuplicateCheck,
    MaterialMissingCheck,
    MaterialOutlierCheck,
    MaterialQualitySummary,
    MaterialSchemaCheck,
    MaterialTypeCheck,
    MaterialUnitCheck,
)
from examples.demo_source import MaterialDemoTable

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_ID = "MaterialQualitySummary-demo"


def create_flow_payload(case="dirty"):
    if case not in {"clean", "dirty"}:
        raise ValueError("case must be clean or dirty")
    # pandas exports strict JSON nulls; don't put NaN literals into a UI template.
    records = pd.read_csv(ROOT / "examples" / f"{case}.csv").to_json(orient="records", force_ascii=False)
    source = MaterialDemoTable().set(records_json=records)
    source.set_id("MaterialDemoTable-demo")
    nodes = [
        MaterialSchemaCheck().set(required_columns_json='["sample_id", "stress", "temperature", "date"]'),
        MaterialMissingCheck(),
        MaterialTypeCheck().set(
            expectations_json=json.dumps(
                {
                    "sample_id": "string",
                    "stress": "number",
                    "temperature": "number",
                    "date": {"type": "datetime", "format": "%Y-%m-%d"},
                }
            )
        ),
        MaterialUnitCheck().set(
            source_units_json='{"stress": "MPa", "temperature": "degC"}',
            expected_units_json='{"stress": "Pa", "temperature": "K"}',
        ),
        MaterialDuplicateCheck().set(columns_json='["sample_id"]'),
        MaterialOutlierCheck().set(
            columns_json='["stress"]',
            detection_method="range",
            bounds_json='{"stress": {"min": 0, "max": 100}}',
        ),
    ]
    for node in nodes:
        node.set_id(f"{node.name}-demo")
        node.set(input_table=source.build_table)
    summary = MaterialQualitySummary()
    summary.set_id(SUMMARY_ID)
    summary.set(reports=[node.build_report for node in nodes])
    graph = Graph(start=source, end=summary, flow_name=f"材料数据质检-{case}")
    payload = graph.dump(
        name=f"材料数据质检-{case}",
        description=("六项非破坏性检查与汇总；数据为人工测试样例。无模型调用、无需API密钥。"),
    )
    positions = {source.get_id(): {"x": 0, "y": 600}, summary.get_id(): {"x": 1000, "y": 600}}
    positions.update({node.get_id(): {"x": 400, "y": index * 500} for index, node in enumerate(nodes)})
    for node in payload["data"]["nodes"]:
        node["position"] = positions[node["id"]]
        node["type"] = "genericNode"
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["clean", "dirty", "all"], default="all")
    args = parser.parse_args()
    for case in ["clean", "dirty"] if args.case == "all" else [args.case]:
        path = ROOT / "examples" / f"{case}_quality_flow.json"
        path.write_text(
            json.dumps(create_flow_payload(case), ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
            newline="\n",
        )
        print(path)


if __name__ == "__main__":
    main()
