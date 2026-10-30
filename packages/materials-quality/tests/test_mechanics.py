import importlib
import json
from pathlib import Path

import pytest
from lfx.custom.eval import eval_custom_component_code
from lfx.schema import DataFrame
from pandas.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parents[1]


def test_native_context_node_loads_and_rules_port_connects_without_local_json():
    module = importlib.import_module("components.materials_quality")
    cls = module.MaterialQualityContext
    table = DataFrame({"x": [1, -200, 3]})
    before = table.copy(deep=True)
    rules = {"missing_tokens": ["", "-200"], "checks": {"types": {"expectations": {"x": "number"}}}}
    context_node = cls().set(input_table=table, rules_json=json.dumps(rules))
    context = context_node.build_context()
    node = module.MaterialTypeCheck().set(
        input_table=table, quality_context=context, expectations_json="invalid"
    )
    assert node.build_report().data["passed"]
    assert node.build_report().data["provenance"]["mode"] == "shared"
    assert_frame_equal(node.pass_table(), before)
    code = (ROOT / "components/materials_quality/quality_context.py").read_text(encoding="utf-8")
    assert eval_custom_component_code(code)().to_frontend_node()["data"]["node"]["outputs"]


@pytest.mark.parametrize("case", ["clean", "dirty", "corrected"])
def test_mechanics_stored_workflow_matches_independent_manifest(case):
    from scripts.run_example import execute_payload

    builder = importlib.import_module("scripts.build_mechanics")
    payload = builder.create_mechanics_payload(case)
    report = execute_payload(json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False)))
    manifest = ROOT / "examples/mechanics/expected_findings.json"
    expected = json.loads(manifest.read_text(encoding="utf-8"))[case]
    actual = sorted((f["check_id"], f["code"], f["column"], f["row_position"]) for f in report["findings"])
    assert actual == sorted(tuple(f) for f in expected["findings"])
    assert report["passed"] == expected["passed"]
    assert report["metrics"]["completed_checks"] == 6
    assert report["provenance_status"] == "verified"
    assert report["provenance"]["source"]["source_name"] == f"{case}.csv"
    outliers = next(r for r in report["checks"] if r["check_id"] == "outliers")
    assert outliers["parameters"]["group_by"] == ["condition"]
    if case == "dirty":
        assert all(f["row_position"] != 2 for f in outliers["findings"])
    else:
        assert next(r for r in report["checks"] if r["check_id"] == "duplicates")["passed"]
