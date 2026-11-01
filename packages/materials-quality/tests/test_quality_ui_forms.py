"""Native quality forms execute real checks and preserve legacy precedence."""

import pytest
from lfx.schema import DataFrame

from components.materials_quality import (
    MaterialDuplicateCheck,
    MaterialMissingCheck,
    MaterialOutlierCheck,
    MaterialQualityContext,
    MaterialSchemaCheck,
    MaterialTypeCheck,
    MaterialUnitCheck,
)


def test_shared_rule_form_configures_six_checks_without_json():
    table = DataFrame({"id": ["A", "A"], "x": [0, 10]})
    node = MaterialQualityContext().set(
        input_table=table,
        ui_mode="form",
        enabled_checks=["schema", "missing", "types", "units", "duplicates", "outliers"],
        missing_tokens=[],
        group_by=[],
        required_columns=["id", "x"],
        field_rules=[{"column": "x", "type": "number"}],
        constraint_rules=[{"column": "x", "min": 0, "max": 10}],
        unit_rules=[{"column": "x", "source_unit": "MPa", "expected_unit": "Pa"}],
        duplicate_keys=["id"],
        outlier_columns=["x"],
        detection_method="range",
    )
    context = node.build_context()
    rules = context.data["rules"]
    assert rules["missing_tokens"] == []
    assert rules["checks"]["outliers"]["bounds"]["x"]["min"] == 0
    assert rules["checks"]["schema"]["schema_template"]["properties"]["x"]["minimum"] == 0
    assert rules["checks"]["units"]["convert_values"] is False
    assert (
        MaterialDuplicateCheck()
        .set(input_table=table, quality_context=context)
        .build_report()
        .data["total_findings"]
        == 2
    )


@pytest.mark.parametrize(
    "cls,settings",
    [
        (MaterialSchemaCheck, {"required_columns": ["x"]}),
        (MaterialMissingCheck, {"columns": ["x"], "missing_tokens": []}),
        (MaterialTypeCheck, {"field_rules": [{"column": "x", "type": "integer"}]}),
        (MaterialUnitCheck, {"unit_rules": [{"column": "x", "source_unit": "MPa", "expected_unit": "Pa"}]}),
        (MaterialDuplicateCheck, {"duplicate_keys": ["x"], "numeric_tolerances": {"x": 0}}),
        (
            MaterialOutlierCheck,
            {
                "outlier_columns": ["x"],
                "detection_method": "range",
                "constraint_rules": [{"column": "x", "min": 0, "max": 1}],
            },
        ),
    ],
)
def test_independent_forms_execute(cls, settings):
    node = cls().set(input_table=DataFrame({"x": [0, 1]}), ui_mode="form", **settings)
    assert node.build_report().data["passed"] is True


def test_explicit_mode_wins_and_legacy_json_only_stays_compatible():
    table = DataFrame({"x": [1]})
    legacy = MaterialQualityContext().set(
        input_table=table, rules_json='{"missing_tokens":[],"checks":{"duplicates":{}}}'
    )
    assert set(legacy.build_context().data["rules"]["checks"]) == {"duplicates"}
    legacy.set(ui_mode="form", enabled_checks=["missing"])
    assert set(legacy.build_context().data["rules"]["checks"]) == {"missing"}
    node = MaterialTypeCheck().set(input_table=table, expectations_json='{"x":"number"}')
    assert node.build_report().data["passed"]
    node.set(ui_mode="json", field_rules=[], expectations_json='{"x":"integer"}')
    assert node.build_report().data["parameters"]["expectations"] == {"x": "integer"}


def test_native_controls_are_tables_and_lists_with_serialized_mode():
    node = MaterialQualityContext()
    assert node._parameters == {}
    template = node.to_frontend_node()["data"]["node"]["template"]
    for name in ["field_rules", "constraint_rules", "unit_rules"]:
        assert template[name]["type"] == "table"
        assert template[name]["table_schema"]
    assert template["ui_mode"]["value"] == "form"
    assert template["rules_json"]["advanced"]
    node.set(rules_json='{"checks":{"missing":{}}}')
    assert node.to_frontend_node()["data"]["node"]["template"]["ui_mode"]["value"] == "json"


