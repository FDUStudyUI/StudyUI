"""Legacy quality rules become native controls only after a real round trip."""

import json

import pytest

from components.materials_quality import (
    MaterialDuplicateCheck,
    MaterialMissingCheck,
    MaterialOutlierCheck,
    MaterialQualityContext,
    MaterialQualitySummary,
    MaterialSchemaCheck,
    MaterialTypeCheck,
    MaterialUnitCheck,
)
from materials_quality.quality_form_import import quality_to_form
from materials_quality.quality_ui import shared_rules


@pytest.mark.parametrize(
    "cls,saved,expected",
    [
        (
            MaterialSchemaCheck,
            {
                "required_columns_json": '["x"]',
                "aliases_json": '{"x":["X"]}',
                "schema_template_json": '{"type":"object","properties":{"x":{"type":"number","minimum":0}}}',
            },
            "alias_rules",
        ),
        (
            MaterialMissingCheck,
            {"columns_json": '["x"]', "missing_tokens_json": "[]", "group_by_json": "[]"},
            "missing_tokens",
        ),
        (MaterialTypeCheck, {"expectations_json": '{"x":"number"}'}, "field_rules"),
        (
            MaterialUnitCheck,
            {"source_units_json": '{"x":"MPa"}', "expected_units_json": '{"x":"Pa"}', "convert_values": True},
            "unit_rules",
        ),
        (
            MaterialDuplicateCheck,
            {
                "columns_json": '["x"]',
                "numeric_tolerances_json": '{"x":0}',
                "match_similar": True,
                "similarity_threshold": 0,
            },
            "numeric_tolerances",
        ),
        (
            MaterialOutlierCheck,
            {"columns_json": '["x"]', "bounds_json": '{"x":{"min":0,"max":1}}', "detection_method": "range"},
            "constraint_rules",
        ),
        (
            MaterialQualityContext,
            {"rules_json": '{"missing_tokens":[],"checks":{"missing":{"columns":["x"]}}}'},
            "enabled_checks",
        ),
        (MaterialQualitySummary, {"finding_limit": 0}, None),
    ],
)
def test_all_eight_quality_components_import_native_controls(cls, saved, expected):
    values, reason = quality_to_form(cls(), saved)
    assert reason is None
    if expected:
        assert values["ui_mode"] == "form"
        assert expected in values
    else:
        assert values == {}
    if expected == "missing_tokens":
        assert values[expected] == []
    if expected == "numeric_tolerances":
        assert values[expected] == {"x": 0}


@pytest.mark.parametrize(
    "cls,saved",
    [
        (MaterialSchemaCheck, {"schema_template_json": '{"additionalProperties":false}'}),
        (MaterialTypeCheck, {"expectations_json": '{"x":{"type":"number","future":false}}'}),
        (MaterialOutlierCheck, {"detection_method": "iqr", "bounds_json": '{"x":{"min":0}}'}),
        (MaterialMissingCheck, {"missing_tokens_json": "broken"}),
        (MaterialQualityContext, {"rules_json": '{"checks":{"missing":{}},"future":0}'}),
    ],
)
def test_lossy_inactive_unknown_or_malformed_quality_rules_stay_json(cls, saved):
    values, reason = quality_to_form(cls(), saved)
    assert reason and values["ui_mode"] == "json"
    assert all(values[key] == value for key, value in saved.items())


def test_shared_six_check_rules_keep_all_effective_parameters():
    rules = {
        "missing_tokens": [],
        "group_by": [],
        "checks": {
            "schema": {
                "required_columns": ["x"],
                "schema_template": {
                    "type": "object",
                    "properties": {"x": {"type": "number", "minimum": 0, "maximum": 1}},
                },
            },
            "missing": {"columns": ["x"]},
            "types": {"expectations": {"x": "number"}},
            "units": {"source_units": {"x": "MPa"}, "expected_units": {"x": "Pa"}, "convert_values": False},
            "duplicates": {"columns": ["x"], "similarity_threshold": 0, "numeric_tolerances": {"x": 0}},
            "outliers": {"columns": ["x"], "method": "range", "bounds": {"x": {"min": 0, "max": 1}}},
        },
    }
    node = MaterialQualityContext()
    values, reason = quality_to_form(node, {"rules_json": json.dumps(rules)})
    assert reason is None
    assert values["ui_mode"] == "form"
    assert set(shared_rules(node.set(**values))["checks"]) == set(rules["checks"])
