import asyncio

import pandas as pd
import pytest

from materials_quality.science.battery import analyze_battery_cycles

RAW = {
    "mode": "raw",
    "time_unit": "s",
    "current_unit": "A",
    "current_sign": "discharge_negative",
}


def test_summary_uses_each_cells_earliest_valid_cycle_and_declared_capacity_units():
    source = pd.DataFrame(
        [
            ("A", 3, 800, 1000),
            ("B", 1, 2000, 2100),
            ("A", 1, 0, 1000),
            ("A", 2, 1000, 1100),
            ("B", 2, 1600, None),
        ],
        columns=["cell_id", "cycle", "discharge_capacity", "charge_capacity"],
    )
    result = analyze_battery_cycles(
        source, {"capacity_unit": "mAh", "charge_capacity": "charge_capacity", "calculate_efficiency": True}
    )
    rows = result.features.set_index(["cell_id", "cycle"])
    assert rows.loc[("A", 3), "baseline_cycle"] == 2
    assert rows.loc[("A", 3), "discharge_capacity_ah"] == pytest.approx(0.8)
    assert rows.loc[("A", 3), "retention_pct"] == pytest.approx(80)
    assert rows.loc[("A", 3), "coulombic_efficiency_pct"] == pytest.approx(80)
    assert rows.loc[("B", 2), "retention_pct"] == pytest.approx(80)
    assert pd.isna(rows.loc[("B", 2), "coulombic_efficiency_pct"])
    assert rows.loc[("B", 2), "status"] == "partial"
    assert rows.loc[("A", 1), "status"] == "invalid"
    assert "discharge" in rows.loc[("A", 1), "reason"]
    assert result.features.attrs["units"]["retention_pct"] == "%"
    assert result.data["counts"] == {"total": 5, "valid": 3, "partial": 1, "invalid": 1}
    invalid = next(row for row in result.data["cycles"] if row["status"] == "invalid")
    assert invalid["discharge_capacity_ah"] is None
    pd.testing.assert_frame_equal(result.table, source)


def test_explicit_baseline_never_substitutes_a_different_cycle_and_duplicates_are_visible():
    source = pd.DataFrame(
        [("A", 1, 1), ("A", 1, 2), ("A", 2, 3), ("B", 1, 2), ("B", 2, 1)],
        columns=["cell_id", "cycle", "discharge_capacity"],
    )
    result = analyze_battery_cycles(source, {"capacity_unit": "Ah", "baseline_cycle": 1})
    rows = result.features.set_index(["cell_id", "cycle"])
    assert rows.loc[("A", 1), "status"] == "invalid"
    assert rows.loc[("A", 1), "source_row_count"] == 2
    assert rows.loc[("A", 2), "status"] == "partial"
    assert pd.isna(rows.loc[("A", 2), "retention_pct"])
    assert rows.loc[("B", 2), "retention_pct"] == 50


def test_raw_trapezoid_integrates_phase_runs_independently_and_handles_unit_scaling():
    source = pd.DataFrame(
        {
            "cell_id": "A",
            "cycle": 1,
            "phase": ["charge", "charge", "discharge", "discharge", "rest", "discharge", "discharge"],
            "time": [0, 60, 0, 30, 0, 180, 195],
            "current": [2000, 2000, -1000, -3000, 0, -2000, -2000],
        }
    )
    result = analyze_battery_cycles(
        source, dict(RAW, time_unit="min", current_unit="mA", calculate_efficiency=True)
    )
    row = result.features.iloc[0]
    assert row.charge_capacity_ah == pytest.approx(2)
    assert row.discharge_capacity_ah == pytest.approx(1.5)
    assert row.coulombic_efficiency_pct == pytest.approx(75)
    assert row.retention_pct == 100


@pytest.mark.parametrize(
    ("time", "current", "phase", "reason"),
    [
        ([0, 0], [-1, -1], ["discharge"] * 2, "increasing"),
        ([3600, 0], [-1, -1], ["discharge"] * 2, "increasing"),
        ([0, 3600], [-1, 0.05], ["discharge"] * 2, "sign"),
        ([0, 3600], [-1 + 1j, -1], ["discharge"] * 2, "real"),
        ([0, 3600], [-1, -1], ["discharge", "rest"], "two samples"),
        ([0, 3600], [-1, -1], ["discharge", "unknown"], "phase"),
        ([0, 3600], [1, 1], ["charge"] * 2, "discharge"),
    ],
)
def test_invalid_raw_cycle_is_retained_while_other_cycle_completes(time, current, phase, reason):
    source = pd.DataFrame(
        {
            "cell_id": "A",
            "cycle": [1, 1, 2, 2],
            "time": time + [0, 3600],
            "current": current + [-1, -1],
            "phase": phase + ["discharge"] * 2,
        }
    )
    rows = analyze_battery_cycles(source, RAW).features
    assert rows.status.tolist() == ["invalid", "valid"]
    assert reason in rows.iloc[0].reason
    assert rows.iloc[1].discharge_capacity_ah == pytest.approx(1)


