import pandas as pd
import pytest
from lfx.schema import DataFrame
from pandas.testing import assert_frame_equal

from materials_quality.checks import check_duplicates, check_schema, check_types
from materials_quality.units import check_units


def test_structure_template_checks_json_schema_values_and_extra_fields():
    table = pd.DataFrame({"id": ["A", "B"], "stress": [10, -1]})
    template = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "stress": {"type": "number", "minimum": 0}},
        "required": ["id", "stress"],
        "additionalProperties": False,
    }
    result = check_schema(table, required_columns=["id", "stress"], schema_template=template)
    assert [(f["code"], f["column"], f["row_position"]) for f in result["findings"]] == [
        ("SCHEMA_TEMPLATE", "stress", 1)
    ]
    with pytest.raises(ValueError):
        check_schema(table, required_columns=["id"], schema_template={"type": "not-a-jsonschema-type"})


def test_semantic_type_inference_recognizes_numeric_date_and_category_values():
    table = pd.DataFrame(
        {
            "value": ["1", "2", "3", "4"],
            "date": ["2026-10-30"] * 4,
            "group": ["alpha", "beta", "alpha", "beta"],
        }
    )
    result = check_types(table, infer=True)
    assert result["passed"]
    rules = result["metrics"]["inferred_rules"]
    assert rules["value"]["type"] == "integer"
    assert rules["date"] == {"type": "datetime", "format": "%Y-%m-%d"}
    assert rules["group"]["type"] == "category"


def test_empty_column_cannot_be_confidently_inferred():
    result = check_types(pd.DataFrame({"x": [None, None]}), infer=True)
    assert not result["passed"]
    assert result["findings"][0]["code"] == "TYPE_INFERENCE_INSUFFICIENT"


def test_similar_records_are_matched_with_evidence_and_explicit_threshold():
    table = pd.DataFrame({"sample_id": ["sample-A001", "sample-AO01", "other-Z999"], "value": [1, 2, 3]})
    original = table.copy(deep=True)
    result = check_duplicates(table, columns=["sample_id"], similarity_threshold=0.8)
    assert result["metrics"]["duplicate_rows"] == 0
    assert result["metrics"]["similar_pairs"][0]["positions"] == [0, 1]
    assert result["findings"][0]["code"] == "SIMILAR_RECORD"
    assert_frame_equal(table, original)


def test_numeric_similarity_uses_declared_tolerances_not_string_rounding():
    result = check_duplicates(
        pd.DataFrame({"x": [1.0, 1.001, 3.0]}),
        columns=["x"],
        similarity_threshold=1,
        numeric_tolerances={"x": {"atol": 0.002, "rtol": 0}},
    )
    assert result["metrics"]["similar_pairs"][0]["positions"] == [0, 1]


def test_optional_unit_conversion_reports_audit_without_mutating_source():
    table = pd.DataFrame({"temperature": [0.0, 100.0]})
    original = table.copy(deep=True)
    report = check_units(
        table, source_units={"temperature": "degC"}, expected_units={"temperature": "K"}, convert_values=True
    )
    assert report["metrics"]["converted"]
    assert report["metrics"]["conversion_records"][0]["after"] == pytest.approx(273.15)
    assert_frame_equal(table, original)


def test_native_inference_and_converted_output_are_connected_types():
    from components.materials_quality import MaterialTypeCheck, MaterialUnitCheck

    inferred = MaterialTypeCheck().set(input_table=DataFrame({"x": ["1", "2"]}), infer_types=True)
    assert inferred.build_report().data["metrics"]["inferred_rules"]["x"]["type"] == "integer"
    unit = MaterialUnitCheck().set(
        input_table=DataFrame({"t": [0.0, 100.0]}),
        source_units_json='{"t":"degC"}',
        expected_units_json='{"t":"K"}',
        convert_values=True,
    )
    assert unit.build_converted_table().t.tolist() == pytest.approx([273.15, 373.15])
    assert unit.pass_table().t.tolist() == [0.0, 100.0]


def test_shared_rules_can_explicitly_request_type_inference():
    from materials_quality.context import make_context, run_check

    frame = pd.DataFrame({"x": ["1", "2"]})
    context = make_context(frame, {"checks": {"types": {"infer": True}}})
    report = run_check(frame, "types", context=context)
    assert report["passed"] and report["metrics"]["inferred_rules"]["x"]["type"] == "integer"


def test_schema_templates_only_resolve_local_definitions():
    import pandas as pd
    import pytest

    from materials_quality.checks import check_schema

    frame = pd.DataFrame({"id": [1]})
    template = {"$defs": {"row": {"type": "object", "required": ["id"]}}, "$ref": "#/$defs/row"}
    assert check_schema(frame, required_columns=["id"], schema_template=template)["passed"]
    with pytest.raises(ValueError, match="local|external|remote"):
        check_schema(frame, required_columns=["id"], schema_template={"$ref": "https://example.com/schema"})
