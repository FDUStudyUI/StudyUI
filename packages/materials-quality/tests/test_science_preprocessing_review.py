import pandas as pd
import pytest
from lfx.schema import DataFrame

from materials_quality.checks import check_duplicates
from materials_quality.science.preprocessing import (
    handle_missing,
    merge_tables,
    normalize_table,
    reshape_table,
)
from materials_quality.units import check_units


@pytest.mark.parametrize("invalid", [None, " "])
def test_unknown_sample_keys_do_not_join_or_impute(invalid):
    left = pd.DataFrame({"id": [invalid], "strength": [350]})
    right = pd.DataFrame({"id": [invalid], "material": ["Fe"]})
    with pytest.raises(ValueError, match="missing"):
        merge_tables(tables=[left, right], config={"on": "id"})
    frame = pd.DataFrame({"id": [invalid, invalid], "y": [100, None]})
    with pytest.raises(ValueError, match="missing"):
        handle_missing(frame, config={"method": "mean", "columns": ["y"], "group_by": ["id"]})


@pytest.mark.parametrize("method", ["ffill", "linear"])
def test_ordered_imputation_refuses_undated_measurement(method):
    frame = pd.DataFrame({"t": pd.to_datetime(["2025-01-01", "2025-01-02", None]), "y": [0, None, 100]})
    with pytest.raises(ValueError, match="missing"):
        handle_missing(
            frame, config={"method": method, "continuous": True, "order_by": "t", "columns": ["y"]}
        )


def test_robust_scaling_cannot_erase_outlier_and_retains_configuration():
    cfg = {"method": "robust", "columns": ["x"]}
    with pytest.raises(ValueError, match="zero.*[Ii][Qq][Rr]"):
        normalize_table(pd.DataFrame({"x": [0, 0, 0, 0, 100]}), config=cfg)
    out = normalize_table(pd.DataFrame({"x": [1, 2, 3]}), config=cfg)
    assert out.data["parameters"] == cfg
    assert out.data["fit_parameters"]["x"]["center"] == 2


def test_nullable_integer_conversion_is_exact_and_nullable_dates_convert():
    frame = pd.DataFrame({"id": ["9007199254740993", None], "date": ["2025-01-01", None]})
    cfg = {"types": {"id": "integer", "date": "datetime"}, "date_formats": {"date": "%Y-%m-%d"}}
    out = reshape_table(frame, config=cfg)
    assert out.table.id.iloc[0] == 9007199254740993
    assert pd.isna(out.table.date.iloc[1]) and pd.isna(out.table.id.iloc[1])
    assert out.table.date.iloc[0] == pd.Timestamp("2025-01-01")


def test_integer_format_and_boolean_coercion_reject_silent_changes():
    for values, target in [
        (["1.0000000000000001", None], "integer"),
        (["inf", "2"], "number"),
        ([True, False], "integer"),
        ([0, 1], "boolean"),
    ]:
        with pytest.raises(ValueError):
            reshape_table(pd.DataFrame({"x": values}), config={"types": {"x": target}})


def test_similarity_tolerance_uses_exact_large_integer_distance():
    table = pd.DataFrame({"id": [2**53, 2**53 + 1]})

    def count(tol):
        return check_duplicates(
            table, columns=["id"], similarity_threshold=1, numeric_tolerances={"id": {"atol": tol}}
        )["metrics"]["similar_pair_count"]

    assert count(0) == 0
    assert count(1) == 1


def test_asof_rejects_ambiguities_and_records_matched_source():
    left = pd.DataFrame({"t": [1.0]})
    cfg = {"method": "asof", "on": "t", "tolerance": 1.0}
    for x in ([1.0, 1.0], [0.5, 1.5]):
        with pytest.raises(ValueError, match="duplicate|ambiguous"):
            merge_tables(tables=[left, pd.DataFrame({"t": x, "B": [10, 20]})], config=cfg)
    result = merge_tables(
        tables=[
            pd.DataFrame({"t": [1.0, 10.0]}),
            pd.DataFrame({"t": [0.25, 1.5], "B": [10, 20]}, index=[8, 8]),
        ],
        config=cfg,
    )
    matched, missing = result.data["matches"]
    assert matched["left_position"] == 0 and matched["right_position"] == 1
    assert matched["right_coordinate"] == 1.5 and matched["distance"] == 0.5
    assert missing["right_position"] is None and missing["distance"] is None


def test_bad_unit_does_not_destroy_report_or_expose_unconverted_output():
    from components.materials_quality import MaterialUnitCheck

    args = {"source_units_json": '{"x":"m"}', "expected_units_json": '{"x":"mm"}'}
    bad = MaterialUnitCheck().set(input_table=DataFrame({"x": [1, "?"]}), convert_values=True, **args)
    report = bad.build_report().data
    assert not report["passed"] and not report["metrics"]["converted"]
    assert any(f["code"] == "UNIT_VALUE_FORMAT" for f in report["findings"])
    assert bad.build_converted_table().empty
    disabled = MaterialUnitCheck().set(input_table=DataFrame({"x": [1]}), convert_values=False, **args)
    assert disabled.build_converted_table().empty


def test_optional_conversion_strict_boolean_and_mixed_unit_message():
    table = pd.DataFrame({"x": [1, "2 cm"]})
    args = {"source_units": {"x": "m"}, "expected_units": {"x": "mm"}}
    with pytest.raises(ValueError, match="bool"):
        check_units(table, convert_values="false", **args)
    report = check_units(table, convert_values=True, **args)
    assert report["metrics"]["converted"]
    assert report["metrics"]["conversion_records"][1]["after"] == 20
    assert all("were not converted" not in f["reason"] for f in report["findings"])
