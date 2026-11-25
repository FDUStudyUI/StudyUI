"""Analytic counterexamples for candidate, threshold and descriptive uncertainty."""

import numpy as np
import pandas as pd
import pytest

from materials_quality.science.materials import spectra, xrd
from materials_quality.science.materials_curves import peak_records
from materials_quality.science.spectrum_batch import analyze_spectra


def measured(centers=(710,), *, external=0):
    x = np.arange(450.0, 901.0)
    rows = []
    for i, center in enumerate(centers):
        y = 2 * np.exp(-0.5 * ((x - center) / 5) ** 2)
        y += external * np.exp(-0.5 * ((x - 530) / 5) ** 2)
        rows.append(pd.DataFrame({"curve_id": f"00{i}", "group": "a", "x": x, "y": y}))
    return pd.concat(rows, ignore_index=True)


def options(**extra):
    return {"x_unit": "nm", "intensity_unit": "counts", "lambda10_window_nm": [650, 850], **extra}


def test_external_peak_interference_is_diagnosed_and_explicit_threshold_is_fixed():
    low = analyze_spectra(measured((730,), external=10), options())
    high = analyze_spectra(measured((730,), external=100), options())
    assert low.data["curve_summary"][0]["lambda10_nm"] == 730
    assert high.data["curve_summary"][0]["lambda10_nm"] is None
    assert low.data["curve_summary"][0]["peak_detection"]["effective_prominence"] == pytest.approx(0.5)
    assert high.data["curve_summary"][0]["peak_detection"]["effective_prominence"] == pytest.approx(5)
    for amplitude in (10, 100):
        result = analyze_spectra(measured((730,), external=amplitude), options(prominence=0.5))
        row = result.data["curve_summary"][0]
        assert row["window_candidate_nm"] == row["lambda10_nm"] == 730
        assert row["peak_detection"]["prominence_mode"] == "absolute"
        assert row["peak_detection"]["effective_prominence"] == 0.5


@pytest.mark.parametrize("rule, expected", [("highest_prominence", 730), ("redmost", 790)])
def test_competing_candidates_preserve_rules_aliases_and_complete_candidate_set(rule, expected):
    source = measured((730,))
    source["y"] += np.exp(-0.5 * ((source.x - 790) / 5) ** 2)
    result = analyze_spectra(source, options(prominence=0.5, lambda10_selection=rule))
    row = result.data["curve_summary"][0]
    assert row["window_candidate_nm"] == row["lambda10_nm"] == expected
    assert row["selection_rule"] == row["lambda10_method"] == rule
    assert row["candidate_count"] == row["lambda10_candidate_count"] == 2
    assert row["ambiguous"] is row["lambda10_ambiguous"] is True
    assert row["detection_status"] == row["lambda10_status"] == "ambiguous_candidate"
    assert [p["position_nm"] for p in row["window_candidates"]] == [730, 790]
    assert all(p["source_index"] >= 0 and "prominence" in p for p in row["window_candidates"])
    assert result.features.window_candidate_nm.tolist() == [expected, expected]
    assert result.features.attrs["units"]["window_candidate_nm"] == "nm"


@pytest.mark.parametrize("n", [1, 2])
def test_small_curve_samples_do_not_produce_zero_width_or_ordinary_bootstrap_ci(n):
    result = analyze_spectra(measured((710, 720)[:n]), options(bootstrap_samples=200))
    row = result.data["group_summary"][0]
    assert row["window_candidate_nm_ci_low"] is None
    assert row["window_candidate_nm_ci_high"] is None
    assert row["window_candidate_nm_ci_status"] == "insufficient_sample_size"
    assert row["window_candidate_nm_ci_reason"]
    assert "independent curve" not in row["statistics_unit"]


def test_degenerate_resampling_withholds_interval_even_for_three_declared_units():
    result = analyze_spectra(
        measured((710, 710, 710)), options(bootstrap_samples=200, bootstrap_independence_confirmed=True)
    )
    row = result.data["group_summary"][0]
    assert row["lambda10_nm_ci_low"] is None
    assert row["lambda10_nm_ci_status"] == "degenerate_resampling"


def test_curve_count_does_not_establish_independence_for_inference():
    row = analyze_spectra(measured((700, 710, 720)), options(bootstrap_samples=200)).data["group_summary"][0]
    assert row["lambda10_nm_ci_status"] == "independence_not_declared"
    assert row["lambda10_nm_ci_low"] is None


def test_declared_nonconstant_curve_bootstrap_is_seeded_and_estimable():
    cfg = options(bootstrap_samples=200, bootstrap_seed=42, bootstrap_independence_confirmed=True)
    first = analyze_spectra(measured((700, 710, 720)), cfg).data["group_summary"]
    second = analyze_spectra(measured((700, 710, 720)), cfg).data["group_summary"]
    assert first == second
    row = first[0]
    assert row["lambda10_nm_ci_status"] == "estimated"
    assert 700 <= row["lambda10_nm_ci_low"] < row["lambda10_nm_ci_high"] <= 720


