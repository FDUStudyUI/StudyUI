import asyncio
import json

import numpy as np
import pandas as pd
import pytest


def curves(centers=(550, 650), count=None):
    x = np.linspace(400, 800, 401)
    return pd.concat(
        [
            pd.DataFrame(
                {
                    "curve_id": f"{i:04d}",
                    "group": "A" if i % 2 == 0 else "B",
                    "x": x,
                    "y": 2 + 10 * np.exp(-0.5 * ((x - center) / 15) ** 2),
                }
            )
            for i, center in enumerate(centers if count is None else [600] * count)
        ],
        ignore_index=True,
    )


def options(**changes):
    return {
        "x_unit": "nm",
        "intensity_unit": "counts",
        "baseline": {"method": "constant", "value": 2},
        **changes,
    }


def test_complete_curves_are_analyzed_independently_with_gaussian_truth():
    from materials_quality.science.spectrum_batch import analyze_spectra

    source = curves()
    result = analyze_spectra(source, options())
    assert len(result.table) == len(source)
    assert result.table.groupby("curve_id")["source_row"].count().tolist() == [401, 401]
    feature = result.features.set_index("curve_id")
    assert feature["peak_position"].tolist() == [550, 650]
    assert feature["fwhm"].tolist() == pytest.approx([35.3223, 35.3223], rel=1e-3)
    assert feature["area"].tolist() == pytest.approx([375.9942, 375.9942], rel=1e-4)
    assert feature["baseline"].tolist() == [2, 2]
    assert result.data["counts"] == {"total": 2, "completed": 2, "failed": 0, "skipped": 0}
    assert result.data["lambda10_definition"] == "none"
    assert "lambda10" not in feature
    pd.testing.assert_frame_equal(source, curves())
    json.dumps(result.data, allow_nan=False)


def test_1360_curves_return_full_data_without_plots_and_group_n_counts_curves():
    from materials_quality.science.spectrum_batch import analyze_spectra

    result = analyze_spectra(curves(count=1360), options())
    assert len(result.features) == 1360
    assert result.table["curve_id"].nunique() == 1360
    assert len(result.table) == 1360 * 401
    assert result.artifacts == []
    assert [r["n_curves"] for r in result.data["group_summary"]] == [680, 680]


def test_duplicate_coordinates_fail_only_the_affected_curve_and_stop_is_explicit():
    from materials_quality.science.spectrum_batch import analyze_spectra

    source = curves()
    source.loc[1, "x"] = source.loc[0, "x"]
    result = analyze_spectra(source, options())
    assert result.data["counts"]["failed"] == 1
    assert result.features["curve_id"].tolist() == ["0001"]
    assert result.data["curve_summary"][0]["status"] == "failed"
    assert "strictly increasing" in result.data["curve_summary"][0]["error"]
    stopped = analyze_spectra(source, options(on_error="stop"))
    assert stopped.data["counts"] == {"total": 2, "completed": 0, "failed": 1, "skipped": 1}
    assert stopped.data["execution_status"] == "failed"


@pytest.mark.parametrize("change", ["missing_id", "missing_group", "mixed_group", "ambiguous_id"])
def test_missing_or_heterogeneous_curve_keys_are_rejected_before_processing(change):
    from materials_quality.science.spectrum_batch import analyze_spectra

    source = curves()
    if change == "missing_id":
        source.loc[0, "curve_id"] = None
    elif change == "missing_group":
        source.loc[0, "group"] = None
    elif change == "mixed_group":
        source.loc[0, "group"] = "other"
    else:
        source["curve_id"] = source["curve_id"].astype(object)
        source.loc[0, "curve_id"] = 1
        source.loc[1, "curve_id"] = "1"
    with pytest.raises(ValueError, match="curve|group|ambiguous"):
        analyze_spectra(source, options())


def test_units_are_required_and_lambda10_rejects_wavenumber_without_guessing():
    from materials_quality.science.spectrum_batch import analyze_spectra

    with pytest.raises(ValueError, match="unit"):
        analyze_spectra(curves())
    result = analyze_spectra(curves(), options(x_unit="cm^-1"))
    assert "peak_position_nm" not in result.features
    with pytest.raises(ValueError, match="wavelength"):
        analyze_spectra(curves(), options(x_unit="cm^-1", lambda10_window_nm=[650, 850]))


def test_lambda10_selects_coupled_mode_candidate_only_in_explicit_window():
    from materials_quality.science.spectrum_batch import analyze_spectra

    source = curves((530,))
    source["y"] += 5 * np.exp(-0.5 * ((source.x - 710) / 12) ** 2)
    result = analyze_spectra(source, options(lambda10_window_nm=[650, 850]))
    summary = result.data["curve_summary"][0]
    assert summary["peak_position"] == 530
    assert summary["lambda10_nm"] == 710
    assert summary["lambda10_candidate_count"] == 1
    assert not summary["lambda10_ambiguous"]
    assert summary["lambda10_method"] == "highest_prominence"
    assert result.features.lambda10_nm.tolist() == [710, 710]
    assert result.data["lambda10_definition"] == "coupled_mode_candidate"
    assert "lambda10_left" not in result.features
    empty = analyze_spectra(source, options(lambda10_window_nm=[750, 780]))
    assert empty.data["curve_summary"][0]["lambda10_nm"] is None
    assert any("candidate" in warning for warning in empty.warnings)


