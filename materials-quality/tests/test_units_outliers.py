import json

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from materials_quality.outliers import check_outliers
from materials_quality.units import check_units


def test_compatible_units_are_verified_without_changing_values():
    df = pd.DataFrame({"stress": [1.0, 2.0], "temperature": [20.0, 25.0]})
    before = df.copy(deep=True)
    r = check_units(
        df,
        source_units={"stress": "MPa", "temperature": "℃"},
        expected_units={"stress": "Pa", "temperature": "K"},
    )
    assert r["passed"] is True
    assert r["metrics"]["columns"]["stress"]["compatible"] is True
    assert r["metrics"]["columns"]["temperature"]["compatible"] is True
    assert_frame_equal(df, before)


def test_inline_mixed_units_and_incompatible_dimensions_are_flagged():
    df = pd.DataFrame({"stress": ["1 MPa", "2000 kPa", "3 s", None]})
    r = check_units(df, source_units={}, expected_units={"stress": "Pa"})
    assert r["passed"] is False
    assert {f["code"] for f in r["findings"]} == {"UNIT_MIXED", "UNIT_INCOMPATIBLE"}
    incompatible = next(f for f in r["findings"] if f["code"] == "UNIT_INCOMPATIBLE")
    assert incompatible["row_position"] == 2


def test_metadata_and_inline_unit_conflict_is_explicit():
    r = check_units(pd.DataFrame({"x": ["1 s"]}), source_units={"x": "m"}, expected_units={"x": "m"})
    assert "UNIT_INCOMPATIBLE" in [f["code"] for f in r["findings"]]


def test_unitless_numeric_values_without_declared_source_are_unverified():
    r = check_units(pd.DataFrame({"x": [1, 2]}), source_units={}, expected_units={"x": "MPa"})
    assert r["passed"] is False
    assert "UNIT_UNSPECIFIED" in [f["code"] for f in r["findings"]]


def test_unknown_inline_unit_is_a_finding_not_a_crash():
    r = check_units(pd.DataFrame({"x": ["2 mysteryunit"]}), source_units={}, expected_units={"x": "Pa"})
    assert [f["code"] for f in r["findings"]] == ["UNIT_UNKNOWN"]


@pytest.mark.parametrize(
    "source,expected", [({"x": "mysteryunit"}, {"x": "Pa"}), ({}, {}), ({}, {"nope": "Pa"})]
)
def test_bad_unit_configuration_raises(source, expected):
    with pytest.raises(ValueError):
        check_units(pd.DataFrame({"x": [1]}), source_units=source, expected_units=expected)


def test_units_do_not_treat_undefined_compound_quantity_as_numeric():
    r = check_units(
        pd.DataFrame({"x": ["sample-A", "NaN Pa", "2 Pa"]}), source_units={}, expected_units={"x": "Pa"}
    )
    assert r["passed"] is False
    assert {f["row_position"] for f in r["findings"]} >= {0, 1}


def test_iqr_bounds_are_hand_checked_and_input_index_is_preserved():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 100]}, index=["a"] * 5)
    before = df.copy(deep=True)
    r = check_outliers(df, columns=["x"], method="iqr")
    assert [f["row_position"] for f in r["findings"]] == [4]
    threshold = r["metrics"]["thresholds"][0]
    assert threshold["lower"] == -1.0
    assert threshold["upper"] == 7.0
    assert_frame_equal(df, before)


def test_mad_detects_outlier_with_nonzero_median_deviation():
    r = check_outliers(pd.DataFrame({"x": [1, 2, 3, 4, 100]}), columns=["x"], method="mad")
    assert [f["row_position"] for f in r["findings"]] == [4]


def test_zero_mad_flags_deviations_and_documents_fallback():
    r = check_outliers(pd.DataFrame({"x": [1, 1, 1, 1, 9]}), columns=["x"], method="mad")
    assert [f["row_position"] for f in r["findings"]] == [4]
    assert r["metrics"]["thresholds"][0]["fallback"] == "deviations_from_constant_median"
    assert check_outliers(pd.DataFrame({"x": [1] * 5}), columns=["x"], method="mad")["passed"] is True


