"""Build small FORM-mode graphs for real browser acceptance, with actual uploads."""

import argparse
import json
from pathlib import Path

import pandas as pd
from lfx.graph import Graph
from PIL import Image

from components.materials_quality import MaterialQualityContext, MaterialSchemaCheck
from materials_quality.science.catalog import component_class

ROOT = Path(__file__).resolve().parents[1]


def _science(key, alias, **values):
    node = component_class(key)()
    node.set_id(node.name + "-" + alias)
    node.set(ui_mode="form", config_json="{}", **values)
    return node


def _dump(source, sink, name, nodes):
    payload = Graph(start=source, end=sink, flow_name=name).dump(name=name)
    for node in payload["data"]["nodes"]:
        node["type"] = "genericNode"
        node["position"] = {"x": nodes.index(node["id"]) * 540, "y": 0}
    return payload


def build_examples(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(ROOT / "examples/science/materials/fixtures/synthetic_tensile.csv")
    assert len(frame) == 401
    frame.assign(specimen="synthetic-1").to_csv(destination / "synthetic-tensile.csv", index=False)
    Image.new("RGB", (13, 7), color=(24, 100, 180)).save(destination / "tiny.png")

    source = _science("io.table_import", "upload")
    mechanics = _science(
        "materials.mechanics", "fit", input_table=source.build_table, input_data=source.build_report
    )
    curve = _science(
        "viz.mechanics",
        "figure",
        input_table=source.build_table,
        input_data=mechanics.build_report,
        cfg_sample="specimen",
        cfg_data_kind="synthetic",
    )
    report = _science(
        "export.report", "html", reports=[source.build_report, mechanics.build_report, curve.build_report]
    )
    mechanics_flow = _dump(
        source, report, "FORM mechanics upload", [n.get_id() for n in [source, mechanics, curve, report]]
    )

    image = _science("io.image_import", "image")
    image_report = _science("export.report", "imagehtml", reports=[image.build_report])
    image_flow = _dump(image, image_report, "FORM image upload", [image.get_id(), image_report.get_id()])

    table = _science("io.table_import", "quality")
    context = MaterialQualityContext()
    context.set_id("MaterialQualityContext-form")
    context.set(
        ui_mode="form", input_table=table.build_table, enabled_checks=["schema"], required_columns=["strain"]
    )
    check = MaterialSchemaCheck()
    check.set_id("MaterialSchemaCheck-form")
    check.set(ui_mode="form", input_table=context.pass_table, quality_context=context.build_context)
    quality = _dump(table, check, "FORM shared quality rules", [n.get_id() for n in [table, context, check]])

    missing = _science("preprocess.missing", "dynamic", input_table=table.build_table)
    dynamic = _dump(table, missing, "FORM dynamic preprocessing", [table.get_id(), missing.get_id()])
    values = {"mechanics": mechanics_flow, "image": image_flow, "quality": quality, "dynamic": dynamic}
    for name, payload in values.items():
        (destination / (name + ".json")).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return values


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "examples/form_flows")
    args = parser.parse_args()
    build_examples(args.output)
