"""Scientific meaning survives transport independently of numeric fingerprints."""

import importlib
import json
from copy import deepcopy

import pandas as pd
import pytest

from materials_quality.batch.packet import combined_table, make_batch, make_item, pack_table, unpack_table
from materials_quality.context import table_fingerprint


@pytest.fixture
def api():
    return importlib.import_module("materials_quality.science.table_contract")


def point_table():
    return pd.DataFrame(
        {
            "curve": ["001", "001", "002", "002"],
            "sample": [1, 1, 2, 2],
            "group": ["a", "a", "b", "b"],
            "x": [1.0, 2.0, 1.0, 2.0],
            "y": [2.0, 3.0, 4.0, 5.0],
        }
    )


def point_contract(api, table):
    return api.make_contract(
        table,
        granularity="point",
        roles={
            "curve_id": "curve",
            "sample_id": "sample",
            "experimental_unit": "sample",
            "group": "group",
            "x": "x",
            "response": "y",
        },
        experimental_design={"kind": "independent", "confirmed": True},
    )


def test_contract_identity_changes_without_changing_legacy_numeric_fingerprint(api):
    table = point_table()
    first = api.attach_contract(table, point_contract(api, table))
    second_contract = api.make_contract(table, granularity="peak", roles={"curve_id": "curve", "x": "x"})
    second = api.attach_contract(table, second_contract)
    assert table_fingerprint(first) == table_fingerprint(second)
    assert api.contract_identity(first) != api.contract_identity(second)
    assert "contract" not in table.attrs
    assert len(api.contract_identity(first)) == 64


def test_long_point_ids_and_same_entity_role_are_legal_but_incompatible_roles_are_not(api):
    table = point_table()
    contract = point_contract(api, table)
    assert contract["granularity"] == "point"
    assert contract["roles"]["sample_id"] == contract["roles"]["experimental_unit"]
    with pytest.raises(ValueError, match="role"):
        api.make_contract(table, granularity="point", roles={"x": "x", "response": "x"})
    with pytest.raises(ValueError, match="granularity"):
        api.make_contract(table, granularity=3, roles={})


def test_entity_cannot_cross_groups_and_curve_grain_rejects_repeated_curve_records(api):
    table = point_table()
    with pytest.raises(ValueError, match="curve|granularity"):
        api.make_contract(table, granularity="curve", roles={"curve_id": "curve"})
    table.loc[1, "group"] = "b"
    with pytest.raises(ValueError, match="group"):
        point_contract(api, table)


def test_contract_is_strict_bounded_json_and_detects_tamper(api):
    table = point_table()
    attached = api.attach_contract(table, point_contract(api, table))
    attached.attrs["contract"]["granularity"] = "sample"
    with pytest.raises(ValueError, match="hash|sha256"):
        api.read_contract(attached)
    for invalid in ({"noise": float("nan")}, {"noise": object()}, {"noise": "x" * 70000}):
        with pytest.raises(ValueError, match="JSON|limit|finite"):
            api.make_contract(table, granularity="point", roles={}, units_state=invalid)


def test_rename_filter_normalization_and_grouped_history_preserve_only_valid_semantics(api):
    source = point_table()
    source = api.attach_contract(source, point_contract(api, source))
    renamed = api.propagate_contract(
        source, source.rename(columns={"y": "signal"}), "rename", {"rename": {"y": "signal"}}
    )
    assert api.read_contract(renamed)["roles"]["response"] == "signal"
    filtered = api.propagate_contract(source, source.iloc[:2].copy(), "filter")
    assert api.read_contract(filtered)["granularity"] == "point"
    normalized = api.propagate_contract(
        source, source.assign(y=source.y / source.y.max()), "normalize", {"columns": ["y"]}
    )
    assert api.read_contract(normalized)["experimental_design"]["confirmed"]
    grouped = source.groupby("group", as_index=False).agg(mean=("y", "mean"))
    grouped = api.propagate_contract(source, grouped, "grouped", {"group": "group"})
    contract = api.read_contract(grouped)
    assert contract["granularity"] == "group_summary"
    assert contract["roles"] == {"group": "group"}
    assert not contract["experimental_design"]["confirmed"]
    assert contract["derived_from"][-1]["contract_sha256"] == api.contract_identity(source)
    assert contract["aggregation"][-1]["operation"] == "grouped"


def test_unknown_transformation_clears_semantics_and_records_provenance(api):
    source = point_table()
    source = api.attach_contract(source, point_contract(api, source))
    target = api.propagate_contract(source, source.copy(), "arbitrary_join")
    assert api.read_contract(target) is None
    assert target.attrs["contract_provenance"][-1]["operation"] == "arbitrary_join"
    assert target.attrs["contract_warnings"]


def test_batch_contract_is_explicit_roundtrip_validated_and_identifiers_do_not_change_grain(api):
    table = point_table()
    table = api.attach_contract(table, point_contract(api, table))
    encoded = pack_table(table)
    assert encoded["contract"] == api.read_contract(table)
    # The explicit field remains authoritative after attrs is dropped by a consumer.
    encoded["attrs"] = ["dict", {}]
    restored = unpack_table(json.loads(json.dumps(encoded)))
    assert api.contract_identity(restored) == api.contract_identity(table)
    batch = make_batch([make_item("one", "One", {}, table)])
    combined = combined_table(batch)
    assert api.read_contract(combined)["granularity"] == "point"
    tampered = deepcopy(encoded)
    tampered["contract"]["roles"]["response"] = "x"
    with pytest.raises(ValueError, match="hash|sha256|role"):
        unpack_table(tampered)