def test_raw_positive_sign_with_declared_noise_tolerance_integrates_net_current():
    source = pd.DataFrame(
        {"cell_id": "A", "cycle": 1, "time": [0, 3600], "current": [-0.006, 1], "phase": "discharge"}
    )
    result = analyze_battery_cycles(
        source, dict(RAW, current_sign="discharge_positive", sign_tolerance_a=0.01)
    )
    assert result.features.iloc[0].discharge_capacity_ah == pytest.approx(0.497)
    assert pd.isna(result.features.iloc[0].coulombic_efficiency_pct)


def test_raw_efficiency_requires_comparable_order_and_explicit_request():
    source = pd.DataFrame(
        {
            "cell_id": "A",
            "cycle": 1,
            "time": [0, 3600, 0, 3600],
            "current": [-1, -1, 2, 2],
            "phase": ["discharge", "discharge", "charge", "charge"],
        }
    )
    unpaired = analyze_battery_cycles(source, dict(RAW, calculate_efficiency=True)).features.iloc[0]
    assert unpaired.status == "partial"
    assert unpaired.retention_pct == 100
    assert pd.isna(unpaired.coulombic_efficiency_pct)
    assert "precede" in unpaired.reason


def test_raw_does_not_interpret_datetime_storage_integers_as_elapsed_seconds():
    source = pd.DataFrame(
        {
            "cell_id": "A",
            "cycle": 1,
            "time": pd.date_range("2020-01-01", periods=2, freq="h"),
            "current": [-1, -1],
            "phase": "discharge",
        }
    )
    row = analyze_battery_cycles(source, RAW).features.iloc[0]
    assert row.status == "invalid"
    assert "numeric" in row.reason


def test_invalid_identity_and_incompatible_units_fail_explicitly():
    source = pd.DataFrame({"cell_id": ["A", "B"], "cycle": [1, 2], "discharge_capacity": [1, 2]})
    with pytest.raises(ValueError, match="capacity_unit"):
        analyze_battery_cycles(source)
    with pytest.raises(ValueError, match="charge_capacity"):
        analyze_battery_cycles(source, {"capacity_unit": "Ah", "calculate_efficiency": True})
    source.attrs["units"] = {"discharge_capacity": "mAh"}
    with pytest.raises(ValueError, match="conflicting units"):
        analyze_battery_cycles(source, {"capacity_unit": "Ah"})
    source.loc[1, "cycle"] = 0
    with pytest.raises(ValueError, match="positive integer"):
        analyze_battery_cycles(source, {"capacity_unit": "mAh"})


def test_summary_keeps_exact_large_cycle_numbers_when_baselines_are_missing():
    source = pd.DataFrame({"cell_id": ["A", "B"], "cycle": [2**53, 2**53 + 1], "discharge_capacity": [1, 2]})
    result = analyze_battery_cycles(source, {"capacity_unit": "Ah", "baseline_cycle": 2**53 + 1})
    rows = result.features
    assert rows.status.tolist() == ["partial", "valid"]
    assert rows.baseline_cycle.iloc[1] == 2**53 + 1


def test_native_component_builds_features_with_custom_columns_and_traceable_report():
    from lfx.custom.eval import eval_custom_component_code
    from lfx.graph import Graph
    from lfx.schema import DataFrame

    from components.materials_batch.battery_cycles import BatteryCycles

    node = BatteryCycles().set(
        input_table=DataFrame({"电芯": ["A", "A"], "cycle": [1, 2], "discharge_capacity": [2, 1]}),
        cell_column="电芯",
        capacity_unit="Ah",
    )
    results, _ = asyncio.run(node.build_results())
    assert results["features"].retention_pct.tolist() == [100, 50]
    assert results["features"].attrs["units"]["discharge_capacity_ah"] == "Ah"
    contract = results["report"].data["features_contract"]
    assert contract["granularity"] == "point"
    assert contract["roles"]["x"] == "cycle"
    assert contract["experimental_design"]["confirmed"] is False
    assert results["report"].data["provenance"]["parameters"]["cell_id"] == "电芯"
    assert len(results["report"].data["provenance"]["input_sha256"]) == 64
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert "电芯" in template["cell_column"]["options"]
    assert not template["time_column"]["show"]
    assert not template["charge_capacity_column"]["show"]
    template = node.update_build_config(template, "raw", "mode")
    assert template["current_sign"]["show"]
    assert not template["discharge_capacity_column"]["show"]
    payload = Graph(start=node, end=node).dump()
    source = payload["data"]["nodes"][0]["data"]["node"]["template"]["code"]["value"]
    assert eval_custom_component_code(source).__name__ == "BatteryCycles"
