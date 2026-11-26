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
