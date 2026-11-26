import json

import pytest
from lfx.schema import Data, DataFrame

from materials_quality.context import table_fingerprint
from materials_quality.science.catalog import component_class


def test_native_metadata_only_input_change_invalidates_execution_cache():
    table = DataFrame({"curve": ["a", "a"], "x": [1.0, 2.0], "y": [2.0, 3.0]})
    # A pre-V2 attrs declaration must not silently pass as trusted semantics.
    table.attrs["contract"] = {"granularity": "point"}
    node = component_class("preprocess.filter")().set(input_table=table, config_json="{}")
    with pytest.raises(ValueError, match="contract|schema"):
        node.build_report()


def test_native_envelope_restores_contract_and_preserves_rename():
    from materials_quality.science.table_contract import attach_contract, make_contract, read_contract

    source = DataFrame({"curve": ["a", "a"], "x": [1.0, 2.0], "y": [2.0, 3.0]})
    source = attach_contract(
        source,
        make_contract(source, granularity="point", roles={"curve_id": "curve", "x": "x", "response": "y"}),
    )
    node = component_class("preprocess.filter")().set(
        input_table=source, config_json='{"rename":{"y":"signal"}}'
    )
    report = node.build_report().data
    assert report["table_contract"]["roles"]["response"] == "signal"
    table = node.build_table()
    table.attrs = {}
    downstream = component_class("preprocess.filter")().set(
        input_table=table, input_data=Data(data=json.loads(json.dumps(report))), config_json="{}"
    )
    assert read_contract(downstream.build_table())["roles"]["response"] == "signal"


def test_native_cache_tracks_contract_identity_and_rejects_upstream_conflict():
    from materials_quality.science.table_contract import attach_contract, make_contract

    source = DataFrame({"x": [1.0, 2.0], "y": [2.0, 3.0]})
    first = attach_contract(
        source, make_contract(source, granularity="point", roles={"x": "x", "response": "y"})
    )
    second = attach_contract(
        source, make_contract(source, granularity="peak", roles={"x": "x", "response": "y"})
    )
    node = component_class("preprocess.filter")().set(input_table=first, config_json="{}")
    report = node.build_report().data
    node.set(input_table=second)
    assert node.build_report().data["provenance"]["input_sha256"] != report["provenance"]["input_sha256"]
    node.set(input_data=Data(data=report))
    with pytest.raises(ValueError, match="conflict|mismatch"):
        node.build_report()


def test_native_features_port_accepts_its_explicit_contract_in_result_envelope():
    from materials_quality.science.table_contract import attach_contract, make_contract, read_contract

    table = DataFrame({"curve": ["a"], "x": [1.0], "y": [2.0]})
    table_contract = make_contract(table, granularity="point", roles={"x": "x", "response": "y"})
    feature_contract = make_contract(table, granularity="curve", roles={"curve_id": "curve"})
    table = attach_contract(table, feature_contract)
    node = component_class("preprocess.filter")().set(
        input_table=table,
        input_data=Data(
            data={
                "schema_version": "science-result/1",
                "data": {},
                "table_contract": table_contract,
                "features_contract": feature_contract,
                "table_fingerprint": table_fingerprint(table),
                "features_fingerprint": table_fingerprint(table),
            }
        ),
        config_json="{}",
    )
    assert read_contract(node.build_table())["granularity"] == "curve"


def test_batch_rename_updates_contract_and_report_before_next_operation(tmp_path):
    from materials_quality.batch.execution import _rename
    from materials_quality.batch.packet import make_batch, make_item, unpack_table
    from materials_quality.science.table_contract import attach_contract, make_contract, read_contract

    table = DataFrame({"x": [1.0, 2.0], "y": [2.0, 3.0]})
    table = attach_contract(
        table, make_contract(table, granularity="point", roles={"x": "x", "response": "y"})
    )
    renamed = _rename(table, {"y": "signal"})
    assert read_contract(renamed)["roles"]["response"] == "signal"
    batch = make_batch([make_item("one", "One", {}, table)])
    node = component_class("preprocess.filter")().set(
        input_data=Data(data=batch),
        config_json=json.dumps({"output_dir": str(tmp_path), "rename": {"y": "signal"}}),
    )
    output = node.build_report().data
    restored = unpack_table(output["items"][0]["table"])
    assert read_contract(restored) == output["items"][0]["report"]["table_contract"]


