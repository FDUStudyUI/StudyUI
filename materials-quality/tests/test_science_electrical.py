import json
from pathlib import Path

import pandas as pd
import pytest

from materials_quality.science import electrical
from materials_quality.science.table_contract import attach_contract, make_contract, read_contract

IV = {"mode": "iv", "voltage_unit": "mV", "current_unit": "uA", "voltage_min": -10, "voltage_max": 10}
PHOTO = {
    "mode": "photoresponse",
    "time_unit": "ms",
    "current_unit": "nA",
    "baseline_start": 0,
    "baseline_end": 1,
    "light_on": 2,
    "on_plateau_start": 6,
    "on_plateau_end": 7,
    "light_off": 8,
    "recovery_end": 13,
}


def test_iv_fits_only_requested_domain_with_si_units_and_sample_role():
    raw = pd.DataFrame(
        {
            "curve_id": ["001"] * 5,
            "specimen": ["007"] * 5,
            "voltage": [-20, -10, 0, 10, 20],
            "current": [60, -19, 1, 21, -80],
        }
    )
    raw = attach_contract(raw, make_contract(raw, granularity="point", roles={"sample_id": "specimen"}))
    result = electrical.analyze_electrical(raw, IV)
    fit = result.features.iloc[0]
    assert (fit.curve_id, fit.sample_id, fit.status, fit.direction) == ("001", "007", "ok", "increasing")
    assert (fit.fit_n_points, fit.fit_voltage_min_V, fit.fit_voltage_max_V) == (3, -0.01, 0.01)
    assert fit.slope_A_per_V == pytest.approx(0.002)
    assert fit.conductance_S == pytest.approx(0.002)
    assert fit.resistance_ohm == pytest.approx(500)
    assert fit.intercept_A == pytest.approx(1e-6)
    assert fit.r_squared == pytest.approx(1)
    assert fit.residual_rmse_A == pytest.approx(0, abs=1e-15)
    assert result.table.in_fit_domain.tolist() == [False, True, True, True, False]
    assert result.table.loc[[0, 4], "fitted_current_A"].isna().all()
    assert result.table.current.tolist() == raw.current.tolist()
    assert result.features.attrs["units"]["resistance_ohm"] == "ohm"
    assert read_contract(result.features)["roles"] == {"curve_id": "curve_id", "sample_id": "sample_id"}
    assert read_contract(result.features)["experimental_design"]["confirmed"] is False
    assert read_contract(result.table)["granularity"] == "point"


def test_iv_requires_explicit_sweeps_and_keeps_bad_curve_local():
    raw = pd.DataFrame(
        {
            "curve_id": ["loop"] * 6 + ["good"] * 3,
            "scan": ["up"] * 3 + ["down"] * 6,
            "voltage": [-10, 0, 10, 10, 0, -10, 10, 0, -10],
            "current": [-20, 0, 20, 30, 0, -30, 40, 0, -40],
        }
    )
    unsplit = electrical.analyze_electrical(raw, IV)
    assert unsplit.features.status.tolist() == ["invalid", "ok"]
    assert "sweep" in unsplit.features.reason.iloc[0]
    split = electrical.analyze_electrical(raw, {**IV, "sweep": "scan"})
    assert split.features.sweep_id.tolist() == ["up", "down", "down"]
    assert split.features.direction.tolist() == ["increasing", "decreasing", "decreasing"]
    assert split.features.slope_A_per_V.tolist() == pytest.approx([0.002, 0.003, 0.004])
    assert read_contract(split.features)["roles"]["curve_id"] == "analysis_curve_id"
    assert split.features.analysis_curve_id.is_unique


@pytest.mark.parametrize(
    "voltage, current, expected_r_squared",
    [([-10, 0, 10], [5, 5, 5], None), ([-10, -9, -6], [11, 11, 11], None), ([-10, 0, 10], [20, 0, -20], 1)],
)
def test_iv_with_nonpositive_slope_preserves_fit_but_marks_resistance_missing(
    voltage, current, expected_r_squared
):
    raw = pd.DataFrame({"curve_id": ["001"] * 3, "voltage": voltage, "current": current})
    result = electrical.analyze_electrical(raw, IV)
    fit = result.features.iloc[0]
    assert fit.status == "partial"
    assert pd.isna(fit.conductance_S) and pd.isna(fit.resistance_ohm)
    if expected_r_squared is None:
        assert pd.isna(fit.r_squared)
    else:
        assert fit.r_squared == pytest.approx(expected_r_squared)
    assert result.table.fitted_current_A.tolist() == pytest.approx([x * 1e-6 for x in current])


