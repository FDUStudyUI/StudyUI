"""Attributed, unmodified public instrument sources and editable reference flows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def examples():
    return json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))


def get_example(example_id):
    for item in examples():
        if item["id"] == example_id:
            return item
    raise ValueError("未找到该仪器案例。")


def read_source(example_id):
    item = get_example(example_id)
    raw = (ROOT / "data" / item["filename"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise ValueError("仪器案例原文件校验不一致。")
    return raw


def preparation_steps(item):
    if "preparation" not in item:
        return []
    p = item["preparation"]
    return [
        (
            "channels",
            {
                "columns": ["Index", p["force_column"], p["extension_column"]],
                "rename": {p["force_column"]: "load_N", p["extension_column"]: "extension_mm"},
                "conditions": [{"column": "Index", "op": "le", "value": p["last_index"]}],
            },
        ),
        (
            "engineering",
            {
                "derived_columns": [
                    {"column": "strain", "expression": f"extension_mm / {p['gauge_mm']}", "unit": "fraction"},
                    {"column": "stress", "expression": f"load_N / {p['area_mm2']}", "unit": "MPa"},
                ],
                "conditions": [
                    {"column": "strain", "op": "ge", "value": p["strain_range"][0]},
                    {"column": "strain", "op": "le", "value": p["strain_range"][1]},
                ],
            },
        ),
    ]


def prepared_input(example_id, path=None):
    from materials_quality.agent.material_protocols import load_protocol_input
    from materials_quality.science.preprocessing import filter_rows

    item = get_example(example_id)
    spec = dict(item["protocol"], path=str(path or ROOT / "data" / item["filename"]))
    table, raw, key, config = load_protocol_input(spec)
    for _, parameters in preparation_steps(item):
        table = filter_rows(table, config=parameters).table
    return spec, (table, raw, key, config)


def compile_example(example_id, path=None):
    from materials_quality.agent.material_protocols import _compile_material_protocol
    from materials_quality.science.ui_config_import import config_to_form

    item = get_example(example_id)
    spec, bundle = prepared_input(example_id, path)
    compiled = _compile_material_protocol(spec, bundle)
    actions = compiled["actions"]
    steps = preparation_steps(item)
    if steps:
        previous = "raw"
        extra = []
        for index, (alias, parameters) in enumerate(steps, 1):
            extra.extend(
                [
                    {
                        "op": "add_node",
                        "node_id": alias,
                        "component_type": "SciencePreprocessFilter",
                        "config": config_to_form("preprocess.filter", parameters),
                        "x": index * 340,
                        "y": 100,
                    },
                    {
                        "op": "connect",
                        "source": previous,
                        "output": "table",
                        "target": alias,
                        "input": "input_table",
                    },
                    {
                        "op": "connect",
                        "source": previous,
                        "output": "report",
                        "target": alias,
                        "input": "input_data",
                    },
                ]
            )
            previous = alias
        # Preserve the raw import and make every conversion visible on the canvas.
        for action in actions:
            if action["op"] == "add_node" and action["node_id"] != "raw":
                action["x"] += 680
            if (
                action["op"] == "connect"
                and action["source"] == "raw"
                and action["target"] in {"analysis", "plot"}
            ):
                action["source"] = previous
        actions[1:1] = extra
        for alias, _ in steps:
            actions.append(
                {"op": "connect", "source": alias, "output": "report", "target": "report", "input": "reports"}
            )
    compiled["protocol"].update(
        example_id=example_id, source=item["source"], scope=item["scope"], preparation=item.get("preparation")
    )
    return compiled
