import json
from pathlib import Path

import pytest
from lfx.custom.eval import eval_custom_component_code
from lfx.schema import Data, DataFrame, Message
from pandas.testing import assert_frame_equal

from components.materials_quality import (
    MaterialDuplicateCheck,
    MaterialMissingCheck,
    MaterialOutlierCheck,
    MaterialQualitySummary,
    MaterialSchemaCheck,
    MaterialTypeCheck,
    MaterialUnitCheck,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = [
    (MaterialSchemaCheck, {"required_columns_json": '["id", "x"]'}, True),
    (MaterialMissingCheck, {}, False),
    (MaterialTypeCheck, {"expectations_json": '{"x": "number"}'}, True),
    (MaterialUnitCheck, {"source_units_json": '{"x": "MPa"}', "expected_units_json": '{"x": "Pa"}'}, True),
    (MaterialDuplicateCheck, {"columns_json": '["id"]'}, False),
    (
        MaterialOutlierCheck,
        {"columns_json": '["x"]', "detection_method": "range", "bounds_json": '{"x": {"min": 0, "max": 10}}'},
        False,
    ),
]


@pytest.mark.parametrize("cls,config,want_pass", CONFIGS)
def test_real_native_component_outputs_and_preserves_input(cls, config, want_pass):
    table = DataFrame({"id": ["A", "A", "B", "C", "D"], "x": [1, 2, None, 4, 100]})
    before = table.copy(deep=True)
    node = cls().set(input_table=table, **config)
    report = node.build_report()
    assert isinstance(report, Data)
    assert report.data["passed"] is want_pass
    assert isinstance(node.pass_table(), DataFrame)
    assert isinstance(node.build_findings(), DataFrame)
    assert_frame_equal(table, before)
    frontend = node.to_frontend_node()["data"]["node"]
    expected_ports = {"table_out", "findings", "report"}
    if cls is MaterialUnitCheck:
        expected_ports.add("converted_table")
    assert {o["name"] for o in frontend["outputs"]} == expected_ports
    assert all(o["group_outputs"] for o in frontend["outputs"])


@pytest.mark.parametrize(
    "filename",
    [
        "schema_check.py",
        "missing_check.py",
        "type_check.py",
        "unit_check.py",
        "duplicate_check.py",
        "outlier_check.py",
        "quality_summary.py",
    ],
)
def test_component_source_is_accepted_by_actual_langflow_code_loader(filename):
    code = (ROOT / "components" / "materials_quality" / filename).read_text(encoding="utf-8")
    cls = eval_custom_component_code(code)
    node = cls()
    frontend = node.to_frontend_node()
    assert frontend["data"]["node"]["outputs"]


def test_summary_consumes_connected_native_data_reports():
    table = DataFrame({"x": [1, None]})
    report = MaterialMissingCheck().set(input_table=table).build_report()
    node = MaterialQualitySummary().set(reports=[report])
    assert node.build_report().data["metrics"]["failed_checks"] == 1
    assert len(node.build_findings()) == 1
    assert isinstance(node.build_summary(), Message)
    assert "1" in node.build_summary().text


def test_malformed_json_is_an_actionable_configuration_error():
    node = MaterialTypeCheck().set(input_table=DataFrame({"x": [1]}), expectations_json="{broken")
    with pytest.raises(ValueError, match="expectations_json"):
        node.build_report()


def test_type_configuration_rejects_nonstandard_nan_json():
    node = MaterialTypeCheck().set(input_table=DataFrame({"x": [1]}), expectations_json='{"x": NaN}')
    with pytest.raises(ValueError):
        node.build_report()


@pytest.mark.parametrize("case,want_pass", [("clean", True), ("dirty", False)])
def test_exported_example_reimports_and_executes_actual_graph(case, want_pass):
    from scripts.build_example import create_flow_payload
    from scripts.run_example import execute_payload

    payload = json.loads(json.dumps(create_flow_payload(case), ensure_ascii=False, allow_nan=False))
    report = execute_payload(payload)
    assert report["execution_status"] == "completed"
    assert report["metrics"]["completed_checks"] == 6
    assert report["passed"] is want_pass
    if case == "dirty":
        assert {f["code"] for f in report["findings"]} >= {
            "MISSING_VALUE",
            "DUPLICATE_RECORD",
            "TYPE_OR_FORMAT",
            "OUTLIER_RANGE",
        }
