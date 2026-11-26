"""Deterministic analysis tools added to the StudyUI dialogue harness."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from materials_quality.agent import direct_tools
from materials_quality.agent.harness import TOOLS

FIXTURES = Path(__file__).resolve().parents[1] / "testfixtures" / "harness_bench" / "fixtures"


def table(name: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / name)


def test_new_tools_are_registered():
    names = {row["function"]["name"] for row in TOOLS}
    assert {"run_science_operation", "analyze_battery_cycles", "audit_table_quality"} <= names
    schema = next(row for row in TOOLS if row["function"]["name"] == "run_science_operation")
    assert "materials.mechanics" in schema["function"]["parameters"]["properties"]["operation"]["enum"]
    assert "io.table_import" not in schema["function"]["parameters"]["properties"]["operation"]["enum"]


def test_mechanics_operation_returns_exact_fixture_values():
    result = direct_tools.execute_operation(
        "materials.mechanics",
        table=table("mechanics/tensile.csv"),
        config={
            "x": "strain_fraction",
            "y": "stress_MPa",
            "strain_unit": "fraction",
            "stress_unit": "MPa",
            "fit_range": [0.0005, 0.0015],
        },
    )
    data = result["data"]
    assert data["elastic_modulus_MPa"] == pytest.approx(200000.0, rel=1e-6)
    assert data["ultimate_strength_MPa"] == pytest.approx(500.0, abs=1e-6)
    assert result["table"]["row_count"] == 217


def test_xrd_highest_peak_is_stable():
    result = direct_tools.execute_operation(
        "materials.xrd",
        table=table("xrd/xrd_scan.csv"),
        config={
            "x": "two_theta_deg",
            "y": "intensity",
            "x_unit": "2theta_deg",
            "y_unit": "counts",
            "prominence": 50,
            "peak_distance_x": 1.0,
        },
    )
    peaks = result["data"]["peaks"]
    highest = max(peaks, key=lambda row: row["height"])
    assert highest["position"] == pytest.approx(35.4, abs=1e-9)


def test_regression_and_battery_and_quality_summaries():
    regression = direct_tools.execute_operation(
        "stats.regression",
        table=table("regression/arrhenius.csv"),
        config={"features": ["inv_T_K"], "target": "ln_sigma", "method": "linear"},
    )
    assert regression["data"]["metrics"]["r2"] == pytest.approx(1.0, abs=1e-9)
    slope = regression["data"]["model_summary"]["coefficients"][0]
    assert -slope * 8.617333262e-5 == pytest.approx(0.85, rel=1e-4)

    battery = direct_tools.battery_summary(
        table("battery/battery_cycles.csv"),
        {
            "capacity_unit": "mAh",
            "discharge_capacity": "discharge_capacity_mAh_g",
            "charge_capacity": "charge_capacity_mAh_g",
        },
    )
    assert battery["retention_pct_at_last_cycle"] == pytest.approx(80.0, abs=1e-6)
    assert battery["mean_coulombic_efficiency_pct_cycles_2_to_last"] == pytest.approx(99.7, abs=1e-3)
    assert battery["first_cycle"]["discharge_capacity_mAh_g"] == pytest.approx(180.0, abs=1e-6)

    quality = direct_tools.audit_table_quality(
        table("quality/quality_audit.csv"),
        {"negative_columns": ["conductivity_S_cm"], "ranges": {"temperature_C": [0, 2000]}},
    )
    assert quality["missing_cells"] == 3
    assert quality["duplicate_rows"] == 2
    assert quality["negative_values"]["conductivity_S_cm"] == 2
    assert quality["out_of_range"]["temperature_C"]["above"] == 2


def test_battery_columns_are_inferred_when_omitted():
    battery = direct_tools.battery_summary(
        table("battery/battery_cycles.csv"),
        {"capacity_unit": "mAh"},
    )
    assert battery["inferred_columns"] == {
        "discharge_capacity": "discharge_capacity_mAh_g",
        "charge_capacity": "charge_capacity_mAh_g",
    }
    assert battery["retention_pct_at_last_cycle"] == pytest.approx(80.0, abs=1e-6)
    assert battery["mean_coulombic_efficiency_pct_cycles_2_to_last"] == pytest.approx(99.7, abs=1e-3)


def test_direct_analysis_intent_is_narrow():
    from materials_quality.agent.harness import _direct_analysis_intent

    file_path = r"D:\data\tensile.csv"
    assert _direct_analysis_intent(f"Compute the modulus from {file_path} and end with JSON.")
    assert _direct_analysis_intent(f"Audit {file_path} for missing and duplicate rows.")
    assert not _direct_analysis_intent(f"Build a workflow from {file_path}.")
    assert not _direct_analysis_intent("Compute the modulus from this dataset.")


def test_direct_analysis_fast_path_uses_compact_context(tmp_path):
    from materials_quality.agent.file_workflow_client import FileWorkflowClient
    from materials_quality.agent.harness import StudyUIAgent
    from materials_quality.agent.store import SessionStore

    class RecordingModel:
        model = "recording"
        max_output_tokens = 4096

        def __init__(self):
            self.requests = []

        def complete(self, messages, tools, *, max_tokens=None, on_chunk=None):
            self.requests.append({"messages": list(messages), "tools": list(tools)})
            return {
                "content": '{"modulus_GPa": 200.0, "uts_MPa": 500.0}',
                "tool_calls": [],
                "usage": {"prompt_tokens": 0, "completion_tokens": 8, "total_tokens": 8},
                "reasoning_content": "",
            }

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "workflows").mkdir()
    for source in (FIXTURES / "mechanics").iterdir():
        (workspace / source.name).write_bytes(source.read_bytes())
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    catalog = {
        "projects": [
            {
                "id": "bench",
                "name": "Bench",
                "workspace_id": "ws",
                "local_directories": [str(workspace)],
            }
        ],
        "workspaces": [{"id": "ws", "name": "bench", "path": str(workspace)}],
        "variables": [],
    }
    (runtime / "workspace.json").write_text(json.dumps(catalog), encoding="utf-8")
    store = SessionStore(
        runtime / "agent.sqlite3",
        workspace_file=runtime / "workspace.json",
        workflow_root=workspace / "workflows",
    )
    model = RecordingModel()
    agent = StudyUIAgent(
        store,
        canvas=FileWorkflowClient(workspace / "workflows", FIXTURES.parents[2] / "components"),
        model=model,
    )
    agent.permissions.set_preset("bench", "project_collaboration")
    session_id = agent.new_session("fast-path", project_id="bench")
    response = agent.run_turn(
        session_id,
        f"Compute the modulus from {workspace / 'tensile.csv'} and end with a JSON object.",
    )
    assert response["verification"]["direct_analysis_fast_path"] is True
    request = model.requests[0]
    names = {tool["function"]["name"] for tool in request["tools"]}
    assert names == {"run_science_operation", "analyze_battery_cycles", "audit_table_quality"}
    system_texts = [
        str(message.get("content"))
        for message in request["messages"]
        if message.get("role") == "system"
    ]
    assert any(text.startswith("你是 StudyUI 的确定性材料数据分析 Agent") for text in system_texts)
    assert any("快路径" in text for text in system_texts)
    assert all(len(text) < 2_500 for text in system_texts)


def test_compact_results_drop_redundant_context():
    mechanics = direct_tools.execute_operation(
        "materials.mechanics",
        table=table("mechanics/tensile.csv"),
        config={
            "x": "strain_fraction",
            "y": "stress_MPa",
            "strain_unit": "fraction",
            "stress_unit": "MPa",
            "fit_range": [0.0005, 0.0015],
        },
        compact=True,
    )
    assert "table" not in mechanics
    assert "features" not in mechanics
    assert "transform" not in mechanics["data"]
    assert mechanics["data"]["ultimate_strength_MPa"] == pytest.approx(500.0)

    battery = direct_tools.battery_summary(
        table("battery/battery_cycles.csv"), {"capacity_unit": "mAh"}, compact=True
    )
    assert "cycles_preview" not in battery
    assert battery["retention_pct_at_last_cycle"] == pytest.approx(80.0, abs=1e-6)

    quality = direct_tools.audit_table_quality(
        table("quality/quality_audit.csv"),
        {"negative_columns": ["conductivity_S_cm"], "ranges": {"temperature_C": [0, 2000]}},
        compact=True,
    )
    assert "assumptions" not in quality
    assert "missing_by_column" not in quality
    assert quality["duplicate_rows"] == 2


def test_quality_ranges_accept_common_shapes():
    quality = direct_tools.audit_table_quality(
        table("quality/quality_audit.csv"),
        {"negative_columns": "conductivity_S_cm", "ranges": [["temperature_C", 0, 2000]]},
    )
    assert quality["missing_cells"] == 3
    assert quality["duplicate_rows"] == 2
    assert quality["negative_values"]["conductivity_S_cm"] == 2
    assert quality["out_of_range"]["temperature_C"]["above"] == 2


def test_battery_cell_value_is_treated_as_filter():
    battery = direct_tools.battery_summary(
        table("battery/battery_cycles.csv"),
        {"capacity_unit": "mAh", "cell_id": "cell-A"},
    )
    assert battery["cell_filter"] == "cell-A"
    assert battery["inferred_columns"]["cell_id"] == "cell_id"
    assert battery["retention_pct_at_last_cycle"] == pytest.approx(80.0, abs=1e-6)


def test_operation_config_aliases_are_normalized():
    thermal = direct_tools.execute_operation(
        "materials.thermal",
        table=table("thermal/tga.csv"),
        config={
            "kind": "TGA",
            "x": "temperature_C",
            "y": "mass_pct",
            "x_unit": "C",
            "y_unit": "percent",
        },
        compact=True,
    )
    assert thermal["data"]["total_mass_loss_percent"] == pytest.approx(40.0, abs=0.5)
    assert thermal["config_normalizations"] == []

    regression = direct_tools.execute_operation(
        "stats.regression",
        table=table("regression/arrhenius.csv"),
        config={
            "features": ["inv_T_K"],
            "target": "ln_sigma",
            "method": "linear",
            "validation_split": "chronological",
        },
        compact=True,
    )
    assert regression["data"]["metrics"]["r2"] == pytest.approx(1.0, abs=1e-9)
    assert any("time_column" in note for note in regression["config_normalizations"])


def test_invalid_thermal_kind_defaults_to_tg():
    thermal = direct_tools.execute_operation(
        "materials.thermal",
        table=table("thermal/tga.csv"),
        config={
            "kind": "mass_loss",
            "x": "temperature_C",
            "y": "mass_pct",
            "x_unit": "degC",
            "y_unit": "%",
        },
        compact=True,
    )
    assert thermal["data"]["total_mass_loss_percent"] == pytest.approx(40.0, abs=0.5)
    assert any("using tg" in note for note in thermal["config_normalizations"])


def test_operation_allowlist_rejects_io_nodes():
    with pytest.raises(ValueError, match="not available"):
        direct_tools.execute_operation("io.table_import", table=table("mechanics/tensile.csv"))


def test_inline_csv_and_summary_do_not_return_raw_rows():
    frame = direct_tools.load_inline_table("x,y\n1,2\n3,4\n")
    assert list(frame.columns) == ["x", "y"]
    summary = direct_tools._table_summary(frame)
    assert summary["row_count"] == 2
    assert summary["rows_returned"] == 0
    assert summary["numeric_summary"]["x"] == {
        "count": 2,
        "min": 1.0,
        "max": 3.0,
        "mean": 2.0,
    }
    assert "rows" not in summary
    json.dumps(summary, ensure_ascii=False)


def test_configuration_errors_list_available_columns():
    with pytest.raises(ValueError, match="available_columns"):
        direct_tools.execute_operation(
            "materials.mechanics",
            table=table("mechanics/tensile.csv"),
            config={},
        )
    with pytest.raises(ValueError, match="available_columns"):
        direct_tools.battery_summary(
            table("battery/battery_cycles.csv"),
            {"discharge_capacity": "not_a_column", "charge_capacity": "not_a_column"},
        )
