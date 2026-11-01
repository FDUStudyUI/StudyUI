"""Portable example configuration is editable and keeps explicit algorithm values."""

import json
from copy import deepcopy

import pytest

from materials_quality.science.catalog import component_class
from materials_quality.science.ui_config_import import config_to_form
from materials_quality.science.ui_schema import form_config


def composed(key, values):
    return form_config(component_class(key)().set(**values), key, validate=False)


def test_mechanics_import_uses_native_range_and_preserves_original():
    config = {"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0, 0.0008]}
    original = deepcopy(config)
    values = config_to_form("materials.mechanics", config)
    assert values["ui_mode"] == "form"
    assert values["cfg_fit_range_min"] == 0
    assert values["cfg_fit_range_max"] == 0.0008
    assert composed("materials.mechanics", values)["fit_range"] == [0, 0.0008]
    assert config == original


def test_calibration_tables_repeated_rgb_and_optional_numbers_roundtrip():
    config = {
        "color": [255, 0, 0],
        "color_tolerance": 0,
        "region": [0, 0, 100, 100],
        "calibration": {"x": [[20, 0], [120, 10]], "y": [[120, 0], [20, 100]]},
    }
    values = config_to_form("extract.chart_digitize", config)
    assert values["ui_mode"] == "form"
    assert values["cfg_color"] == ["255", "0", "0"]
    assert values["cfg_calibration_x"] == [{"pixel": 20, "value": 0}, {"pixel": 120, "value": 10}]
    result = composed("extract.chart_digitize", values)
    assert result["color"] == config["color"]
    assert result["region"] == config["region"]
    assert result["calibration"]["x"] == config["calibration"]["x"]
    values = config_to_form("materials.microstructure", {"pixel_size": 2, "spatial_unit": "um"})
    assert values["cfg_pixel_size_enabled"] == "是"
    assert composed("materials.microstructure", values)["pixel_size"] == 2


def test_filter_table_keeps_numeric_looking_string_comparison():
    config = {"conditions": [{"column": "sample", "op": "eq", "value": "001"}], "drop_empty": False}
    values = config_to_form("preprocess.filter", config)
    assert values["ui_mode"] == "form"
    result = composed("preprocess.filter", values)
    assert result["conditions"] == config["conditions"]
    assert result["drop_empty"] is False


def test_rectangles_and_native_list_mapping_roundtrip():
    config = {"regions": [[0, 0, 20, 30], [20, 0, 40, 30]]}
    values = config_to_form("extract.image_ocr", config)
    assert values["ui_mode"] == "form"
    assert values["cfg_regions"][0] == {"left": 0, "top": 0, "right": 20, "bottom": 30}
    assert composed("extract.image_ocr", values)["regions"] == config["regions"]
    config = {"method": "lexicon", "lexicon": {"phase": ["alpha", "beta"]}}
    values = config_to_form("lit.extract", config)
    assert values["ui_mode"] == "form"
    assert values["cfg_lexicon"] == {"phase": "alpha,beta"}
    assert composed("lit.extract", values)["lexicon"] == config["lexicon"]


@pytest.mark.parametrize(
    "key,config",
    [
        ("preprocess.filter", {"unknown": {"zero": 0, "empty": [], "false": False}}),
        ("materials.spectra", {"baseline": {"method": "none", "points": [[0, 1], [2, 3]]}}),
        ("preprocess.normalize", {"columns": []}),
    ],
)
def test_unrepresentable_values_fall_back_to_original_json(key, config):
    values = config_to_form(key, config)
    assert values["ui_mode"] == "json"
    assert json.loads(values["config_json"]) == config
    assert composed(key, values) == config


def test_saved_and_existing_prediction_tasks_omit_training_defaults():
    values = config_to_form("stats.predict", {"model_path": "saved.skops"})
    assert values["cfg_prediction_task"] == "saved"
    assert composed("stats.predict", values) == {"model_path": "saved.skops"}
    values = config_to_form("stats.predict", {}, task="saved")
    assert values["ui_mode"] == "form" and values["cfg_prediction_task"] == "saved"
    assert composed("stats.predict", values) == {}
    values = config_to_form("stats.evaluate", {"y_true": "y", "y_pred": "y_pred"})
    assert values["cfg_evaluation_task"] == "predictions"
    assert composed("stats.evaluate", values) == {"y_true": "y", "y_pred": "y_pred"}


def test_all_example_factories_build_native_forms_without_execution():
    from scripts.build_science_examples import FACTORIES

    total = forms = 0
    for factory in FACTORIES:
        flow = factory()
        for alias, node in flow.nodes.items():
            total += 1
            forms += node._parameters.get("ui_mode") == "form"
            assert node._parameters.get("ui_mode") == "form", (flow.slug, alias, node._parameters)
            if flow.operations[alias] == "materials.mechanics":
                assert node._parameters["ui_mode"] == "form"
            if flow.operations[alias] == "stats.predict":
                assert node._parameters["cfg_prediction_task"] == "saved"
                assert "method" not in form_config(node, "stats.predict")
        payload = flow.dump()
        assert payload["data"]["edges"]
    assert forms == total


def test_builder_preserves_supported_report_collection_connections():
    from scripts.build_science_examples import Flow

    flow = Flow("test", "Native report context", records=[{"x": 1, "y": 2}])
    flow.add("left", "preprocess.filter", table="fixture")
    flow.add("right", "preprocess.filter", table="fixture")
    flow.add(
        "join", "preprocess.merge", {"method": "append"}, tables=["left", "right"], reports=["left", "right"]
    )
    report_edges = [
        edge
        for edge in flow.dump()["data"]["edges"]
        if edge["target"] == flow.nodes["join"].get_id()
        and edge["data"]["targetHandle"]["fieldName"] == "reports"
    ]
    assert {edge["source"] for edge in report_edges} == {
        flow.nodes["left"].get_id(),
        flow.nodes["right"].get_id(),
    }
