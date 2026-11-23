import importlib.util

import numpy as np
import pandas as pd
import pytest


def test_agent_summary_hides_inactive_scientific_defaults():
    from materials_quality.agent.workflow import flow_summary

    flow = {
        "data": {
            "nodes": [
                {
                    "id": "plot",
                    "data": {
                        "type": "test",
                        "node": {
                            "template": {
                                "cfg_y": {"value": "intensity", "show": False},
                                "cfg_columns": {"value": ["stress_MPa"], "show": True},
                            }
                        },
                    },
                }
            ],
            "edges": [],
        }
    }
    fields = flow_summary(flow)["nodes"][0]["config"]
    assert fields == {"cfg_columns": ["stress_MPa"]}


def compiler():
    assert importlib.util.find_spec("materials_quality.agent.material_protocols"), "Missing protocol compiler"
    from materials_quality.agent.material_protocols import compile_material_protocol

    return compile_material_protocol


def test_agent_cannot_save_an_invented_dropdown_option():
    from materials_quality.agent.workflow import _set_config
    from materials_quality.science.catalog import component_class

    component = component_class("viz.spectra")()
    node = component.to_frontend_node()
    with pytest.raises(ValueError, match="cfg_data_kind"):
        _set_config(node, {"cfg_data_kind": "experimental"})
    _set_config(node, {"cfg_data_kind": "measured"})
    assert node["data"]["node"]["template"]["cfg_data_kind"]["value"] == "measured"


def test_protocol_reads_original_numeric_instrument_file(tmp_path):
    path = tmp_path / "scan.dat"
    path.write_text("# instrument export\n10 1\n20 4\n30 1\n", encoding="utf-8")
    result = compiler()(
        {
            "task": "xrd",
            "path": str(path),
            "x": "x",
            "y": "y",
            "x_unit": "deg",
            "y_unit": "counts",
            "baseline": "none",
            "prominence": 1,
        }
    )
    raw = result["actions"][0]
    assert raw["component_type"] == "ScienceIoInstrumentImport"
    assert result["protocol"]["row_count"] == 3
    assert result["protocol"]["source_sha256"]


def test_mechanics_requires_explicit_units_and_elastic_range(tmp_path):
    path = tmp_path / "curve.csv"
    pd.DataFrame({"strain": [0, 0.001, 0.002], "stress": [0, 200, 210]}).to_csv(path, index=False)
    compile = compiler()
    with pytest.raises(ValueError, match="fit_range"):
        compile(
            {
                "task": "mechanics",
                "path": str(path),
                "x": "strain",
                "y": "stress",
                "x_unit": "fraction",
                "y_unit": "MPa",
            }
        )


@pytest.mark.parametrize("task", ["mechanics", "spectra", "xrd"])
def test_protocol_is_deterministic_and_all_nodes_are_native_forms(tmp_path, task):
    path = tmp_path / "curve.csv"
    pd.DataFrame({"xx": [0, 0.001, 0.002, 0.003], "yy": [0, 200, 210, 215]}).to_csv(path, index=False)
    spec = {
        "task": task,
        "path": str(path),
        "x": "xx",
        "y": "yy",
        "x_unit": "fraction" if task == "mechanics" else "deg" if task == "xrd" else "nm",
        "y_unit": "MPa" if task == "mechanics" else "counts",
    }
    if task == "mechanics":
        spec.update(fit_range=[0, 0.002], yield_offset=0.002)
    else:
        spec.update(baseline="none", prominence=1)
    compile = compiler()
    result = compile(spec)
    assert result == compile(spec)
    nodes = [a for a in result["actions"] if a["op"] == "add_node"]
    assert len(nodes) >= 4
    assert all(n["config"].get("config_json", "{}") == "{}" for n in nodes)
    assert all(n["config"].get("ui_mode", "form") == "form" for n in nodes)
    assert result["protocol"]["source_sha256"]


def test_protocol_rejects_invented_columns_and_ambiguous_multiple_curves(tmp_path):
    path = tmp_path / "curve.csv"
    pd.DataFrame({"strain": [0, 1, 0, 1], "stress": [0, 2, 0, 3]}).to_csv(path, index=False)
    compile = compiler()
    spec = {
        "task": "mechanics",
        "path": str(path),
        "x": "missing",
        "y": "stress",
        "x_unit": "fraction",
        "y_unit": "MPa",
        "fit_range": [0, 1],
        "yield_offset": 0.002,
    }
    with pytest.raises(ValueError, match="列"):
        compile(spec)
    spec["x"] = "strain"
    with pytest.raises(ValueError, match="单调|曲线"):
        compile(spec)


@pytest.mark.parametrize("task", ["mechanics", "spectra", "xrd"])
def test_protocol_executes_connected_graph_and_matches_independent_reference(tmp_path, task):
    from lfx.graph import Graph

    from materials_quality.agent.workflow import apply_actions
    from materials_quality.science.catalog import component_class

    path = tmp_path / "measurements.csv"
    x = np.linspace(0, 0.02, 401) if task == "mechanics" else np.linspace(10, 80, 701)
    y = (
        np.where(x <= 0.001, 200000 * x, 200 + 1000 * (x - 0.001))
        if task == "mechanics"
        else (100 * np.exp(-(((x - 40) / 2) ** 2)))
    )
    pd.DataFrame({"x": x, "y": y}).to_csv(path, index=False)
    spec = {
        "task": task,
        "path": str(path),
        "x": "x",
        "y": "y",
        "x_unit": "fraction" if task == "mechanics" else "deg" if task == "xrd" else "nm",
        "y_unit": "MPa" if task == "mechanics" else "counts",
    }
    spec.update(
        {"fit_range": [0, 0.0008], "yield_offset": 0.002}
        if task == "mechanics"
        else {"baseline": "none", "prominence": 1}
    )
    compiled = compiler()(spec)
    keys = ["io.table_import", "materials." + task, "viz.spectra", "export.report", "export.table"]
    catalog = {
        "materials_protocols": {
            component_class(k)().name: component_class(k)().to_frontend_node()["data"]["node"] for k in keys
        }
    }
    flow, _ = apply_actions({"data": {"nodes": [], "edges": []}}, compiled["actions"], catalog)
    graph = Graph.from_payload(flow)
    for step in graph.start():
        if hasattr(step, "valid"):
            assert step.valid, step
    results = graph.get_vertex("analysis").results
    report = results["report"].data
    # Exact expected quantities come from the input formulas, not the analyzed report.
    if task == "mechanics":
        assert report["data"]["elastic_modulus_MPa"] == pytest.approx(200000)
    else:
        features = results["features"]
        assert any(abs(float(v) - 40) < 0.11 for v in features["peak_position"])
    assert graph.get_vertex("report").results["report"].data["artifacts"]