def test_physical_range_includes_endpoints_and_reports_bad_numeric_values():
    df = pd.DataFrame({"x": [0, 100, -1, 101, np.inf, "bad", None]})
    r = check_outliers(df, columns=["x"], method="range", bounds={"x": {"min": 0, "max": 100}})
    assert sorted((f["row_position"], f["code"]) for f in r["findings"]) == [
        (2, "OUTLIER_RANGE"),
        (3, "OUTLIER_RANGE"),
        (4, "NON_FINITE"),
        (5, "NON_NUMERIC"),
    ]
    json.dumps(r, allow_nan=False)


def test_grouped_outliers_do_not_compare_different_material_baselines():
    df = pd.DataFrame({"material": ["A"] * 4 + ["B"] * 4, "x": [1, 1, 1, 2, 100, 100, 100, 101]})
    r = check_outliers(
        df, columns=["x"], method="range", bounds={"x": {"min": 0, "max": 200}}, group_by=["material"]
    )
    assert r["passed"] is True
    assert len(r["metrics"]["thresholds"]) == 2


def test_small_baseline_is_reported_as_insufficient():
    r = check_outliers(pd.DataFrame({"x": [1, 2]}), columns=["x"], method="iqr")
    assert r["passed"] is False
    assert [f["code"] for f in r["findings"]] == ["INSUFFICIENT_BASELINE"]


@pytest.mark.parametrize("method", ["iqr", "mad"])
def test_extreme_finite_values_cannot_silently_pass_with_overflowed_statistics(method):
    r = check_outliers(pd.DataFrame({"x": [1e308, 1e308, 1e308, -1e308]}), columns=["x"], method=method)
    assert r["passed"] is False
    assert "NUMERICAL_LIMIT" in [f["code"] for f in r["findings"]]
    json.dumps(r, allow_nan=False)


def test_physical_range_preserves_exact_integer_information_beyond_float_precision():
    r = check_outliers(
        pd.DataFrame({"x": ["9007199254740993"]}),
        columns=["x"],
        method="range",
        bounds={"x": {"max": 9007199254740992}},
    )
    assert r["passed"] is False
    assert [f["code"] for f in r["findings"]] == ["OUTLIER_RANGE"]


@pytest.mark.parametrize("method", ["iqr", "mad"])
@pytest.mark.parametrize(
    "values",
    [
        ["9007199254740992"] * 4 + ["9007199254740993"],
        ["1e-1000"] * 4 + ["9e-1000"],
    ],
)
def test_statistical_conversion_cannot_collapse_distinct_values_and_pass(method, values):
    r = check_outliers(pd.DataFrame({"x": values}), columns=["x"], method=method)
    assert r["passed"] is False
    assert "NUMERICAL_LIMIT" in [f["code"] for f in r["findings"]]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"columns": [], "method": "iqr"},
        {"columns": ["nope"], "method": "iqr"},
        {"columns": ["x"], "method": "iqr", "multiplier": -1},
        {"columns": ["x"], "method": "mad", "mad_threshold": float("nan")},
        {"columns": ["x"], "method": "range", "bounds": {}},
        {"columns": ["x"], "method": "range", "bounds": {"x": {"min": 10, "max": 1}}},
        {"columns": ["x"], "method": "unknown"},
    ],
)
def test_invalid_outlier_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        check_outliers(pd.DataFrame({"x": [1, 2, 3]}), **kwargs)


@pytest.mark.parametrize(
    "check,kwargs",
    [
        (check_units, {"source_units": {"x": "Pa"}, "expected_units": {"x": "Pa"}}),
        (check_outliers, {"columns": ["x"], "method": "iqr"}),
    ],
)
def test_empty_units_and_outliers_do_not_pass(check, kwargs):
    assert check(pd.DataFrame({"x": []}), **kwargs)["passed"] is False
