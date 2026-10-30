import json

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from materials_quality.aggregate import aggregate_reports
from materials_quality.checks import check_duplicates, check_missing, check_schema, check_types


def codes(report):
    return [f["code"] for f in report["findings"]]


def test_required_alias_is_resolved_without_renaming_source():
    df = pd.DataFrame({"样品编号": ["A"], "stress": [10]})
    before = df.copy(deep=True)
    result = check_schema(df, required_columns=["sample_id", "stress"], aliases={"sample_id": ["样品编号"]})
    assert result["passed"] is True
    assert result["metrics"]["resolved_columns"] == {"sample_id": "样品编号", "stress": "stress"}
    assert_frame_equal(df, before)


def test_schema_reports_missing_and_ambiguous_aliases():
    df = pd.DataFrame({"样品": ["A"], "编号": ["B"]})
    report = check_schema(
        df, required_columns=["sample_id", "stress"], aliases={"sample_id": ["样品", "编号"]}
    )
    assert set(codes(report)) == {"AMBIGUOUS_COLUMN", "MISSING_COLUMN"}
    assert report["passed"] is False


def test_canonical_and_alias_both_present_is_ambiguous():
    report = check_schema(
        pd.DataFrame({"id": [1], "编号": [2]}), required_columns=["id"], aliases={"id": ["编号"]}
    )
    assert codes(report) == ["AMBIGUOUS_COLUMN"]


def test_one_source_column_cannot_satisfy_two_distinct_required_fields():
    with pytest.raises(ValueError, match="alias"):
        check_schema(
            pd.DataFrame({"x": [1]}),
            required_columns=["stress", "strain"],
            aliases={"stress": ["x"], "strain": ["x"]},
        )


@pytest.mark.parametrize(
    "checker,kwargs",
    [
        (check_schema, {"required_columns": ["x"]}),
        (check_missing, {}),
        (check_types, {"expectations": {"x": "number"}}),
        (check_duplicates, {}),
    ],
)
def test_empty_table_never_reports_all_clear(checker, kwargs):
    result = checker(pd.DataFrame({"x": []}), **kwargs)
    assert result["passed"] is False
    assert "EMPTY_TABLE" in codes(result)


def test_missing_nulls_tokens_patterns_and_duplicate_indexes():
    df = pd.DataFrame({"a": [None, "", "NA", 3], "b": [1, np.nan, 2, 3]}, index=[7, 7, 9, 10])
    before = df.copy(deep=True)
    r = check_missing(df)
    assert r["metrics"]["columns"]["a"] == {"missing_count": 2, "missing_ratio": 0.5}
    assert r["metrics"]["columns"]["b"] == {"missing_count": 1, "missing_ratio": 0.25}
    assert r["metrics"]["affected_rows"] == 2
    assert r["metrics"]["patterns"] == [
        {"columns": ["a"], "row_count": 1},
        {"columns": ["a", "b"], "row_count": 1},
    ]
    assert [f["row_position"] for f in r["findings"]] == [0, 1, 1]
    assert_frame_equal(df, before)
    explicit = check_missing(df, missing_tokens=["", "NA"])
    assert explicit["metrics"]["columns"]["a"]["missing_count"] == 3


def test_missing_group_counts_use_rows_with_missing_group_keys():
    df = pd.DataFrame({"group": ["A", "A", None], "x": [None, 2, None]})
    r = check_missing(df, columns=["x"], group_by=["group"])
    assert r["metrics"]["groups"] == [
        {
            "group": {"group": "A"},
            "row_count": 2,
            "columns": {"x": {"missing_count": 1, "missing_ratio": 0.5}},
        },
        {
            "group": {"group": None},
            "row_count": 1,
            "columns": {"x": {"missing_count": 1, "missing_ratio": 1.0}},
        },
    ]


def test_explicit_numeric_missing_marker_matches_float_csv_cells():
    # CSV parsers can promote an integer sentinel to float after encountering NA.
    df = pd.DataFrame({"sensor": [-200.0, 12.0, None], "id": ["NA", "B", "C"]})
    r = check_missing(df, missing_tokens=["", "-200"])
    assert r["metrics"]["columns"]["sensor"]["missing_count"] == 2
    assert r["metrics"]["columns"]["id"]["missing_count"] == 0
    assert check_missing(df)["metrics"]["columns"]["sensor"]["missing_count"] == 1


def test_missing_nested_objects_do_not_trigger_ambiguous_truth_errors():
    r = check_missing(pd.DataFrame({"x": [[1, 2], {"a": 1}, None]}))
    assert r["metrics"]["columns"]["x"]["missing_count"] == 1


def test_bounded_findings_do_not_hide_failure_or_full_counts():
    r = check_missing(pd.DataFrame({"x": [None] * 5}), finding_limit=2)
    assert r["total_findings"] == 5
    assert r["returned_findings"] == 2
    assert r["truncated"] is True
    assert r["passed"] is False


def test_numeric_checks_reject_bool_infinity_and_preserve_large_integer_strings():
    df = pd.DataFrame({"x": [True, "inf", "3.5", "9007199254740993", None]})
    r = check_types(df, expectations={"x": "integer"})
    assert [f["row_position"] for f in r["findings"]] == [0, 1, 2]
    assert r["metrics"]["columns"]["x"]["checked_count"] == 4


