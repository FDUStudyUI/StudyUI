"""Build portable form-only batch examples and a twenty-file upload template."""

import argparse
import base64
import json
from pathlib import Path

import pandas as pd
from lfx.graph import Graph

from components.materials_batch.batch_quality import MaterialBatchQuality
from components.materials_batch.batch_source import MaterialBatchInput
from components.materials_batch.batch_summary import MaterialBatchSummary
from examples.science_flows.fixture_source import ScienceFixtureBundle
from materials_quality.science.catalog import component_class

ROOT = Path(__file__).resolve().parents[1]


def _id(node, name):
    node.set_id(node.name + "-" + name)
    return node


def _science(key, name, **values):
    return _id(component_class(key)(), name).set(ui_mode="form", config_json="{}", **values)


def _dump(nodes, title):
    payload = Graph(start=nodes[0], end=nodes[-1], flow_name=title).dump(name=title)
    ids = [n.get_id() for n in nodes]
    for vertex in payload["data"]["nodes"]:
        vertex["type"] = "genericNode"
        vertex["position"] = {"x": ids.index(vertex["id"]) * 520, "y": 0}
    return payload


def build_examples(destination=None):
    dest = Path(destination or ROOT / "examples/batch_flows")
    dest.mkdir(parents=True, exist_ok=True)
    fixtures = dest / "twenty_csv"
    fixtures.mkdir(exist_ok=True)
    original = pd.read_csv(ROOT / "examples/science/materials/fixtures/synthetic_tensile.csv")
    frames = []
    for i in range(20):
        frame = original.copy()
        frame["stress"] *= 1 + i / 10
        frame["specimen"] = f"synthetic-{i + 1:02}"
        frame.to_csv(fixtures / f"specimen-{i + 1:02}.csv", index=False)
        frames.append(frame)
    records = pd.concat(frames, ignore_index=True).to_dict("records")
    encoded = base64.b64encode(json.dumps({"records": records}).encode()).decode()
    fixture = _id(ScienceFixtureBundle(), "twenty").set(bundle_base64=encoded)
    source = _id(MaterialBatchInput(), "twenty").set(
        source_mode="grouped", input_table=fixture.build_table, sample_column="specimen"
    )
    quality = _id(MaterialBatchQuality(), "twenty").set(
        input_data=source.build_batch, enabled_checks=["missing"], columns=["strain", "stress"]
    )
    mechanics = _science(
        "materials.mechanics",
        "twenty",
        input_data=quality.build_batch,
        cfg_fit_range_min=0,
        cfg_fit_range_max=0.0008,
    )
    plot = _science(
        "viz.mechanics",
        "twenty",
        input_data=mechanics.build_report,
        cfg_x="strain_fraction",
        cfg_y="stress_MPa",
        cfg_sample="batch_item_id",
        cfg_data_kind="synthetic",
        cfg_formats=["png"],
    )
    sink = _id(MaterialBatchSummary(), "twenty").set(input_data=plot.build_report)
    values = {
        "01_twenty_specimens": _dump(
            [fixture, source, quality, mechanics, plot, sink], "批量拉伸：20份完整试样（合成）"
        )
    }
    upload = _id(MaterialBatchInput(), "upload").set(source_mode="files")
    reader = _science("io.table_import", "upload", input_data=upload.build_batch)
    upload_quality = _id(MaterialBatchQuality(), "upload").set(
        input_data=reader.build_report, enabled_checks=["missing"], columns=["strain", "stress"]
    )
    upload_mechanics = _science(
        "materials.mechanics",
        "upload",
        input_data=upload_quality.build_batch,
        cfg_fit_range_min=0,
        cfg_fit_range_max=0.0008,
    )
    upload_plot = _science(
        "viz.mechanics",
        "upload",
        input_data=upload_mechanics.build_report,
        cfg_x="strain_fraction",
        cfg_y="stress_MPa",
        cfg_sample="batch_item_id",
        cfg_data_kind="synthetic",
        cfg_formats=["png"],
    )
    upload_sink = _id(MaterialBatchSummary(), "upload").set(input_data=upload_plot.build_report)
    values["02_twenty_files_upload"] = _dump(
        [upload, reader, upload_quality, upload_mechanics, upload_plot, upload_sink],
        "批量上传：多份CSV拉伸试样（合成）",
    )
    for name, payload in values.items():
        (dest / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return values


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build_examples(args.output)