def test_photoresponse_interpolates_ordered_crossings_for_negative_amplitude():
    raw = pd.DataFrame(
        {
            "curve_id": ["001"] * 11,
            "time": [0, 1, 2, 4, 6, 7, 8, 10, 12, 13, 14],
            "current": [2, 2, 2, -3, -8, -8, -8, -3, 2, 2, 99],
        }
    )
    result = electrical.analyze_electrical(raw, PHOTO)
    fit = result.features.iloc[0]
    assert fit.status == "ok"
    assert fit.baseline_A == pytest.approx(2e-9)
    assert fit.on_plateau_A == pytest.approx(-8e-9)
    assert fit.amplitude_A == pytest.approx(-10e-9)
    assert fit.rise_time_s == pytest.approx(0.0032)
    assert fit.recovery_time_s == pytest.approx(0.0032)
    assert pd.isna(result.table.loc[10, "photo_phase"])


def test_photoresponse_reports_incomplete_recovery_without_rescaling_end_level():
    raw = pd.DataFrame(
        {
            "curve_id": ["001"] * 10,
            "time": [0, 1, 2, 4, 6, 7, 8, 10, 12, 13],
            "current": [0, 0, 0, 5, 10, 10, 10, 9, 6, 5],
        }
    )
    fit = electrical.analyze_electrical(raw, PHOTO).features.iloc[0]
    assert fit.status == "partial"
    assert fit.rise_time_s == pytest.approx(0.0032)
    assert pd.isna(fit.recovery_time_s)
    assert fit.recovery_reason == "missing_10_percent_crossing"


@pytest.mark.parametrize("overrides", [{"voltage_min": None}, {"voltage_unit": "s"}, {"current_unit": "V"}])
def test_iv_requires_explicit_physical_units_and_a_finite_domain(overrides):
    raw = pd.DataFrame({"curve_id": ["001"] * 3, "voltage": [-10, 0, 10], "current": [-1, 0, 1]})
    with pytest.raises(ValueError):
        electrical.analyze_electrical(raw, {**IV, **overrides})


@pytest.mark.parametrize(
    "current",
    [
        pd.date_range("2020-01-01", periods=3, freq="s"),
        pd.to_timedelta([0, 1, 2], unit="s"),
        [1 + 2j, 2 + 4j, 3 + 6j],
    ],
)
def test_iv_rejects_dates_durations_and_complex_signals(current):
    raw = pd.DataFrame({"curve_id": ["001"] * 3, "voltage": [-10, 0, 10], "current": current})
    features = electrical.analyze_electrical(raw, IV).features
    assert features.loc[0, "status"] == "invalid"
    assert pd.isna(features.loc[0, "conductance_S"])


def test_native_form_switches_modes_and_emits_strict_report_json():
    from lfx.custom.eval import eval_custom_component_code
    from lfx.schema import DataFrame

    source = Path(__file__).resolve().parents[1] / "components" / "materials_batch" / "electrical.py"
    component = eval_custom_component_code(source.read_text(encoding="utf-8"))
    raw = DataFrame({"curve_id": ["001"] * 3, "voltage": [-10, 0, 10], "current": [3, 3, 3]})
    node = component().set(input_table=raw, **{key: str(value) for key, value in IV.items()})
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert template["voltage_min"]["show"] and not template["light_on"]["show"]
    updated = node.update_build_config(template, "photoresponse", "mode")
    assert updated["light_on"]["show"] and not updated["voltage_min"]["show"]
    assert node.build_features().curve_id.tolist() == ["001"]
    report = node.build_report().data
    assert report["operation"] == "materials.electrical"
    assert report["data"]["statuses"][0]["status"] == "partial"
    assert report["features_contract"]["granularity"] == "curve"
    assert len(report["features_fingerprint"]) == 64
    assert report["features_preview"]["records"][0]["resistance_ohm"] is None
    json.dumps(report, allow_nan=False)
