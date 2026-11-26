from materials_quality.agent.node_layout import (
    compact_component_catalog,
    compact_flow_templates,
    compact_template,
    keep_visible,
)


def test_keep_visible_core_and_columns():
    assert keep_visible("input_table")
    assert keep_visible("cfg_path")
    assert keep_visible("x_column")
    assert keep_visible("cfg_columns")
    assert keep_visible("cfg_curve_id")
    assert keep_visible("cfg_group_by")
    assert not keep_visible("window_low")
    assert not keep_visible("cfg_dpi")
    assert not keep_visible("baseline_value")


def test_compact_template_keeps_core_and_folds_optional():
    template = {
        "input_table": {"_type": "DataFrameInput"},
        "x_column": {},
        "cfg_columns": {},
        "cfg_dpi": {},
        "window_low": {},
        "bundle_base64": {},
        "code": {"advanced": True},
    }

    compact_template(template)

    assert template["input_table"]["advanced"] is False
    assert template["x_column"]["advanced"] is False
    assert template["cfg_columns"]["advanced"] is False
    assert template["bundle_base64"]["advanced"] is False
    assert template["cfg_dpi"]["advanced"] is True
    assert template["window_low"]["advanced"] is True
    assert template["code"]["advanced"] is True


def test_compact_template_planner_keeps_only_task_columns():
    template = {
        "input_table": {},
        "task": {"value": "spectra"},
        "request": {},
        "curve_column": {},
        "x_column": {},
        "y_column": {},
        "group_column": {},
        "sample_column": {},
        "variable_column": {},
        "value_column": {},
        "unit_column": {},
        "x_unit": {},
        "window_low": {},
        "data_kind": {},
        "code": {"advanced": True},
    }

    compact_template(template, type_name="ResearchSkillPlanner")

    for name in (
        "input_table",
        "task",
        "request",
        "curve_column",
        "x_column",
        "y_column",
        "group_column",
    ):
        assert template[name]["advanced"] is False
    for name in (
        "sample_column",
        "variable_column",
        "value_column",
        "unit_column",
        "x_unit",
        "window_low",
        "data_kind",
        "code",
    ):
        assert template[name]["advanced"] is True


def test_compact_template_planner_auto_keeps_only_fixed_fields():
    template = {
        "input_table": {},
        "task": {"value": "auto"},
        "request": {},
        "x_column": {},
        "window_low": {},
    }

    compact_template(template, type_name="ResearchSkillPlanner")

    assert template["input_table"]["advanced"] is False
    assert template["task"]["advanced"] is False
    assert template["request"]["advanced"] is False
    assert template["x_column"]["advanced"] is True
    assert template["window_low"]["advanced"] is True


def test_compact_flow_templates_nested():
    flow = {
        "data": {
            "nodes": [
                {
                    "data": {
                        "node": {
                            "template": {
                                "input_table": {},
                                "curve_column": {},
                                "noise_multiplier": {},
                            }
                        }
                    }
                }
            ]
        }
    }

    compact_flow_templates(flow)

    template = flow["data"]["nodes"][0]["data"]["node"]["template"]
    assert template["input_table"]["advanced"] is False
    assert template["curve_column"]["advanced"] is False
    assert template["noise_multiplier"]["advanced"] is True


def test_compact_component_catalog():
    catalog = {
        "materials_visualization": {
            "ScienceVizSpectra": {
                "template": {
                    "input_table": {},
                    "cfg_columns": {},
                    "cfg_dpi": {},
                }
            }
        }
    }

    compact_component_catalog(catalog)

    template = catalog["materials_visualization"]["ScienceVizSpectra"]["template"]
    assert template["input_table"]["advanced"] is False
    assert template["cfg_columns"]["advanced"] is False
    assert template["cfg_dpi"]["advanced"] is True