def test_explicit_date_format_category_boolean_and_no_coercion():
    df = pd.DataFrame(
        {
            "date": ["2026-10-30", "30/10/2026", None],
            "phase": ["alpha", "gamma", "beta"],
            "flag": [True, "false", "perhaps"],
        }
    )
    before = df.copy(deep=True)
    r = check_types(
        df,
        expectations={
            "date": {"type": "datetime", "format": "%Y-%m-%d"},
            "phase": {"type": "category", "allowed": ["alpha", "beta"]},
            "flag": "boolean",
        },
    )
    assert {(f["column"], f["row_position"]) for f in r["findings"]} == {
        ("date", 1),
        ("phase", 1),
        ("flag", 2),
    }
    assert_frame_equal(df, before)


@pytest.mark.parametrize(
    "expectations",
    [
        {},
        {"x": "mystery"},
        {"x": {"type": "datetime"}},
        {"x": {"type": "category", "allowed": []}},
        {"missing": "number"},
    ],
)
def test_invalid_type_rules_are_configuration_errors(expectations):
    with pytest.raises(ValueError):
        check_types(pd.DataFrame({"x": [1]}), expectations=expectations)


def test_string_rule_does_not_accept_numeric_values():
    r = check_types(pd.DataFrame({"x": ["1", 1, None]}), expectations={"x": "string"})
    assert [f["row_position"] for f in r["findings"]] == [1]


def test_duplicates_marks_every_member_without_dropping_rows():
    df = pd.DataFrame({"id": ["A", "A", "B"], "value": [1, 2, 3]}, index=[5, 5, 5])
    before = df.copy(deep=True)
    r = check_duplicates(df, columns=["id"])
    assert r["metrics"]["duplicate_rows"] == 2
    assert r["metrics"]["duplicate_groups"] == 1
    assert [f["row_position"] for f in r["findings"]] == [0, 1]
    assert check_duplicates(df)["passed"] is True
    assert_frame_equal(df, before)


def test_exact_duplicates_include_missing_values_and_multiple_groups():
    df = pd.DataFrame({"x": [None, None, 3, 3, 4]})
    r = check_duplicates(df)
    assert r["metrics"]["duplicate_rows"] == 4
    assert r["metrics"]["duplicate_groups"] == 2


@pytest.mark.parametrize("kwargs", [{"columns": ["unknown"]}, {"finding_limit": 0}, {"finding_limit": True}])
def test_invalid_check_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        check_missing(pd.DataFrame({"x": [1]}), **kwargs)


def test_duplicate_column_labels_are_rejected_before_ambiguous_selection():
    with pytest.raises(ValueError, match="duplicate"):
        check_missing(pd.DataFrame([[1, 2]], columns=["x", "x"]))


def test_reports_are_strict_json_even_with_timestamp_indexes():
    df = pd.DataFrame({"x": [None]}, index=[pd.Timestamp("2026-10-30")])
    text = json.dumps(check_missing(df), ensure_ascii=False, allow_nan=False)
    assert "2026-10-30" in text


def test_aggregate_preserves_per_check_verdicts_and_counts():
    dirty = check_missing(pd.DataFrame({"x": [None, None]}), finding_limit=1)
    clean = check_duplicates(pd.DataFrame({"x": [1, 2]}))
    r = aggregate_reports([dirty, clean], finding_limit=1)
    assert r["passed"] is False
    assert r["metrics"]["completed_checks"] == 2
    assert r["metrics"]["failed_checks"] == 1
    assert r["total_findings"] == 2
    assert r["returned_findings"] == 1
    assert r["truncated"] is True
    assert len(r["checks"]) == 2


def test_zero_checks_is_insufficient_not_success():
    r = aggregate_reports([])
    assert r["passed"] is False
    assert r["execution_status"] == "insufficient"


@pytest.mark.parametrize("bad", [{}, {"schema_version": "999"}, {"error": "check unavailable"}])
def test_aggregate_rejects_malformed_reports(bad):
    with pytest.raises(ValueError):
        aggregate_reports([bad])


def test_aggregate_rejects_a_pass_flag_that_contradicts_its_findings():
    report = check_missing(pd.DataFrame({"x": [None]}))
    report["passed"] = True
    with pytest.raises(ValueError):
        aggregate_reports([report])


@pytest.mark.parametrize(
    "mutation",
    [
        {"dataset": {}},
        {"dataset": {"rows": True, "columns": 1}},
        {"dataset": {"rows": 0, "columns": 1}},
        {"total_findings": True},
        {"returned_findings": 99},
        {"truncated": True},
    ],
)
def test_aggregate_rejects_inconsistent_native_report_envelopes(mutation):
    report = check_missing(pd.DataFrame({"x": [1]}))
    report.update(mutation)
    with pytest.raises(ValueError):
        aggregate_reports([report])


@pytest.mark.parametrize("field", ["returned_findings", "truncated", "parameters"])
def test_aggregate_rejects_incomplete_contracts(field):
    report = check_missing(pd.DataFrame({"x": [1]}))
    del report[field]
    with pytest.raises(ValueError):
        aggregate_reports([report])