def test_batch_contract_mismatch_between_attrs_and_explicit_field_rejected(api):
    table = point_table()
    table = api.attach_contract(table, point_contract(api, table))
    encoded = pack_table(table)
    encoded["contract"] = api.make_contract(table, granularity="peak", roles={"x": "x"})
    with pytest.raises(ValueError, match="conflict|mismatch"):
        unpack_table(encoded)


@pytest.mark.parametrize(
    "design",
    [{"kind": [], "confirmed": False}, {"kind": "independent", "confirmed": True, "aggregation_unit": []}],
)
def test_malformed_design_has_actionable_validation_error(api, design):
    with pytest.raises(ValueError, match="experimental_design|experimental design"):
        api.make_contract(
            point_table(),
            granularity="point",
            roles={"experimental_unit": "sample"},
            experimental_design=design,
        )


def test_normalizing_identity_columns_clears_entity_claims(api):
    table = point_table()
    table = api.attach_contract(table, point_contract(api, table))
    result = api.propagate_contract(
        table, table.assign(sample=[0.0, 0.0, 1.0, 1.0]), "normalize", {"columns": ["sample"]}
    )
    assert api.read_contract(result) is None
    assert result.attrs["contract_warnings"]


def test_concat_with_mixed_declared_grain_clears_inherited_contract(api):
    table = point_table()
    declared = api.attach_contract(table, point_contract(api, table))
    batch = make_batch([make_item("one", "One", {}, declared), make_item("two", "Two", {}, table)])
    result = combined_table(batch)
    assert api.read_contract(result) is None
    assert result.attrs["contract_warnings"]


def test_explicit_independent_curve_can_be_its_sample_and_unit(api):
    table = pd.DataFrame({"id": ["001", "002"], "value": [1.0, 2.0]})
    roles = {"curve_id": "id", "sample_id": "id", "experimental_unit": "id", "response": "value"}
    contract = api.make_contract(
        table,
        granularity="curve",
        roles=roles,
        experimental_design={"kind": "independent", "confirmed": True},
    )
    assert contract["roles"] == roles


def test_unit_conversion_of_response_does_not_clear_unchanged_entity_ids(api):
    table = point_table()
    table = api.attach_contract(table, point_contract(api, table))
    result = api.propagate_contract(
        table,
        table.assign(y=table.y * 1000),
        "units",
        {"source_units": {"y": "GPa"}, "target_units": {"y": "MPa"}},
    )
    assert api.read_contract(result)["experimental_design"]["confirmed"]


def test_excessive_nesting_rejected_before_recursive_copy(api):
    nested = {}
    for _ in range(1200):
        nested = {"nested": nested}
    with pytest.raises(ValueError, match="limit"):
        api.make_contract(point_table(), granularity="point", roles={}, units_state=nested)


@pytest.mark.parametrize("kind", ["independent", "paired"])
def test_unit_grain_is_unique_per_variable_and_paired_condition(api, kind):
    table = pd.DataFrame(
        {
            "unit": ["u1", "u1", "u2", "u2"],
            "group": ["a", "a", "b", "b"],
            "variable": ["modulus", "yield", "modulus", "yield"],
            "value": [1.0, 2.0, 3.0, 4.0],
        }
    )
    if kind == "paired":
        table.loc[2:, "unit"] = "u1"
    roles = {"experimental_unit": "unit", "group": "group", "variable": "variable", "response": "value"}
    design = {"kind": kind, "confirmed": False}
    contract = api.make_contract(
        table, granularity="experimental_unit", roles=roles, experimental_design=design
    )
    assert contract["experimental_design"] == design
    duplicate = pd.concat([table, table.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="granularity"):
        api.make_contract(duplicate, granularity="experimental_unit", roles=roles, experimental_design=design)


def test_filter_propagation_preserves_contract_only_units_without_mutating_input(api):
    table = point_table()
    contract = api.make_contract(
        table,
        granularity="point",
        roles={"x": "x", "response": "y"},
        units_state={"source": "explicit_task_parameters", "units": {"x_unit": "nm", "y_unit": "counts"}},
    )
    source = api.attach_contract(table, contract)
    output = api.propagate_contract(source, source.iloc[:2].copy(), "filter")
    assert api.read_contract(output)["units_state"]["units"] == {"x": "nm", "y": "counts"}
    assert output.attrs["units"] == {"x": "nm", "y": "counts"}
    assert "units" not in source.attrs


def test_direct_rename_updates_pandas_inherited_unit_labels(api):
    table = point_table()
    table.attrs["units"] = {"x": "nm", "y": "counts"}
    source = api.attach_contract(table, point_contract(api, table))
    target = source.rename(columns={"y": "signal"})
    output = api.propagate_contract(source, target, "rename", {"rename": {"y": "signal"}})
    assert output.attrs["units"] == {"x": "nm", "signal": "counts"}
    assert source.attrs["units"] == {"x": "nm", "y": "counts"}