def test_connected_context_ignores_invalid_local_form_and_json():
    table = DataFrame({"x": [1]})
    context = MaterialQualityContext().set(input_table=table, enabled_checks=["missing"]).build_context()
    node = MaterialMissingCheck().set(
        input_table=table, quality_context=context, columns=["absent"], columns_json="broken"
    )
    assert node.build_report().data["provenance"]["mode"] == "shared"


@pytest.mark.parametrize("legacy", [False, True])
def test_native_graph_roundtrip_preserves_form_and_legacy_rules(legacy):
    from lfx.graph import Graph

    from examples.demo_source import MaterialDemoTable

    source = MaterialDemoTable().set(records_json='[{"x":0},{"x":null}]')
    settings = (
        {"rules_json": '{"missing_tokens":[],"checks":{"missing":{"columns":["x"]}}}'}
        if legacy
        else {
            "ui_mode": "form",
            "enabled_checks": ["missing", "outliers", "units"],
            "columns": ["x"],
            "missing_tokens": [],
            "outlier_columns": ["x"],
            "detection_method": "range",
            "constraint_rules": [{"column": "x", "min": 0, "max": 1}],
            "unit_rules": [{"column": "x", "source_unit": "MPa", "expected_unit": "Pa"}],
            "convert_values": False,
        }
    )
    context = MaterialQualityContext().set(input_table=source.build_table, **settings)
    check = MaterialMissingCheck().set(input_table=source.build_table, quality_context=context.build_context)
    payload = Graph(start=source, end=check).dump(name="Quality form roundtrip")
    restored = Graph.from_payload(payload)
    for step in restored.start():
        assert not hasattr(step, "valid") or step.valid
    report = restored.get_vertex(check.get_id()).results["report"].data
    assert report["total_findings"] == 1
    assert report["provenance"]["mode"] == "shared"
    assert report["parameters"]["missing_tokens"] == []
    if not legacy:
        rules = report["provenance"]["rule_set"]["rules"]["checks"]
        assert rules["outliers"]["bounds"]["x"]["min"] == 0
        assert rules["units"]["convert_values"] is False


def test_shared_form_only_shows_selected_check_controls():
    node = MaterialQualityContext()
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert template["missing_tokens"]["show"]
    assert not template["unit_rules"]["show"]
    updated = node.update_build_config(template, ["outliers"], "enabled_checks")
    assert updated["outlier_columns"]["show"]
    assert not updated["constraint_rules"]["show"]  # iqr default
    updated = node.update_build_config(updated, "range", "detection_method")
    assert updated["constraint_rules"]["show"]
    assert not updated["iqr_multiplier"]["show"]
    updated = node.update_build_config(updated, "json", "ui_mode")
    assert updated["rules_json"]["show"]
    assert not updated["outlier_columns"]["show"]


def test_empty_values_are_recorded_and_duplicate_rule_rows_rejected():
    node = MaterialQualityContext().set(missing_tokens=[], convert_values=False, numeric_tolerances={"x": 0})
    assert node._parameters["missing_tokens"] == []
    assert node._parameters["convert_values"] is False
    assert node._parameters["numeric_tolerances"] == {"x": 0}
    node.set(
        input_table=DataFrame({"x": [1]}),
        enabled_checks=["types"],
        field_rules=[{"column": "x", "type": "number"}, {"column": "x", "type": "integer"}],
    )
    with pytest.raises(ValueError, match="field_rules"):
        node.build_context()


def test_inactive_outlier_settings_do_not_leak_into_selected_method():
    node = MaterialOutlierCheck().set(
        input_table=DataFrame({"x": [0, 1, 2]}),
        ui_mode="form",
        outlier_columns=["x"],
        detection_method="iqr",
        mad_threshold=0,
        constraint_rules=[{"column": "x", "min": "bad"}],
    )
    assert node.build_report().data["passed"]
    template = node.to_frontend_node()["data"]["node"]["template"]
    updated = node.update_build_config(template, "json", "ui_mode")
    assert updated["detection_method"]["show"]
    assert updated["iqr_multiplier"]["show"]
    assert updated["bounds_json"]["show"]
