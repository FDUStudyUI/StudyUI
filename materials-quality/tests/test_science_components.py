import json
from pathlib import Path

import pytest
from lfx.custom.eval import eval_custom_component_code
from lfx.schema import Data, DataFrame, Message

from materials_quality.science.catalog import component_class, entries, get
from materials_quality.science.ui_schema import science_outputs

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_has_distinct_real_operations():
    items = entries()
    assert len(items) == 48
    assert len({item["key"] for item in items}) == len(items)
    for item in items:
        assert callable(get(item["key"])["callable"])
        path = ROOT / "components" / item["directory"] / (item["filename"] + ".py")
        cls = eval_custom_component_code(path.read_text(encoding="utf-8"))
        node = cls()
        ports = node.to_frontend_node()["data"]["node"]["outputs"]
        assert {p["name"] for p in ports} == {p.name for p in science_outputs(item["key"])}
        fields = node.to_frontend_node()["data"]["node"]["template"]
        assert ("input_table" in fields) is item["table_input"]
        assert ("input_tables" in fields) is item["tables_input"]
        assert ("reports" in fields) is item["reports_input"]
        assert all(p["group_outputs"] for p in ports)


def test_native_connected_transform_units_stats_and_report(tmp_path):
    unit = component_class("preprocess.units")().set(
        input_table=DataFrame({"sample_id": ["001", "002"], "x": [1.0, 2.0]}),
        config_json=json.dumps({"source_units": {"x": "GPa"}, "target_units": {"x": "MPa"}}),
    )
    transformed = unit.build_table()
    assert transformed["x"].tolist() == [1000.0, 2000.0]
    assert isinstance(unit.build_report(), Data)
    stat = component_class("stats.grouped")().set(
        input_table=transformed,
        input_data=unit.build_report(),
        config_json='{"group":"sample_id","columns":["x"]}',
    )
    report = stat.build_report()
    assert len(report.data["provenance"]["lineage"]) == 2
    assert isinstance(stat.build_summary(), Message)
    export = component_class("export.report")().set(
        reports=[unit.build_report(), report],
        input_table=stat.build_table(),
        config_json=json.dumps({"output_dir": str(tmp_path)}),
    )
    result = export.build_report()
    assert result.data["data"]["verified"]
    html = Path(result.data["data"]["file_path"]).read_text(encoding="utf-8")
    assert "preprocess.units" in html and "stats.grouped" in html
    assert len(export.build_artifacts()) == 1


def test_native_cache_tracks_inputs_and_does_not_repeat_artifacts(tmp_path):
    node = component_class("export.table")().set(
        input_table=DataFrame({"id": ["001"]}),
        config_json=json.dumps({"output_dir": str(tmp_path)}),
    )
    first = node.build_report().data["artifacts"]
    assert node.build_report().data["artifacts"] == first
    assert node.build_artifacts()["path"].tolist() == first
    node.set(input_table=DataFrame({"id": ["002"]}))
    assert node.build_report().data["artifacts"] != first


