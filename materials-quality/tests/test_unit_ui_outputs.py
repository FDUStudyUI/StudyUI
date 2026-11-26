"""Native unit conversion ports distinguish absent results from empty datasets."""

import json

import pytest
from lfx.schema import DataFrame

from components.materials_quality import MaterialUnitCheck

BASE_PORTS = {"table_out", "findings", "report"}


def form_node(**settings):
    return MaterialUnitCheck().set(
        input_table=DataFrame({"stress": [1.0]}),
        ui_mode="form",
        unit_rules=[{"column": "stress", "source_unit": "MPa", "expected_unit": "Pa"}],
        **settings,
    )


def test_native_constructor_exposes_diagnostics_without_an_absent_conversion_port():
    node = MaterialUnitCheck()
    assert {output.name for output in node.outputs} == BASE_PORTS
    assert set(node._outputs_map) == BASE_PORTS
    template = node.to_frontend_node()["data"]["node"]
    assert {output["name"] for output in template["outputs"]} == BASE_PORTS
    assert template["template"]["convert_values"]["real_time_refresh"] is True
    assert template["template"]["convert_values"]["_input_type"] == "DropdownInput"
    assert template["template"]["convert_values"]["options"] == ["否", "是"]


def test_explicit_form_conversion_exposes_real_converted_values_and_can_be_disabled():
    node = form_node(convert_values=True)
    assert {output.name for output in node.outputs} == BASE_PORTS | {"converted_table"}
    assert node.build_converted_table()["stress"].tolist() == [1_000_000.0]
    node.set(convert_values=False)
    assert {output.name for output in node.outputs} == BASE_PORTS


@pytest.mark.parametrize("value,enabled", [(True, True), (False, False), ("是", True), ("否", False)])
def test_conversion_dropdown_and_legacy_boolean_calls_dispatch_real_booleans(value, enabled):
    node = form_node(convert_values=value)
    report = node.build_report().data
    assert report["metrics"]["converted"] is enabled
    assert ("converted_table" in {output.name for output in node.outputs}) is enabled
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert template["convert_values"]["value"] == ("是" if enabled else "否")


def test_shared_context_still_controls_conversion_despite_local_port_intent():
    from components.materials_quality import MaterialQualityContext

    node = form_node(convert_values=True)
    context = (
        MaterialQualityContext()
        .set(
            input_table=node.input_table,
            enabled_checks=["units"],
            unit_rules=[{"column": "stress", "source_unit": "MPa", "expected_unit": "Pa"}],
            convert_values=False,
        )
        .build_context()
    )
    node.set(quality_context=context)
    assert "converted_table" in {output.name for output in node.outputs}
    assert node.build_report().data["metrics"]["converted"] is False
    with pytest.raises(ValueError, match="不可用"):
        node.build_converted_table()


@pytest.mark.parametrize("enabled", [False, True])
def test_disabled_or_blocked_native_conversion_raises_instead_of_returning_empty(enabled):
    node = form_node(convert_values=enabled)
    if enabled:
        node.set(unit_rules=[{"column": "stress", "source_unit": "MPa", "expected_unit": "second"}])
    assert node.build_report().data["metrics"]["converted"] is False
    with pytest.raises(ValueError, match="conversion|换算|不可用"):
        node.build_converted_table()


def test_legacy_json_mode_keeps_four_ports_and_marks_its_unavailable_table():
    node = MaterialUnitCheck().set(
        input_table=DataFrame({"stress": [1.0]}),
        source_units_json='{"stress":"MPa"}',
        expected_units_json='{"stress":"Pa"}',
        convert_values=False,
    )
    assert {output.name for output in node.outputs} == BASE_PORTS | {"converted_table"}
    output = node.build_converted_table()
    assert output.empty and list(output.columns) == ["stress"]
    assert output.attrs["table_available"] is False
    assert output.attrs["absence_reason"]


def test_native_output_refresh_tracks_mode_and_conversion_toggle():
    node = form_node()
    frontend = node.to_frontend_node()["data"]["node"]
    updated = node.update_outputs(frontend, "convert_values", True)
    assert {
        output.name if hasattr(output, "name") else output["name"] for output in updated["outputs"]
    } == BASE_PORTS | {"converted_table"}
    updated = node.update_outputs(frontend, "convert_values", False)
    assert {
        output.name if hasattr(output, "name") else output["name"] for output in updated["outputs"]
    } == BASE_PORTS
    updated = node.update_outputs(frontend, "ui_mode", "json")
    assert {
        output.name if hasattr(output, "name") else output["name"] for output in updated["outputs"]
    } == BASE_PORTS | {"converted_table"}


def test_invalid_native_units_still_build_three_diagnostic_outputs_in_a_real_graph():
    from lfx.graph import Graph

    from examples.demo_source import MaterialDemoTable

    source = MaterialDemoTable().set(records_json='[{"stress":1.0}]')
    node = MaterialUnitCheck()
    node.set_id("native-unit-diagnostics")
    node.set(
        input_table=source.build_table,
        ui_mode="form",
        unit_rules=[{"column": "stress", "source_unit": "MPa", "expected_unit": "second"}],
    )
    graph = Graph.from_payload(json.loads(json.dumps(Graph(start=source, end=node).dump())))
    for step in graph.start():
        assert not hasattr(step, "valid") or step.valid, step
    results = graph.get_vertex("native-unit-diagnostics").results
    assert set(results) == BASE_PORTS
    assert results["report"].data["passed"] is False


def test_legacy_json_graph_roundtrip_keeps_its_flagged_absent_conversion_output():
    from lfx.graph import Graph

    from examples.demo_source import MaterialDemoTable

    source = MaterialDemoTable().set(records_json='[{"stress":1.0}]')
    node = MaterialUnitCheck()
    node.set_id("legacy-unit-diagnostics")
    node.set(
        input_table=source.build_table,
        source_units_json='{"stress":"MPa"}',
        expected_units_json='{"stress":"Pa"}',
        convert_values=False,
    )
    graph = Graph.from_payload(json.loads(json.dumps(Graph(start=source, end=node).dump())))
    for step in graph.start():
        assert not hasattr(step, "valid") or step.valid, step
    results = graph.get_vertex("legacy-unit-diagnostics").results
    assert set(results) == BASE_PORTS | {"converted_table"}
    assert results["converted_table"].empty
    assert results["converted_table"].attrs["table_available"] is False


def test_enabled_native_conversion_graph_roundtrip_builds_actual_converted_values():
    from lfx.graph import Graph

    from examples.demo_source import MaterialDemoTable

    source = MaterialDemoTable().set(records_json='[{"stress":1.0}]')
    node = MaterialUnitCheck()
    node.set_id("native-unit-conversion")
    node.set(
        input_table=source.build_table,
        ui_mode="form",
        unit_rules=[{"column": "stress", "source_unit": "MPa", "expected_unit": "Pa"}],
        convert_values="是",
    )
    graph = Graph.from_payload(json.loads(json.dumps(Graph(start=source, end=node).dump())))
    for step in graph.start():
        assert not hasattr(step, "valid") or step.valid, step
    results = graph.get_vertex("native-unit-conversion").results
    assert set(results) == BASE_PORTS | {"converted_table"}
    assert results["converted_table"]["stress"].tolist() == [1_000_000.0]