@pytest.mark.parametrize("operation", [spectra, xrd])
def test_threshold_diagnostics_exist_without_detected_peaks(operation):
    result = operation(pd.DataFrame({"x": np.arange(7), "y": np.zeros(7)}), config={"prominence": 0.5})
    assert result.data["peaks"] == []
    assert result.data["peak_detection"]["effective_prominence"] == 0.5
    assert result.data["peak_detection"]["prominence_mode"] == "absolute"


def test_noise_reference_requires_declared_window_and_reports_measured_method():
    x = np.arange(11.0)
    y = np.array([-1, 0, 1, 0, -1, 0, 0, 10, 0, 0, 0.0])
    result = spectra(
        pd.DataFrame({"x": x, "y": y}),
        config={"prominence_mode": "noise_reference", "noise_window": [0, 4], "noise_multiplier": 3},
    )
    meta = result.data["peak_detection"]
    assert meta["effective_prominence"] == pytest.approx(3 * 1.482602218505602)
    assert meta["noise_window"] == [0, 4]
    assert meta["noise_sample_count"] == 5
    assert meta["noise_estimator"] == "median_absolute_deviation_normal_scaled"
    assert [p["position"] for p in result.data["peaks"]] == [7]


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"prominence_mode": "unknown"}, "prominence_mode"),
        ({"prominence_mode": "absolute"}, "prominence"),
        ({"prominence_mode": "noise_reference"}, "noise_window"),
        ({"prominence_mode": "noise_reference", "noise_window": [0, 2]}, "five"),
        ({"prominence_mode": "noise_reference", "noise_window": [0, 6]}, "noise"),
        ({"peak_distance_x": 0}, "peak_distance_x"),
    ],
)
def test_new_peak_controls_reject_missing_or_invalid_configuration(extra, message):
    with pytest.raises(ValueError, match=message):
        spectra(pd.DataFrame({"x": np.arange(7.0), "y": np.zeros(7)}), config=extra)


def test_physical_distance_suppresses_close_peaks_on_uneven_grid_only():
    x = np.array([0, 1, 2, 3, 4, 4.1, 4.2, 4.3, 4.4, 10, 11, 12, 13.0])
    y = np.array([0, 0, 5, 0, 0, 4, 0, 3, 0, 0, 2, 0, 0.0])
    old = peak_records(x, y, {"prominence": 0.5, "peak_distance": 2})
    assert [p["position"] for p in old] == [2, 4.1, 4.3, 11]
    physical = peak_records(x, y, {"prominence": 0.5, "peak_distance_x": 2})
    assert [p["position"] for p in physical] == [2, 4.1, 11]


def test_detection_denominators_separate_failures_and_skips_from_nondetections():
    source = measured((710, 720, 730, 740, 750))
    source.loc[source.curve_id == "001", "y"] = 0
    source.loc[source.curve_id == "002", "y"] += np.exp(-0.5 * ((source.x - 790) / 5) ** 2)
    source.loc[source.curve_id == "003", "y"] = np.nan
    result = analyze_spectra(source, options(prominence=0.5, on_error="stop"))
    row = result.data["group_summary"][0]
    assert {
        key: row[key]
        for key in (
            "n_total",
            "n_eligible",
            "n_detected",
            "n_ambiguous",
            "n_no_candidate",
            "n_failed",
            "n_skipped",
        )
    } == {
        "n_total": 5,
        "n_eligible": 3,
        "n_detected": 2,
        "n_ambiguous": 1,
        "n_no_candidate": 1,
        "n_failed": 1,
        "n_skipped": 1,
    }
    assert row["observed_detection_fraction"] == pytest.approx(2 / 3)
    assert row["ambiguous_in_descriptive_statistics"] is True
    assert len(result.data["peak_detection"]) == 3


def test_legal_long_table_repeated_curve_ids_and_boundary_candidates_are_preserved():
    result = analyze_spectra(measured((710,)), options(lambda10_window_nm=[710, 850], prominence=0.5))
    row = result.data["curve_summary"][0]
    assert result.data["counts"]["completed"] == 1
    assert row["n_points"] == 451
    assert row["candidate_at_window_edge"] is True
    assert row["window_candidates"][0]["at_window_edge"] is True


def test_detection_fraction_without_window_counts_completed_peak_curves():
    source = measured((710, 720))
    source.loc[source.curve_id == "001", "y"] = 0
    result = analyze_spectra(source, {"x_unit": "nm", "intensity_unit": "counts"})
    row = result.data["group_summary"][0]
    assert row["n_detected"] == 1
    assert row["n_no_candidate"] == 1
    assert row["observed_detection_fraction"] == 0.5