def test_native_asset_resolution_input_file_hash_invalidation_and_secret_redaction(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("x\n1\n", encoding="utf-8")
    node = component_class("io.table_import")().set(
        input_data=Data(data={"asset_paths": {"source": str(path)}}),
        config_json='{"path":"@asset:source","Authorization":"Bearer TOPSECRET"}',
    )
    assert node.build_table()["x"].tolist() == [1]
    assert "TOPSECRET" not in json.dumps(node.build_report().data)
    path.write_text("x\n2\n", encoding="utf-8")
    assert node.build_table()["x"].tolist() == [2]
    assert node.build_report().data["data"]["asset_paths"]["source"] == str(path)


def test_native_configuration_rejects_nonfinite_json():
    node = component_class("preprocess.filter")().set(config_json='{"bad":NaN}')
    with pytest.raises(ValueError, match="JSON"):
        node.build_report()


def test_sdk_class_serializes_its_own_source_not_the_lfx_evaluator():
    from lfx.graph import Graph

    node = component_class("preprocess.filter")().set(input_table=DataFrame({"x": [1]}))
    payload = Graph(start=node, end=node).dump()
    code = payload["data"]["nodes"][0]["data"]["node"]["template"]["code"]["value"]
    assert "class SciencePreprocessFilter(" in code


def test_serialized_connected_graph_preserves_config_object():
    from lfx.graph import Graph

    from examples.demo_source import MaterialDemoTable

    source = MaterialDemoTable().set(records_json='[{"x":1,"y":2},{"x":3,"y":4}]')
    node = component_class("preprocess.filter")()
    node.set_id("native-config-test")
    node.set(
        input_table=source.build_table,
        config_json='{"conditions":[{"column":"x","op":"gt","value":1}],"columns":["x"]}',
    )
    payload = Graph(start=source, end=node).dump()
    imported = Graph.from_payload(json.loads(json.dumps(payload)))
    for step in imported.start():
        if hasattr(step, "valid"):
            assert step.valid, step
    result = imported.get_vertex("native-config-test").results["table"]
    assert result.to_dict("list") == {"x": [3]}


def test_cache_distinguishes_decimal_and_text_in_object_cells():
    from decimal import Decimal

    import pandas as pd

    node = component_class("preprocess.filter")().set(
        input_table=DataFrame({"x": pd.Series([Decimal("1")], dtype=object)}),
        config_json='{"conditions":[{"column":"x","op":"eq","value":"1"}]}',
    )
    assert len(node.build_table()) == 0
    original_hash = node.build_report().data["provenance"]["input_sha256"]
    node.set(input_table=DataFrame({"x": pd.Series(["1"], dtype=object)}))
    assert len(node.build_table()) == 1
    assert node.build_report().data["provenance"]["input_sha256"] != original_hash


def test_cache_invalidates_when_upstream_provenance_changes_without_data_change():
    def source(name):
        return Data(
            data={
                "schema_version": "science-result/1",
                "data": {"value": 1},
                "provenance": {"lineage": [{"operation": name}]},
            }
        )

    node = component_class("preprocess.filter")().set(
        input_table=DataFrame({"x": [1]}), input_data=source("SOURCE_A")
    )
    before = node.build_report().data
    node.set(input_data=source("SOURCE_B"))
    after = node.build_report().data
    assert before["provenance"]["input_sha256"] != after["provenance"]["input_sha256"]
    assert [r["operation"] for r in after["provenance"]["lineage"]] == ["SOURCE_B", "preprocess.filter"]


@pytest.mark.parametrize("values,enabled", [([1.0, 2.0], False), ([1.0, "?"], True)])
def test_quality_unit_native_sink_returns_diagnostics_when_conversion_unavailable(values, enabled):
    import asyncio

    from components.materials_quality.unit_check import MaterialUnitCheck

    node = MaterialUnitCheck().set(
        input_table=DataFrame({"x": values}),
        source_units_json='{"x":"MPa"}',
        expected_units_json='{"x":"Pa"}',
        convert_values=enabled,
    )
    results, _ = asyncio.run(node.build_results())
    assert isinstance(results["report"], Data)
    assert not results["report"].data["metrics"]["converted"]
    assert results["converted_table"].empty


def test_cache_tracks_ordered_categories_and_units_metadata():
    import pandas as pd

    def frame(order, unit):
        result = DataFrame({"grade": pd.Categorical(["lo", "hi"], categories=order, ordered=True)})
        result.attrs["units"] = {"grade": unit}
        return result

    node = component_class("preprocess.filter")().set(
        input_table=frame(["lo", "hi"], "label-a"),
        config_json='{"conditions":[{"column":"grade","op":"lt","value":"hi"}]}',
    )
    assert node.build_table()["grade"].tolist() == ["lo"]
    first = node.build_report().data["provenance"]["input_sha256"]
    node.set(input_table=frame(["hi", "lo"], "label-b"))
    assert node.build_table().empty
    assert node.build_report().data["provenance"]["input_sha256"] != first


def test_document_text_is_not_probed_as_a_local_file(tmp_path):
    secret = tmp_path / "private.txt"
    secret.write_text("private", encoding="utf-8")
    node = component_class("preprocess.filter")().set(
        input_table=DataFrame({"x": [1]}),
        input_data=Data(data={"documents": [{"text": str(secret), "path": str(secret)}]}),
    )
    assert node.build_report().data["provenance"]["source_files"] == {}


def test_preview_path_column_does_not_authorize_file_reads(tmp_path):
    secret = tmp_path / "private.txt"
    secret.write_text("private", encoding="utf-8")
    first = component_class("preprocess.filter")().set(input_table=DataFrame({"path": [str(secret)]}))
    second = component_class("preprocess.filter")().set(
        input_table=DataFrame({"x": [1]}), input_data=first.build_report()
    )
    assert second.build_report().data["provenance"]["source_files"] == {}


@pytest.mark.parametrize("dictionary_form", [False, True])
def test_report_cache_tracks_explicit_figure_contents(tmp_path, dictionary_form):
    from PIL import Image

    path = tmp_path / "figure.png"
    Image.new("RGB", (2, 2), "red").save(path)
    figure = {"path": str(path)} if dictionary_form else str(path)
    report = component_class("export.report")().set(
        input_data=Data(data={"figures": [figure]}), config_json=json.dumps({"output_dir": str(tmp_path)})
    )
    first = report.build_report().data
    Image.new("RGB", (3, 3), "blue").save(path)
    second = report.build_report().data
    assert second["data"]["figures"][0]["size"] == [3, 3]
    assert first["provenance"]["input_sha256"] != second["provenance"]["input_sha256"]


def test_aggregate_report_contains_table_only_statistics_and_states_preview_bounds(tmp_path):
    node = component_class("stats.grouped")().set(
        input_table=DataFrame({"group": ["A", "A"], "value": [10000.0, 12345.0]}),
        config_json='{"group":"group","columns":["value"]}',
    )
    report = node.build_report()
    assert report.data["table_preview"]["records"][0]["mean"] == 11172.5
    export = component_class("export.report")().set(
        reports=[report], config_json=json.dumps({"output_dir": str(tmp_path)})
    )
    html = Path(export.build_report().data["data"]["file_path"]).read_text(encoding="utf-8")
    assert "11172.5" in html and "stats.grouped" in html
    large = component_class("preprocess.filter")().set(input_table=DataFrame({"x": list(range(150))}))
    preview = large.build_report().data["table_preview"]
    assert preview["total_rows"] == 150 and preview["included_rows"] == 100 and preview["truncated"]
