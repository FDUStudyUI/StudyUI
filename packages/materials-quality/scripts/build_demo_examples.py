"""Build five portable native reference graphs from unchanged packaged originals.

Run from packages/materials-quality: python -m scripts.build_demo_examples.
This only regenerates stored graphs, never the originals or catalog metadata.
"""

import base64
import hashlib
import json
from pathlib import Path

from components.materials_batch.batch_spectrum_analyzer import BatchSpectrumAnalyzer
from components.materials_batch.contrast_study import ContrastStudy
from components.materials_sources.science_fixture_bundle import ScienceFixtureBundle
from materials_quality.demos.catalog import ROOT, list_datasets, read_demo_bytes
from materials_quality.science.ui_config_import import config_to_form
from scripts.build_batch_examples import _dump, _id, _science


def _node(key, name, config=None, **connections):
    settings = config_to_form(key, config or {})
    settings.pop("ui_mode", None)
    settings.pop("config_json", None)
    return _science(key, name, **settings, **connections)


def _build(info):
    case = info["id"]
    raw = read_demo_bytes(case)
    bundle = {
        "synthetic": True,
        "assets": {info["filename"]: {"base64": base64.b64encode(raw).decode(), "sha256": info["sha256"]}},
        "data": {
            "operation": "demo.source",
            "provenance": {
                "source_sha256": info["sha256"],
                "source_filename": info["filename"],
                **info["provenance"],
            },
            "warnings": [info["provenance"]["description"], *info["limitations"]],
            "data": {
                "dataset_id": case,
                "row_count": info["row_count"],
                "scope": info["scope"],
                "units": info["units"],
            },
        },
    }
    source = _id(ScienceFixtureBundle(), case + "-source").set(
        bundle_base64=base64.b64encode(json.dumps(bundle, ensure_ascii=False).encode()).decode()
    )
    config = {"path": "@asset:" + info["filename"]}
    if case == "zirconia_xrd":
        config.update(delimiter=" ", range="A19:B3020", header=0)
    imported = _node("io.table_import", case + "-import", config, input_data=source.build_data)
    nodes = [source, imported]
    reports = [source.build_data, imported.build_report]

    def add(key, suffix, config, **connections):
        node = _node(key, case + "-" + suffix, config, **connections)
        nodes.append(node)
        reports.append(node.build_report)
        return node

    def plot(key, suffix, config, **connections):
        return add(key, suffix, {"data_kind": "synthetic", "formats": ["png"], **config}, **connections)

    if case == "ti64_tensile":
        analyzed = add(
            "materials.mechanics",
            "analysis",
            {
                "x": "strain",
                "y": "stress",
                "strain_unit": "fraction",
                "stress_unit": "MPa",
                "fit_range": [0, 0.0008],
                "yield_offset": 0.002,
                "fracture_confirmed": False,
            },
            input_table=imported.build_table,
            input_data=imported.build_report,
        )
        plot(
            "viz.mechanics",
            "plot",
            {
                "x": "strain",
                "y": "stress",
                "sample": "specimen",
                "units": {"strain": "fraction", "stress": "MPa"},
                "title": "One synthetic specimen; assumed MPa / strain fraction",
            },
            input_table=imported.build_table,
            input_data=imported.build_report,
        )
    elif case == "raman_spectra":
        analyzed = _id(BatchSpectrumAnalyzer(), case + "-analysis").set(
            input_table=imported.build_table,
            x_column="wavelength_nm",
            y_column="intensity_counts",
            group_column="group",
            x_unit="nm",
            intensity_unit="counts",
            baseline_method="constant",
            baseline_value=2.0,
            prominence_mode="显式阈值",
            prominence=0.5,
            lambda10_enabled=True,
            lambda10_min_nm=650.0,
            lambda10_max_nm=850.0,
            on_error="stop",
        )
        nodes.append(analyzed)
        reports.append(analyzed.build_report)
        plot(
            "viz.spectra",
            "plot",
            {
                "method": "band",
                "x": "x",
                "y": "smoothed",
                "curve_id": "curve_id",
                "group": "group",
                "band": "iqr",
                "title": "Corrected spectra: group mean and descriptive IQR",
            },
            input_table=analyzed.build_curves,
            input_data=analyzed.build_report,
        )
        add("export.table", "features", {"format": "csv"}, input_table=analyzed.build_features)
    elif case == "material_contrast":
        analyzed = _id(ContrastStudy(), case + "-analysis").set(
            input_table=imported.build_table,
            design="independent",
            strategy="parametric",
            correction="holm",
            value_unit="a.u.",
        )
        nodes.append(analyzed)
        reports.append(analyzed.build_report)
        plot(
            "viz.performance",
            "plot",
            {
                "method": "bar",
                "y": "value",
                "group": "group",
                "title": "Independent unit means; n=4/group; bars mean +/- SD",
            },
            input_table=analyzed.build_units,
        )
        add("export.table", "units", {"format": "csv"}, input_table=analyzed.build_units)
        add("export.table", "features", {"format": "csv"}, input_table=analyzed.build_features)
    elif case == "zirconia_xrd":
        analyzed = add(
            "materials.xrd",
            "analysis",
            {
                "x": "2Theta",
                "y": "Intensity",
                "x_unit": "deg",
                "intensity_unit": "cps",
                "baseline": {"method": "linear"},
                "prominence": 100.0,
            },
            input_table=imported.build_table,
            input_data=imported.build_report,
        )
        plot(
            "viz.spectra",
            "plot",
            {
                "method": "line",
                "x": "x",
                "columns": ["raw_y", "corrected"],
                "units": {"x": "deg", "raw_y": "cps", "corrected": "cps"},
                "title": "XRD candidate peaks only; no phase library",
            },
            input_table=analyzed.build_table,
            input_data=analyzed.build_report,
        )
    else:
        add(
            "export.table",
            "original",
            {"format": "csv"},
            input_table=imported.build_table,
            input_data=imported.build_report,
        )
        for branch, label in (("charge", "Charge"), ("discharge", "Discharge")):
            selected = add(
                "preprocess.filter",
                branch,
                {"conditions": [{"column": "Step", "op": "eq", "value": label}]},
                input_table=imported.build_table,
                input_data=imported.build_report,
            )
            wide = add(
                "preprocess.reshape",
                branch + "-soc",
                {"method": "long_to_wide", "index": ["SOC"], "columns": "Step", "values": "Voltage_V"},
                input_table=selected.build_table,
                input_data=selected.build_report,
            )
            plot(
                "viz.spectra",
                branch + "-plot",
                {
                    "method": "line",
                    "x": "SOC",
                    "columns": [label],
                    "units": {"SOC": "fraction", label: "V"},
                    "title": label + ": voltage vs supplied SOC (one cycle)",
                },
                input_table=wide.build_table,
                input_data=wide.build_report,
            )

    report = _node(
        "export.report",
        case + "-report",
        {
            "title": info["title"] + "｜演示参考流程（未验证实验来源）",
            "format": "html",
        },
        reports=reports,
    )
    nodes.append(report)
    payload = _dump(nodes, info["title"] + "｜演示参考流程")
    payload["demo_dataset_id"] = case
    payload["studyui_reference"] = {
        "dataset_id": case,
        "source_sha256": info["sha256"],
        "nodes": {node.get_id().split(case + "-", 1)[1]: node.get_id() for node in nodes},
    }
    payload["description"] = info["scope"] + "。打开后按画布运行；可在节点表单修改参数。"
    # The left trunk feeds analysis, parallel output branches, and the final report.
    roles = payload["studyui_reference"]["nodes"]
    layout = {
        "source": (0, 0),
        "import": (450, 0),
        "analysis": (900, 0),
        "plot": (1350, 0),
        "features": (1350, 1100),
        "units": (1350, -1100),
        "report": (1800, 0),
    }
    if case == "ti64_tensile":
        layout.update(plot=(900, 1100), report=(1350, 0))
    elif case == "zirconia_xrd":
        layout.update(plot=(1350, 700))
    if case == "battery_cycle":
        layout = {
            "source": (0, 0),
            "import": (450, 0),
            "original": (900, -1100),
            "charge": (900, 0),
            "charge-soc": (1350, 0),
            "charge-plot": (1800, 0),
            "discharge": (900, 1100),
            "discharge-soc": (1350, 1100),
            "discharge-plot": (1800, 1100),
            "report": (2250, 0),
        }
    positions = {node_id: {"x": layout[role][0], "y": layout[role][1]} for role, node_id in roles.items()}
    for vertex in payload["data"]["nodes"]:
        vertex["position"] = positions[vertex["id"]]
    return payload


def build_examples(destination=None):
    destination = Path(destination or ROOT / "flows")
    destination.mkdir(parents=True, exist_ok=True)
    payloads = {}
    hashes = {}
    for info in list_datasets():
        payload = _build(info)
        path = destination / (info["id"] + ".json")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        hashes[info["id"]] = hashlib.sha256(path.read_bytes()).hexdigest()
        payloads[info["id"]] = payload
    (destination / "checksums.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8", newline="\n")
    return payloads


if __name__ == "__main__":
    build_examples()
