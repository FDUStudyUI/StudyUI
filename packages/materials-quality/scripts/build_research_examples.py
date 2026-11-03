"""Build portable eight-curve feature/statistics and spectral-band workflows."""

import argparse
import base64
import json
from pathlib import Path

import numpy as np
from lfx.graph import Graph

from components.materials_batch.batch_spectrum_analyzer import BatchSpectrumAnalyzer
from examples.science_flows.fixture_source import ScienceFixtureBundle
from materials_quality.science.catalog import component_class

ROOT = Path(__file__).resolve().parents[1]
MODE_CENTERS = [700, 710, 720, 730, 740, 750, 760, 770]


def synthetic_records():
    """Two groups of four independent synthetic curves, with two known peaks."""
    records = []
    x = np.arange(400, 901, dtype=float)
    for index, center in enumerate(MODE_CENTERS):
        y = 2 + 10 * np.exp(-0.5 * ((x - 530) / 10) ** 2)
        y += 5 * np.exp(-0.5 * ((x - center) / 12) ** 2)
        records.extend(
            {
                "curve_id": f"curve-{index + 1:02}",
                "group": "A" if index < 4 else "B",
                "wavelength_nm": float(xx),
                "intensity_counts": float(yy),
            }
            for xx, yy in zip(x, y, strict=True)
        )
    return records


def _id(node, suffix):
    node.set_id(node.name + "-" + suffix)
    return node


def _science(key, suffix, **values):
    return _id(component_class(key)(), suffix).set(ui_mode="form", config_json="{}", **values)


def _source_and_spectra(suffix):
    bundle = base64.b64encode(json.dumps({"records": synthetic_records()}).encode()).decode()
    source = _id(ScienceFixtureBundle(), suffix).set(bundle_base64=bundle)
    analyzer = _id(BatchSpectrumAnalyzer(), suffix).set(
        input_table=source.build_table,
        x_column="wavelength_nm",
        y_column="intensity_counts",
        group_column="group",
        x_unit="nm",
        intensity_unit="counts",
        baseline_method="constant",
        baseline_value=2,
        lambda10_enabled=True,
        lambda10_min_nm=650,
        lambda10_max_nm=850,
    )
    return source, analyzer


def _dump(nodes, title):
    payload = Graph(start=nodes[0], end=nodes[-1], flow_name=title).dump(name=title)
    ids = [node.get_id() for node in nodes]
    for vertex in payload["data"]["nodes"]:
        vertex["type"] = "genericNode"
        vertex["position"] = {"x": ids.index(vertex["id"]) * 540, "y": 0}
    return payload


def build_examples(destination=None):
    destination = Path(destination or ROOT / "examples/research_flows")
    destination.mkdir(parents=True, exist_ok=True)
    source, analyzer = _source_and_spectra("eight")
    selected = _science(
        "preprocess.filter",
        "candidates",
        input_table=analyzer.build_features,
        input_data=analyzer.build_report,
        cfg_conditions=[{"column": "is_lambda10_candidate", "op": "eq", "value": "true"}],
    )
    grouped = _science(
        "stats.grouped",
        "means",
        input_table=selected.build_table,
        input_data=selected.build_report,
        cfg_group="group",
        cfg_columns=["lambda10_nm"],
    )
    report = _science(
        "export.report",
        "html",
        reports=[analyzer.build_report, grouped.build_report],
        cfg_title="Eight synthetic spectra: window-selected candidates and group statistics",
    )
    values = {
        "01_eight_curve_features": _dump(
            [source, analyzer, selected, grouped, report], "八条合成光谱：特征端口与分组统计"
        )
    }

    source, analyzer = _source_and_spectra("band")
    band = _science(
        "viz.spectra",
        "band",
        input_table=analyzer.build_curves,
        input_data=analyzer.build_report,
        cfg_method="band",
        cfg_x="x",
        cfg_y="corrected",
        cfg_curve_id="curve_id",
        cfg_group="group",
        cfg_band="iqr",
        cfg_data_kind="synthetic",
        cfg_formats=["png"],
        cfg_title="Synthetic spectral means and pointwise interquartile bands",
    )
    report = _science("export.report", "bandhtml", reports=[analyzer.build_report, band.build_report])
    values["02_eight_curve_bands"] = _dump(
        [source, analyzer, band, report], "八条合成光谱：分组均值与真实填充带"
    )
    for name, payload in values.items():
        (destination / (name + ".json")).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
    return values


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build_examples(args.output)