def test_research_envelope_reinjects_only_unambiguous_matching_contract():
    from materials_quality.science.table_contract import make_contract, read_contract

    table = DataFrame({"x": [1.0, 2.0], "y": [2.0, 3.0]})
    contract = make_contract(table, granularity="point", roles={"x": "x", "response": "y"})
    upstream = {
        "schema_version": "research-result/1",
        "tables": {
            "curves": {"columns": ["x", "y"], "contract": contract, "fingerprint": table_fingerprint(table)}
        },
    }
    node = component_class("preprocess.filter")().set(
        input_table=table, input_data=Data(data=upstream), config_json="{}"
    )
    assert read_contract(node.build_table())["granularity"] == "point"
    other = make_contract(table, granularity="peak", roles={"x": "x"})
    node.set(
        input_data=Data(
            data={
                "table_contract": contract,
                "features_contract": other,
                "table_fingerprint": table_fingerprint(table),
                "features_fingerprint": table_fingerprint(table),
            }
        )
    )
    with pytest.raises(ValueError, match="ambiguous"):
        node.build_report()


def unit_envelope(schema, contract, units, table):
    metadata = {"columns": ["curve_id", "x", "y"], "units": units}
    bound = table.copy(deep=True)
    bound.attrs = {"units": units}
    fingerprint = table_fingerprint(bound)
    if schema == "research-result/1":
        return {
            "schema_version": schema,
            "tables": {"curves": {**metadata, "contract": contract, "fingerprint": fingerprint}},
        }
    return {
        "schema_version": schema,
        "data": {},
        "table_contract": contract,
        "table_preview": metadata,
        "table_fingerprint": fingerprint,
    }


@pytest.mark.parametrize("schema", ["research-result/1", "science-result/1"])
@pytest.mark.parametrize("attrs", [{}, {"units": {}}])
def test_attrs_free_envelope_restores_units_before_filter_and_rename(schema, attrs):
    from copy import deepcopy

    from materials_quality.science.table_contract import make_contract, read_contract

    table = DataFrame({"curve_id": ["c", "c"], "x": [500.0, 510.0], "y": [2.0, 3.0]})
    table.attrs["units"] = {"x": "nm", "y": "counts"}
    contract = make_contract(
        table, granularity="point", roles={"curve_id": "curve_id", "x": "x", "response": "y"}
    )
    table.attrs = deepcopy(attrs)
    before = deepcopy(table.attrs)
    node = component_class("preprocess.filter")().set(
        input_table=table,
        input_data=Data(data=unit_envelope(schema, contract, {"x": "nm", "y": "counts"}, table)),
        config_json='{"rename":{"y":"signal"}}',
    )
    output = node.build_table()
    assert output.attrs["units"] == {"x": "nm", "signal": "counts"}
    assert read_contract(output)["units_state"]["units"] == output.attrs["units"]
    assert table.attrs == before


@pytest.mark.parametrize("schema", ["research-result/1", "science-result/1"])
def test_envelope_rejects_units_conflicting_with_contract_or_existing_attrs(schema):
    from materials_quality.science.table_contract import make_contract

    table = DataFrame({"curve_id": ["c"], "x": [500.0], "y": [2.0]})
    table.attrs["units"] = {"x": "nm", "y": "counts"}
    contract = make_contract(table, granularity="point", roles={"x": "x", "response": "y"})
    table.attrs = {}
    node = component_class("preprocess.filter")().set(
        input_table=table,
        input_data=Data(data=unit_envelope(schema, contract, {"x": "um", "y": "counts"}, table)),
        config_json="{}",
    )
    with pytest.raises(ValueError, match="unit|单位"):
        node.build_report()
    table.attrs["units"] = {"x": "um"}
    node.set(input_data=Data(data=unit_envelope(schema, contract, {"x": "nm", "y": "counts"}, table)))
    with pytest.raises(ValueError, match="unit|单位"):
        node.build_report()


@pytest.mark.parametrize("schema", ["research-result/1", "science-result/1"])
def test_duplicate_matching_contracts_cannot_hide_conflicting_unit_metadata(schema):
    from materials_quality.science.table_contract import make_contract

    table = DataFrame({"curve_id": ["c"], "x": [500.0], "y": [2.0]})
    contract = make_contract(table, granularity="point", roles={"x": "x", "response": "y"})
    upstream = unit_envelope(schema, contract, {"x": "nm"}, table)
    if schema == "research-result/1":
        upstream["tables"]["features"] = {
            "columns": list(table.columns),
            "contract": contract,
            "units": {"x": "um"},
            "fingerprint": upstream["tables"]["curves"]["fingerprint"],
        }
    else:
        upstream.update(
            features_contract=contract,
            features_preview={"columns": list(table.columns), "units": {"x": "um"}},
            features_fingerprint=upstream["table_fingerprint"],
        )
    node = component_class("preprocess.filter")().set(
        input_table=table, input_data=Data(data=upstream), config_json="{}"
    )
    with pytest.raises(ValueError, match="unit|ambiguous"):
        node.build_report()


