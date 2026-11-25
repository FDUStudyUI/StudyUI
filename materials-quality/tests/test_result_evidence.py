"""Claims must retain actual cells and separate interpretation from observation."""

import json

import pandas as pd
import pytest

from materials_quality.science.result_evidence import result_evidence
from materials_quality.science.viz_report import build_report


def test_observations_bind_exact_row_column_value_and_units():
    table = pd.DataFrame({"curve_id": ["a", "b"], "peak_nm": [715.0, 755.0]})
    table.attrs["units"] = {"peak_nm": "nm"}
    result = result_evidence(table, config={"columns": ["peak_nm"], "identity_column": "curve_id"})
    assert len(result.table) == 2
    claims = result.data["evidence_bundle"]["claims"]
    assert claims[0]["kind"] == "observation"
    assert claims[0]["result_ref"]["value"] == 715.0
    assert claims[0]["result_ref"]["unit"] == "nm"
    assert claims[0]["result_ref"]["row_identity"] == "a"
    assert len(claims[0]["result_ref"]["table_sha256"]) == 64
    changed = table.copy()
    changed.loc[0, "peak_nm"] = 716
    other = result_evidence(changed, config={"columns": ["peak_nm"]})
    assert other.data["evidence_bundle"]["table_sha256"] != result.data["evidence_bundle"]["table_sha256"]


def test_missing_results_are_not_zero_and_hypotheses_not_observations():
    result = result_evidence(
        pd.DataFrame({"peak": [None, 42.0]}),
        config={"columns": ["peak"], "hypothesis": "可能存在耦合增强"},
    )
    claims = result.data["evidence_bundle"]["claims"]
    assert claims[0]["status"] == "missing_measurement"
    assert claims[0]["result_ref"]["value"] is None
    assert claims[-1]["kind"] == "hypothesis"
    assert claims[-1]["status"] == "requires_experiment"
    json.dumps(result.data, allow_nan=False)


def test_explanation_requires_known_card_and_keeps_unverified_transfer():
    table = pd.DataFrame({"peak": [42.0]})
    with pytest.raises(ValueError, match="method_card"):
        result_evidence(table, config={"columns": ["peak"], "explanation": "机制", "method_card": "madeup"})


def test_report_carries_evidence_bundle_without_html_injection(tmp_path):
    result = result_evidence(
        pd.DataFrame({"peak": [42.0]}),
        config={"columns": ["peak"], "hypothesis": "<script>alert(1)</script>"},
    )
    report = build_report(result.table, {"output_dir": str(tmp_path)}, result.data)
    text = open(report.artifacts[0], encoding="utf-8").read()
    assert "Evidence-linked claims" in text
    assert "table_sha256" in text
    assert "<script>alert(1)</script>" not in text


def test_selection_and_boundaries_are_explicit():
    table = pd.DataFrame({"x": range(30)})
    result = result_evidence(table, config={"columns": ["x"], "max_rows": 20})
    assert len(result.table) == 20
    assert result.data["evidence_bundle"]["omitted_rows"] == 10
    assert result.warnings
    with pytest.raises(ValueError, match="columns"):
        result_evidence(table, config={"columns": ["missing"]})
    with pytest.raises(ValueError, match="max_rows"):
        result_evidence(table, config={"columns": ["x"], "max_rows": True})


def test_native_evidence_binds_matching_report_and_rejects_unrelated_result():
    from lfx.schema import Data, DataFrame

    from materials_quality.science.catalog import component_class

    source = component_class("stats.grouped")().set(
        input_table=DataFrame({"group": ["A", "A"], "value": [1.0, 3.0]}),
        cfg_group_by=["group"],
        cfg_columns=["value"],
    )
    table, report = source.build_table(), source.build_report()
    node = component_class("lit.result_evidence")().set(
        input_table=table,
        input_data=report,
        cfg_columns=["mean"],
    )
    bundle = node.build_report().data["data"]["evidence_bundle"]
    assert bundle["upstream_execution"]["operation"] == "stats.grouped"
    assert bundle["upstream_execution"]["provenance"]["parameters"]
    unrelated = dict(report.data)
    unrelated["table_fingerprint"] = "unrelated"
    node.set(input_data=Data(data=unrelated))
    with pytest.raises(ValueError, match="不一致"):
        node.build_report()
