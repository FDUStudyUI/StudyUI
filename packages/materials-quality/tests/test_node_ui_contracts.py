"""Behavioral UI regressions: real controls, saved config and honest output types."""

import json

import pandas as pd
import pytest
from lfx.schema import DataFrame
from PIL import Image

from materials_quality.science.catalog import component_class
from materials_quality.science.ui_schema import form_config
from materials_quality.science.ui_types import field


def test_field_metadata_keeps_false_zero_and_empty_defaults():
    assert field("enabled", "启用", "bool", default=False)["default"] is False
    assert field("offset", "偏移", "float", default=0)["default"] == 0
    assert field("columns", "列", "list", default=[])["default"] == []


def test_mechanics_has_native_units_columns_and_range_controls():
    node = component_class("materials.mechanics")()
    inputs = {value.name: value for value in node.inputs}
    assert {
        "cfg_x",
        "cfg_y",
        "cfg_strain_unit",
        "cfg_stress_unit",
        "cfg_fit_range_min",
        "cfg_fit_range_max",
    } <= inputs.keys()
    assert inputs["cfg_stress_unit"].options == ["Pa", "kPa", "MPa", "GPa"]
    assert inputs["config_json"].advanced and not inputs["config_json"].show


def test_form_only_mechanics_executes_without_json():
    node = component_class("materials.mechanics")().set(
        ui_mode="form",
        cfg_x="strain",
        cfg_y="stress",
        cfg_strain_unit="fraction",
        cfg_stress_unit="MPa",
        cfg_fit_range_min=0,
        cfg_fit_range_max=0.001,
        input_table=DataFrame(
            {"strain": [0, 0.0005, 0.001, 0.003, 0.004], "stress": [0, 100, 200, 220, 230]}
        ),
    )
    assert node.build_report().data["data"]["elastic_modulus_MPa"] == pytest.approx(200000)


def test_form_mode_has_explicit_precedence_and_preserves_false():
    node = component_class("preprocess.filter")().set(
        ui_mode="form",
        config_json='{"columns":["other"]}',
        cfg_columns=["x"],
        input_table=DataFrame({"x": [1], "other": [2]}),
    )
    assert list(node.build_table()) == ["x"]


def test_legacy_json_only_call_keeps_original_parameters():
    node = component_class("preprocess.filter")().set(
        input_table=DataFrame({"x": [1], "other": [2]}),
        config_json='{"columns":["other"]}',
    )
    assert list(node.build_table()) == ["other"]


def test_tableless_image_has_no_table_or_unrelated_inputs(tmp_path):
    node = component_class("io.image_import")()
    inputs = {value.name for value in node.inputs}
    outputs = {value.name for value in node.outputs}
    assert "input_table" not in inputs and "input_tables" not in inputs and "reports" not in inputs
    assert "table" not in outputs
    path = tmp_path / "image.png"
    Image.new("RGB", (2, 2), "red").save(path)
    node.set(config_json=json.dumps({"path": str(path)}))
    assert node.build_report().data["table_summary"] is None
    with pytest.raises(ValueError, match="table|表格"):
        node.build_table()


def test_genuine_empty_table_remains_a_valid_table():
    node = component_class("preprocess.filter")().set(
        input_table=DataFrame({"x": [1]}),
        config_json='{"conditions":[{"column":"x","op":"gt","value":5}]}',
    )
    assert isinstance(node.build_table(), pd.DataFrame) and node.build_table().empty
    assert node.build_report().data["table_summary"]["rows"] == 0


def test_non_report_node_does_not_advertise_report_collection():
    node = component_class("stats.grouped")()
    assert "reports" not in {value.name for value in node.inputs}
    report = component_class("export.report")()
    assert "reports" in {value.name for value in report.inputs}


def test_generated_node_is_self_serializing_and_form_config_roundtrips():
    from lfx.graph import Graph

    from examples.demo_source import MaterialDemoTable

    source = MaterialDemoTable().set(records_json='[{"x":1,"y":2}]')
    node = component_class("preprocess.filter")()
    node.set_id("form-roundtrip")
    node.set(input_table=source.build_table, ui_mode="form", cfg_columns=["y"])
    payload = Graph(start=source, end=node).dump()
    graph = Graph.from_payload(json.loads(json.dumps(payload)))
    for step in graph.start():
        if hasattr(step, "valid"):
            assert step.valid
    assert graph.get_vertex("form-roundtrip").results["table"].to_dict("list") == {"y": [2]}