def test_candidate_alias_bootstrap_uses_identical_empirical_resamples():
    row = analyze_spectra(
        measured((681, 699, 711, 732, 750, 777, 813)),
        options(bootstrap_samples=37, bootstrap_seed=2, bootstrap_independence_confirmed=True),
    ).data["group_summary"][0]
    assert row["window_candidate_nm_ci_low"] == row["lambda10_nm_ci_low"]
    assert row["window_candidate_nm_ci_high"] == row["lambda10_nm_ci_high"]


def test_sorted_candidates_retain_original_measurement_row_reference():
    source = measured((710,)).iloc[::-1].reset_index(drop=True)
    result = analyze_spectra(source, options(sort=True))
    candidate = result.data["curve_summary"][0]["window_candidates"][0]
    assert candidate["source_index"] == 190
    assert candidate["input_row_position"] == 190
    assert source.iloc[candidate["input_row_position"]].x == 710


@pytest.mark.parametrize("design", ["independent", "paired"])
def test_public_analyzer_cannot_override_known_unit_design_for_bootstrap(design):
    from materials_quality.science.table_contract import attach_contract, make_contract

    table = measured((700, 710, 720))
    table["unit"] = "one-sample"
    table = attach_contract(
        table,
        make_contract(
            table,
            granularity="point",
            roles={"curve_id": "curve_id", "x": "x", "response": "y", "experimental_unit": "unit"},
            experimental_design={"kind": design, "confirmed": True},
        ),
    )
    with pytest.raises(ValueError, match="unit|independent|paired|独立"):
        analyze_spectra(table, options(bootstrap_samples=100, bootstrap_independence_confirmed=True))
    assert analyze_spectra(table, options()).data["counts"]["completed"] == 3


@pytest.mark.parametrize(
    "grain,roles", [("group_summary", {"group": "group"}), ("point", {"x": "y", "response": "x"})]
)
def test_public_analyzer_rejects_wrong_grain_and_conflicting_bindings(grain, roles):
    from materials_quality.science.table_contract import attach_contract, make_contract

    table = measured()
    table = attach_contract(table, make_contract(table, granularity=grain, roles=roles))
    with pytest.raises(ValueError, match="point|role|contract|逐点"):
        analyze_spectra(table, options())


def test_public_analyzer_restores_persistent_contract_units_before_explicit_declarations():
    from materials_quality.science.table_contract import attach_contract, make_contract

    table = measured()
    table = attach_contract(
        table,
        make_contract(
            table,
            granularity="point",
            roles={"curve_id": "curve_id", "x": "x", "response": "y"},
            units_state={"source": "instrument", "units": {"x": "nm", "y": "counts"}},
        ),
    )
    with pytest.raises(ValueError, match="unit|conflict"):
        analyze_spectra(table, options(x_unit="um"))
    result = analyze_spectra(table, {"lambda10_window_nm": [650, 850]})
    assert result.data["x_unit"] == "nm" and result.data["intensity_unit"] == "counts"
    assert result.data["curve_summary"][0]["window_candidate_nm"] == 710
    assert "units" not in table.attrs


def public_clustered_source():
    from materials_quality.science.table_contract import attach_contract, make_contract

    table = measured((700, 710, 720, 730, 740, 750))
    table["sample"] = [101] * (3 * 451) + ["101"] * (3 * 451)
    return attach_contract(
        table,
        make_contract(
            table,
            granularity="point",
            roles={
                "curve_id": "curve_id",
                "x": "x",
                "response": "y",
                "sample_id": "sample",
                "experimental_unit": "sample",
            },
            experimental_design={"kind": "independent", "confirmed": True},
            units_state={"source": "instrument", "units": {"x": "nm", "y": "counts"}},
        ),
    )


def test_public_output_preserves_known_topology_at_point_and_peak_boundaries():
    from materials_quality.context import table_fingerprint
    from materials_quality.science.table_contract import read_contract

    source = public_clustered_source()
    result = analyze_spectra(source, options())
    for grain, frame in (("point", result.table), ("peak", result.features)):
        contract = read_contract(frame)
        assert contract is not None and contract["granularity"] == grain
        assert contract["experimental_design"] == read_contract(source)["experimental_design"]
        column = contract["roles"]["experimental_unit"]
        assert column == contract["roles"]["sample_id"]
        assert frame.drop_duplicates("curve_id")[column].tolist() == [101] * 3 + ["101"] * 3
        changed = frame.copy(deep=True)
        changed.iloc[0, changed.columns.get_loc(column)] = "changed-unit"
        assert table_fingerprint(changed) != table_fingerprint(frame)
    assert result.data["features"][0]["sample"] == 101


def test_public_output_cannot_enable_downstream_ci_on_six_curves_from_two_units(tmp_path):
    from materials_quality.science.visualization import spectra as plot_spectra

    result = analyze_spectra(public_clustered_source(), options())
    with pytest.raises(ValueError, match="experimental unit|aggregate"):
        plot_spectra(
            result.table,
            config={
                "method": "band",
                "band": "ci95",
                "x": "x",
                "y": "smoothed",
                "curve_id": "curve_id",
                "independence_confirmed": True,
                "output_dir": str(tmp_path),
            },
        )
