"""Protect source identity, reproducibility and consistent value semantics."""

from copy import deepcopy
from importlib import import_module

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from materials_quality.aggregate import aggregate_reports


def api():
    return import_module("materials_quality.context")


def rules():
    return {
        "missing_tokens": ["", "-200"],
        "group_by": ["temperature"],
        "checks": {
            "missing": {"columns": ["stress"]},
            "types": {"expectations": {"stress": "number"}},
            "units": {"source_units": {"stress": "MPa"}, "expected_units": {"stress": "Pa"}},
            "outliers": {"columns": ["stress"], "method": "range", "bounds": {"stress": {"min": 0}}},
            "duplicates": {"columns": ["sample_id", "temperature", "replicate"]},
        },
    }


def table():
    return pd.DataFrame(
        {"sample_id": ["A", "A", "A"], "temperature": [25, 25, 80],
         "replicate": [1, 2, 1], "stress": [100, -200, 80]}, index=[7, 7, 9]
    )


def test_fingerprint_is_stable_but_sensitive_to_values_index_order_and_types():
    df = table()
    fingerprint = api().table_fingerprint(df)
    assert len(fingerprint) == 64
    assert api().table_fingerprint(df.copy(deep=True)) == fingerprint
    for changed in [df.iloc[::-1], df.reset_index(drop=True), df.astype({"stress": "str"}),
                    df.assign(stress=df.stress + 1)]:
        assert api().table_fingerprint(changed) != fingerprint


def test_shared_missing_tokens_excluded_from_other_checks_without_mutation():
    df = table()
    before = df.copy(deep=True)
    context = api().make_context(df, rules(), source={"dataset_id": "run-1", "source_name": "raw.csv"})
    reports = [api().run_check(df, name, context=context) for name in rules()["checks"]]
    assert reports[0]["total_findings"] == 1
    assert reports[0]["findings"][0]["row_index"] == 7
    assert all(r["passed"] for r in reports[1:])
    assert reports[2]["metrics"]["columns"]["stress"]["checked_count"] == 2
    assert_frame_equal(df, before)
    summary = aggregate_reports(reports)
    assert summary["provenance_status"] == "verified"
    assert summary["dataset"]["fingerprint"] == context["dataset"]["fingerprint"]


@pytest.mark.parametrize("mutation", ["table", "rules", "source", "fingerprint"])
def test_stale_or_mutated_context_is_rejected(mutation):
    df = table()
    context = api().make_context(df, rules())
    if mutation == "table":
        df.loc[9, "stress"] = 90
    elif mutation == "rules":
        context["rules"]["missing_tokens"] = []
    elif mutation == "source":
        context["source"]["source_name"] = "other.csv"
    else:
        context["dataset"]["fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="context|fingerprint|integrity"):
        api().run_check(df, "missing", context=context)


def test_context_owns_a_snapshot_and_shared_rules_override_local_parameters():
    df, config = table(), rules()
    context = api().make_context(df, config)
    config["missing_tokens"] = []
    report = api().run_check(df, "missing", context=context, parameters={"missing_tokens": []})
    assert report["total_findings"] == 1
    assert report["provenance"]["rule_set"]["rules"]["missing_tokens"] == ["", "-200"]


@pytest.mark.parametrize("mutation", ["unknown", "per_check_token", "per_check_group", "missing_argument"])
def test_rules_fail_closed_for_unknown_or_conflicting_configuration(mutation):
    config = rules()
    if mutation == "unknown":
        config["checks"]["outliers"]["methdo"] = "iqr"
    elif mutation == "per_check_token":
        config["checks"]["missing"]["missing_tokens"] = []
    elif mutation == "per_check_group":
        config["checks"]["outliers"]["group_by"] = []
    else:
        del config["checks"]["types"]["expectations"]
    with pytest.raises(ValueError):
        api().make_context(table(), config)


def test_unconfigured_check_is_not_silently_run_with_local_defaults():
    context = api().make_context(table(), rules())
    with pytest.raises(ValueError, match="schema.*configured"):
        api().run_check(table(), "schema", context=context, parameters={"required_columns": ["sample_id"]})


@pytest.mark.parametrize("difference", ["table", "rules", "source", "mode", "legacy", "duplicate"])
def test_summary_rejects_mixed_identity_or_rule_scope(difference):
    df = table()
    ctx = api().make_context(df, rules())
    first = api().run_check(df, "missing", context=ctx)
    if difference == "table":
        df.loc[9, "stress"] = 90
        ctx = api().make_context(df, rules())
    elif difference == "rules":
        config = rules()
        config["missing_tokens"] = [""]
        ctx = api().make_context(df, config)
    elif difference == "source":
        ctx = api().make_context(df, rules(), source={"source_name": "other.csv"})
    second = api().run_check(df, "duplicates", context=ctx)
    if difference == "mode":
        second = api().run_check(df, "duplicates", parameters={"columns": ["sample_id"]})
    elif difference == "legacy":
        del second["provenance"]
    elif difference == "duplicate":
        second = deepcopy(first)
    with pytest.raises(ValueError):
        aggregate_reports([first, second])


def test_summary_rejects_tampered_effective_parameters():
    report = api().run_check(table(), "missing", context=api().make_context(table(), rules()))
    report["parameters"]["missing_tokens"] = []
    with pytest.raises(ValueError):
        aggregate_reports([report])


def test_local_node_checks_are_traced_without_a_shared_ruleset():
    reports = [api().run_check(table(), "missing"), api().run_check(table(), "duplicates")]
    assert aggregate_reports(reports)["provenance_status"] == "verified"
    assert reports[0]["provenance"]["mode"] == "local"


def test_legacy_only_reports_explicitly_lack_provenance_verification():
    from materials_quality.checks import check_missing

    summary = aggregate_reports([check_missing(table())])
    assert summary["provenance_status"] == "unverified_legacy"


def test_sentinel_mask_preserves_exact_large_integers_for_range_checks():
    df = pd.DataFrame({"stress": [9007199254740993, -200, 2]})
    config = {"missing_tokens": ["-200"], "checks": {"outliers": {
        "columns": ["stress"], "method": "range", "bounds": {"stress": {"max": 9007199254740992}}
    }}}
    report = api().run_check(df, "outliers", context=api().make_context(df, config))
    assert [(f["code"], f["row_position"]) for f in report["findings"]] == [("OUTLIER_RANGE", 0)]