def test_unset_optional_numeric_controls_preserve_algorithm_auto_defaults():
    for key, absent in [
        ("stats.predict", {"max_depth"}),
        ("viz.mechanics", {"dpi", "width_mm", "height_mm"}),
    ]:
        config = form_config(component_class(key)().set(ui_mode="form"), key, validate=False)
        assert not absent.intersection(config), config


def test_numeric_list_default_loads_and_converts_without_json():
    node = component_class("extract.chart_digitize")().set(ui_mode="form")
    assert form_config(node, "extract.chart_digitize", validate=False)["color"] == [255, 0, 0]


def test_serialized_native_controls_show_current_method_and_mode():
    node = component_class("preprocess.missing")().set(cfg_method="linear")
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert template["cfg_order_by"]["show"] and template["cfg_continuous"]["show"]
    node = component_class("viz.spectra")().set(config_json='{"method":"line"}')
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert template["ui_mode"]["value"] == "json" and template["config_json"]["show"]


def test_boolean_controller_requests_refresh():
    node = component_class("lit.sources")()
    field = node.to_frontend_node()["data"]["node"]["template"]["cfg_save"]
    assert field["real_time_refresh"] is True


def test_explicit_tab_delimiter_is_not_trimmed():
    node = component_class("io.table_import")().set(ui_mode="form", cfg_delimiter="\t")
    assert form_config(node, "io.table_import")["delimiter"] == "\t"


def test_explicit_null_header_is_preserved_as_no_header():
    node = component_class("io.table_import")().set(ui_mode="form", cfg_header=None)
    assert form_config(node, "io.table_import")["header"] is None
    assert (
        form_config(component_class("io.table_import")().set(ui_mode="form"), "io.table_import")["header"]
        == 0
    )


def test_group_by_satisfies_grouped_statistics_group_requirement():
    from materials_quality.science.grouped_stats import grouped_summary

    node = component_class("stats.grouped")().set(
        ui_mode="form", cfg_group="", cfg_group_by=["metric"], cfg_columns=["hardness"]
    )
    config = form_config(node, "stats.grouped")
    assert "group" not in config
    assert config["group_by"] == ["metric"]
    assert config["columns"] == ["hardness"]
    result = grouped_summary(pd.DataFrame({"metric": ["HV_A", "HV_A"], "hardness": [10.0, 14.0]}), config)
    assert result.table.loc[0, "metric"] == "HV_A"
    assert result.table.loc[0, "count"] == 2
    assert result.table.loc[0, "mean"] == 12.0
    assert result.table.loc[0, "std"] == pytest.approx(2**0.5 * 2)

    missing = component_class("stats.grouped")().set(
        ui_mode="form", cfg_group="", cfg_group_by=[], cfg_columns=["hardness"]
    )
    with pytest.raises(ValueError, match="分组列"):
        form_config(missing, "stats.grouped")


def test_integer_control_rejects_fraction_before_sdk_coercion():
    node = component_class("stats.predict")().set(ui_mode="form", cfg_seed=1.5)
    with pytest.raises(ValueError, match="整数"):
        form_config(node, "stats.predict")


def test_external_converter_keeps_repeated_command_arguments():
    node = component_class("io.instrument_import")().set(
        ui_mode="form",
        cfg_converter=["tool", "--map", "A", "--map", "B", "{input}", "{output}"],
    )
    field = node.to_frontend_node()["data"]["node"]["template"]["cfg_converter"]
    assert field["_input_type"] == "StrInput" and field.get("list") is True
    assert field["value"].count("--map") == 2


def test_data_columns_do_not_replace_non_column_choices():
    from materials_quality.science.ui_schema import refresh_config

    node = component_class("viz.mechanics")().set(input_table=DataFrame({"measurement": [1, 2]}))
    template = node.to_frontend_node()["data"]["node"]["template"]
    refresh_config(node, "viz.mechanics", template, "form", "ui_mode")
    assert template["cfg_x"]["options"] == ["measurement"]
    assert "measurement" not in template["cfg_formats"]["options"]


def test_connected_provenance_port_stays_visible_in_exported_graph():
    from lfx.graph import Graph

    source = component_class("materials.mechanics")()
    sink = component_class("viz.mechanics")().set(input_data=source.build_report)
    payload = Graph(start=source, end=sink).dump()
    vertex = next(n for n in payload["data"]["nodes"] if n["id"] == sink.get_id())
    assert vertex["data"]["node"]["template"]["input_data"]["advanced"] is False