@pytest.mark.parametrize("schema", ["research-result/1", "science-result/1"])
@pytest.mark.parametrize("attached", [False, True])
def test_envelope_value_binding_rejects_same_schema_rescaled_table(schema, attached):
    from copy import deepcopy

    from materials_quality.science.table_contract import attach_contract, make_contract

    original = DataFrame({"curve_id": ["c", "c"], "x": [500.0, 510.0], "y": [2.0, 3.0]})
    original.attrs["units"] = {"x": "nm", "y": "counts"}
    contract = make_contract(original, granularity="point", roles={"x": "x", "response": "y"})
    upstream = unit_envelope(schema, contract, original.attrs["units"], original)
    changed = original.assign(x=original.x / 1000.0)
    changed.attrs = {}
    if attached:
        changed = attach_contract(changed, contract)
    before = deepcopy(changed.attrs)
    node = component_class("preprocess.filter")().set(
        input_table=changed, input_data=Data(data=upstream), config_json="{}"
    )
    with pytest.raises(ValueError, match="fingerprint|binding|mismatch"):
        node.build_report()
    assert changed.attrs == before
    assert changed.x.tolist() == [0.5, 0.51]


@pytest.mark.parametrize("schema", ["research-result/1", "science-result/1"])
def test_contract_report_without_output_value_binding_is_rejected(schema):
    from materials_quality.science.table_contract import make_contract

    table = DataFrame({"curve_id": ["c"], "x": [500.0], "y": [2.0]})
    contract = make_contract(table, granularity="point", roles={"x": "x"})
    upstream = unit_envelope(schema, contract, {}, table)
    if schema == "research-result/1":
        upstream["tables"]["curves"].pop("fingerprint")
    else:
        upstream.pop("table_fingerprint")
    node = component_class("preprocess.filter")().set(
        input_table=table, input_data=Data(data=upstream), config_json="{}"
    )
    with pytest.raises(ValueError, match="binding|fingerprint"):
        node.build_report()


def test_science_report_binds_actual_output_table_and_legacy_report_remains_usable():
    table = DataFrame({"x": [500.0, 510.0], "y": [2.0, 3.0]})
    node = component_class("preprocess.filter")().set(
        input_table=table,
        input_data=Data(data={"schema_version": "science-result/1", "data": {}}),
        config_json="{}",
    )
    output = node.build_table()
    report = node.build_report().data
    assert report["table_fingerprint"] == table_fingerprint(output)
    assert report["features_fingerprint"] is None


def test_output_value_binding_disambiguates_same_column_reports():
    from materials_quality.science.table_contract import make_contract, read_contract

    table = DataFrame({"x": [500.0, 510.0], "y": [2.0, 3.0]})
    other = table.assign(y=[20.0, 30.0])
    point = make_contract(table, granularity="point", roles={"x": "x"})
    peak = make_contract(other, granularity="peak", roles={"x": "x"})
    upstream = {
        "table_contract": point,
        "features_contract": peak,
        "table_fingerprint": table_fingerprint(table),
        "features_fingerprint": table_fingerprint(other),
    }
    node = component_class("preprocess.filter")().set(
        input_table=other, input_data=Data(data=upstream), config_json="{}"
    )
    assert read_contract(node.build_table())["granularity"] == "peak"


def test_batch_report_fingerprint_binds_post_import_rename_and_identifiers(tmp_path):
    from materials_quality.batch.packet import unpack_table
    from materials_quality.batch.source import files_batch

    path = tmp_path / "spectrum.csv"
    path.write_text("x,y\n500,2\n510,3\n", encoding="utf-8")
    packet = files_batch([path], rename_columns={"y": "signal"})
    node = component_class("io.table_import")().set(input_data=Data(data=packet), config_json="{}")
    result = node.build_report().data
    assert result["counts"]["failed"] == 0
    item = result["items"][0]
    table = unpack_table(item["table"])
    assert item["report"]["table_fingerprint"] == table_fingerprint(table)
    assert item["report"]["table_preview"]["columns"] == list(table.columns)