def test_lambda10_length_conversion_ambiguity_and_selection_rule():
    from materials_quality.science.spectrum_batch import analyze_spectra

    source = curves((680,))
    source["y"] += 5 * np.exp(-0.5 * ((source.x - 740) / 8) ** 2)
    source["x"] /= 1000
    result = analyze_spectra(source, options(x_unit="um", lambda10_window_nm=[650, 780]))
    summary = result.data["curve_summary"][0]
    assert summary["lambda10_nm"] == pytest.approx(680)
    assert summary["lambda10_candidate_count"] == 2 and summary["lambda10_ambiguous"]
    assert "peak_position_nm" not in result.features
    assert result.features.attrs["units"]["lambda10_nm"] == "nm"
    redmost = analyze_spectra(
        source, options(x_unit="um", lambda10_window_nm=[650, 780], lambda10_selection="redmost")
    )
    assert redmost.data["curve_summary"][0]["lambda10_nm"] == pytest.approx(740)
    with pytest.raises(ValueError, match="window"):
        analyze_spectra(source, options(x_unit="um", lambda10_window_nm=[780, 650]))


def test_no_peak_curves_retain_explicit_record_and_input_row_positions():
    from materials_quality.science.spectrum_batch import analyze_spectra

    source = curves((600,))
    source.index = ["same"] * len(source)
    source["y"] = 2
    result = analyze_spectra(source, options(lambda10_window_nm=[650, 780]))
    assert result.features.iloc[0]["status"] == "no_peaks"
    assert result.data["curve_summary"][0]["n_points"] == 401
    assert result.table.input_row_position.tolist() == list(range(401))


def test_group_and_normalized_curve_units_are_explicit_and_only_reference_existing_columns():
    from materials_quality.science.spectrum_batch import analyze_spectra

    result = analyze_spectra(curves(), options(normalization="max", lambda10_window_nm=[500, 750]))
    assert result.table.attrs["units"]["normalized"] == "dimensionless"
    units = result.data["group_summary_units"]
    assert units["peak_position_mean"] == "nm"
    assert units["area_mean"] == "counts*nm"
    assert units["lambda10_nm_mean"] == "nm"
    assert set(units) <= set(pd.DataFrame(result.data["group_summary"]).columns)


def test_group_summary_uses_one_primary_peak_per_curve_and_seeded_bootstrap():
    from materials_quality.science.spectrum_batch import analyze_spectra

    source = curves((550, 560, 570, 580))
    x = source.x.to_numpy()
    source["y"] += 4 * np.exp(-0.5 * ((x - 720) / 8) ** 2)
    result = analyze_spectra(source, options(bootstrap_samples=50, bootstrap_seed=42))
    assert len(result.features) == 8
    group = result.data["group_summary"][0]
    assert group["n_curves"] == 2
    assert group["peak_position_mean"] == 560
    assert group["peak_position_q50"] == 560
    assert group["peak_position_ci_low"] >= 550 and group["peak_position_ci_high"] <= 570
    again = analyze_spectra(source, options(bootstrap_samples=50, bootstrap_seed=42))
    assert result.data["group_summary"] == again.data["group_summary"]


def test_native_component_uses_controls_runs_real_sdk_and_serializes_graph():
    from lfx.custom.eval import eval_custom_component_code
    from lfx.graph import Graph
    from lfx.schema import Data, DataFrame, Message

    from components.materials_batch.batch_spectrum_analyzer import BatchSpectrumAnalyzer

    node = BatchSpectrumAnalyzer().set(
        input_table=DataFrame(curves()),
        x_unit="nm",
        intensity_unit="counts",
        baseline_method="constant",
        baseline_value=2,
    )
    fields = node.to_frontend_node()["data"]["node"]["template"]
    assert fields["baseline_method"]["options"]
    assert fields["area_ranges"]["table_schema"]
    assert "config_json" not in fields
    results, _ = asyncio.run(node.build_results())
    assert set(results) == {"features", "curves", "groups", "report", "summary"}
    assert isinstance(results["features"], DataFrame) and len(results["features"]) == 2
    assert isinstance(results["report"], Data) and isinstance(results["summary"], Message)
    payload = Graph(start=node, end=node).dump()
    assert len(payload["data"]["nodes"]) == 1
    code = payload["data"]["nodes"][0]["data"]["node"]["template"]["code"]["value"]
    restored = eval_custom_component_code(code)().set(
        input_table=DataFrame(curves()), x_unit="nm", intensity_unit="counts"
    )
    assert len(restored.build_features()) == 2