def test_explicit_training_task_ignores_upstream_saved_model(tmp_path):
    from lfx.schema import Data

    node = component_class("stats.predict")().set(
        ui_mode="form",
        cfg_prediction_task="train",
        cfg_output_dir=str(tmp_path),
        cfg_n_estimators=5,
        input_table=DataFrame({"x": list(range(12)), "y": list(range(12))}),
        input_data=Data(data={"model_path": "missing-upstream-model.skops"}),
    )
    report = node.build_report().data
    assert report["data"]["model_method"] == "random_forest"
    assert report["provenance"]["ui_task"] == "train"


def test_serialized_form_preserves_helpful_field_order():
    node = component_class("materials.mechanics")()
    order = node.to_frontend_node()["data"]["node"]["field_order"]
    assert order.index("input_table") < order.index("cfg_x")
    assert order.index("cfg_fit_range_min") < order.index("cfg_fit_range_max")


def test_training_evaluation_does_not_use_upstream_prediction_vectors():
    from lfx.schema import Data

    node = component_class("stats.evaluate")().set(
        ui_mode="form",
        cfg_evaluation_task="train",
        cfg_folds=3,
        input_table=DataFrame({"x": list(range(12)), "y": list(range(12))}),
        input_data=Data(data={"y_true": [0, 1], "y_pred": [0, 1]}),
    )
    report = node.build_report().data
    assert report["data"]["evaluation"] == "cross_validation"
    assert report["table_summary"]["rows"] == 12


@pytest.mark.parametrize(
    "key,selector", [("stats.predict", "prediction_task"), ("stats.evaluate", "evaluation_task")]
)
def test_saved_task_requires_an_existing_model_input(key, selector):
    node = component_class(key)().set(**{"ui_mode": "form", "cfg_" + selector: "saved"})
    with pytest.raises(ValueError, match="模型|model"):
        node.build_report()


def test_prediction_evaluation_uses_explicit_table_columns_before_upstream_vectors():
    from lfx.schema import Data

    node = component_class("stats.evaluate")().set(
        ui_mode="form",
        cfg_evaluation_task="predictions",
        cfg_y_true="truth",
        cfg_y_pred="prediction",
        input_table=DataFrame({"truth": [0, 1, 2], "prediction": [0, 1, 2]}),
        input_data=Data(data={"y_true": [0, 1], "y_pred": [1, 0]}),
    )
    report = node.build_report().data
    assert report["table_summary"]["rows"] == 3
    assert report["data"]["metrics"]["r2"] == 1


def test_legacy_model_config_does_not_inject_training_defaults():
    node = component_class("stats.predict")().set(config_json='{"model_path":"saved.skops"}')
    assert form_config(node, "stats.predict") == {"model_path": "saved.skops"}


def test_saved_model_form_omits_hidden_training_defaults():
    node = component_class("stats.predict")().set(
        ui_mode="form", cfg_prediction_task="saved", cfg_model_path="saved.skops"
    )
    config = form_config(node, "stats.predict")
    assert config["model_path"] == "saved.skops"
    assert not {"features", "target", "method", "prediction_task"}.intersection(config)


def test_optional_number_toggle_survives_native_graph_serialization():
    node = component_class("viz.mechanics")().set(ui_mode="form", cfg_dpi_enabled="是", cfg_dpi=300)
    config = form_config(node, "viz.mechanics", validate=False)
    assert config["dpi"] == 300
    fields = node.to_frontend_node()["data"]["node"]["template"]
    assert fields["cfg_dpi_enabled"]["value"] == "是" and fields["cfg_dpi"]["show"]
    node.set(cfg_dpi_enabled="否")
    assert "dpi" not in form_config(node, "viz.mechanics", validate=False)


def test_repeated_ordered_values_are_editable_not_multiselected():
    node = component_class("extract.chart_digitize")().set(ui_mode="form", cfg_color=["255", "0", "0"])
    native = {value.name: value for value in node.inputs}["cfg_color"]
    assert type(native).__name__ == "StrInput" and native.is_list
    assert form_config(node, "extract.chart_digitize", validate=False)["color"] == [255, 0, 0]


def test_png_conversion_builds_outputs_without_fake_table(tmp_path):
    import asyncio

    source = tmp_path / "input.png"
    Image.new("RGB", (3, 3), "blue").save(source)
    node = component_class("extract.convert_file")().set(
        ui_mode="form",
        cfg_path=str(source),
        cfg_target="png",
        cfg_output_dir=str(tmp_path / "out"),
    )
    assert "table" not in {value.name for value in node.outputs}
    results, _ = asyncio.run(node.build_results())
    assert "table" not in results and results["report"].data["table_available"] is False
