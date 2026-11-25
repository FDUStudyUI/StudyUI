import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from materials_quality.context import table_fingerprint
from materials_quality.science.preprocessing import merge_tables
from materials_quality.science.table_contract import (
    attach_contract,
    make_contract,
    propagate_contract,
    read_contract,
)


def associate(master, *features, **config):
    return merge_tables(table=master, tables=list(features), config={"method": "specimen", **config})


def declared(table, granularity, roles):
    return attach_contract(table, make_contract(table, granularity=granularity, roles=roles))


def test_composite_join_keeps_master_order_and_reports_both_sides_of_unmatched():
    master = pd.DataFrame({"lot": ["X", "Y", "X"], "sample_id": ["001", "001", "002"]}, index=[4, 2, 9])
    electrical = pd.DataFrame({"lot": ["Y", "X", "Z"], "sample_id": ["001", "002", "001"], "R": [8, 9, 7]})
    electrical.attrs.update(units={"R": "ohm"}, source_name="electrical.csv")
    optical = pd.DataFrame({"lot": ["X"], "sample_id": ["001"], "peak_nm": [610]})
    optical.attrs["units"] = {"peak_nm": "nm"}
    originals = [frame.copy(deep=True) for frame in (master, electrical, optical)]

    result = associate(master, electrical, optical, on=["lot", "sample_id"], allow_undeclared_features=True)

    assert_frame_equal(result.table[master.columns], master)
    assert result.table["R"].isna().tolist() == [True, False, False]
    assert result.table["R"].dropna().tolist() == [8, 9]
    assert result.table["peak_nm"].dropna().tolist() == [610]
    first = result.data["association"]["features"][0]
    assert first["cardinality"] == "one_to_one"
    assert first["matched_rows"] == 2
    assert first["missing_master_rows"] == first["orphan_feature_rows"] == 1
    assert first["missing_master_preview"] == [{"lot": "X", "sample_id": "001"}]
    assert first["orphan_feature_preview"] == [{"lot": "Z", "sample_id": "001"}]
    assert result.warnings
    assert result.table.attrs["units"] == {"R": "ohm", "peak_nm": "nm"}
    assert read_contract(result.table)["granularity"] == "sample"
    assert result.data["sources"][1]["source_name"] == "electrical.csv"
    assert result.data["sources"][1]["table_sha256"] == table_fingerprint(electrical)
    for frame, original in zip((master, electrical, optical), originals, strict=True):
        assert_frame_equal(frame, original)
        assert frame.attrs == original.attrs


def test_exact_keys_preserve_large_integer_identity():
    master = pd.DataFrame({"id": [2**63, 2**63 + 1]}, dtype="uint64")
    feature = pd.DataFrame({"id": pd.Series([2**63 + 1, 2**63], dtype=object), "value": [20, 10]})
    result = associate(master, feature, on="id", allow_undeclared_features=True)
    assert result.table["value"].tolist() == [10, 20]
    assert result.table["id"].tolist() == [2**63, 2**63 + 1]


def test_composite_association_history_does_not_validate_transformed_keys():
    master = pd.DataFrame({"lot": [2, 1], "sample": ["S", "S"]})
    feature = master.assign(response=[20, 10])
    keys = ["lot", "sample"]
    original = associate(master, feature, on=keys, allow_undeclared_features=True).table
    assert associate(master, original, on=keys).table["response"].tolist() == [20, 10]
    changed = propagate_contract(original, original.assign(lot=[1, 2]), "normalize", {"columns": ["lot"]})
    with pytest.raises(ValueError, match="specimen identity.*keys"):
        associate(master, changed, on=keys)


def test_declared_composite_master_key_cannot_be_narrowed():
    base = pd.DataFrame({"lot": ["L1"], "sample": ["S1"]})
    master = associate(
        base, base.assign(optical=[5]), on=["lot", "sample"], allow_undeclared_features=True
    ).table
    feature = pd.DataFrame({"sample": ["S1"], "electrical": [8]})
    with pytest.raises(ValueError, match="specimen identity.*keys"):
        associate(master, feature, on="sample", allow_undeclared_features=True)


@pytest.mark.parametrize(
    ("master_ids", "feature_ids", "message"),
    [
        (["S1", "S1"], ["S1"], "master.*duplicate.*S1"),
        (["S1"], ["S1", "S1"], "feature table 1.*duplicate.*S1"),
        (["S1"], [""], "feature table 1.*missing"),
        (["001"], [1], "incompatible key types"),
        ([True], [1], "strings or integers"),
    ],
)
def test_invalid_keys_fail_before_association(master_ids, feature_ids, message):
    master = pd.DataFrame({"id": master_ids})
    feature = pd.DataFrame({"id": feature_ids, "value": range(len(feature_ids))})
    with pytest.raises(ValueError, match=message):
        associate(master, feature, on=["id"], allow_undeclared_features=True)


def test_require_complete_coverage_reports_missing_and_orphan_counts():
    master = pd.DataFrame({"id": ["S1", "S2"]})
    feature = pd.DataFrame({"id": ["S1", "S3"], "value": [1, 3]})
    with pytest.raises(ValueError, match="1 missing master.*1 orphan.*S2.*S3"):
        associate(master, feature, on=["id"], allow_undeclared_features=True, unmatched="error")


def test_declared_feature_needs_specimen_role_on_keys_and_feature_grain():
    master = pd.DataFrame({"id": ["S1"]})
    raw = pd.DataFrame({"id": ["S1"], "curve": ["C1"], "value": [1]})
    with pytest.raises(ValueError, match="undeclared.*feature"):
        associate(master, raw, on=["id"])
    with pytest.raises(ValueError, match="grain.*point"):
        point = declared(raw, "point", {"sample_id": "id"})
        associate(master, point, on=["id"], allow_undeclared_features=True)
    with pytest.raises(ValueError, match="specimen identity.*keys"):
        associate(master, declared(raw, "curve", {"curve_id": "curve"}), on=["id"])

    feature = declared(raw, "curve", {"curve_id": "curve", "sample_id": "id"})
    result = associate(master, feature, on=["id"])
    assert result.table["value"].tolist() == [1]
    assert result.data["association"]["features"][0]["input_grain"] == "curve"
    assert read_contract(result.table)["roles"] == {"sample_id": "id"}
    assert result.data["sources"][1]["contract_sha256"] == read_contract(feature)["contract_sha256"]


def test_coordinate_or_replicate_roles_cannot_be_used_as_specimen_keys():
    master = pd.DataFrame({"id": ["S1", "S1"], "repeat": [1, 2]})
    feature = declared(
        master.assign(curve=["C1", "C2"], value=[1, 2]),
        "curve",
        {"sample_id": "id", "curve_id": "curve", "technical_replicate": "repeat"},
    )
    with pytest.raises(ValueError, match="specimen keys.*technical_replicate"):
        associate(master, feature, on=["id", "repeat"])


def test_curve_feature_grain_requires_curve_identity():
    master = pd.DataFrame({"id": ["S1", "S2"]})
    feature = declared(master.assign(value=[3, 4]), "curve", {"sample_id": "id"})
    with pytest.raises(ValueError, match="curve.*curve_id"):
        associate(master, feature, on="id")


def test_long_features_cannot_mix_measured_variables_in_one_column():
    master = pd.DataFrame({"id": ["S1", "S2"]})
    feature = declared(
        master.assign(metric=["resistance", "capacitance"], value=[3, 4]),
        "experimental_unit",
        {"experimental_unit": "id", "variable": "metric", "value": "value"},
    )
    with pytest.raises(ValueError, match="multiple measured variables"):
        associate(master, feature, on="id")


def test_feature_column_collisions_need_explicit_rename_and_units_are_checked():
    master = pd.DataFrame({"id": ["S1"], "value": [1]})
    master.attrs["units"] = {"value": "V"}
    feature = pd.DataFrame({"id": ["S1"], "value": [1]})
    feature.attrs["units"] = {"value": "mV"}
    with pytest.raises(ValueError, match="conflicting units for value"):
        associate(master, feature, on=["id"], allow_undeclared_features=True)
    feature.attrs["units"] = {"value": "V"}
    with pytest.raises(ValueError, match="(?i)duplicate non-key.*value.*rename"):
        associate(master, feature, on=["id"], allow_undeclared_features=True)


def test_master_contract_and_bound_units_are_preserved():
    master = pd.DataFrame({"id": ["S1", "S2"], "group": ["A", "B"]})
    master = attach_contract(
        master,
        make_contract(
            master,
            granularity="experimental_unit",
            roles={"experimental_unit": "id", "group": "group"},
            experimental_design={"kind": "independent", "confirmed": True},
            aggregation=[{"operation": "explicit_summary"}],
        ),
    )
    feature = pd.DataFrame({"id": ["S1"], "I": [1]})
    feature = attach_contract(
        feature,
        make_contract(
            feature, granularity="sample", roles={"sample_id": "id"}, units_state={"units": {"I": "A"}}
        ),
    )
    result = associate(master, feature, on="id")
    contract = read_contract(result.table)
    assert contract["granularity"] == "experimental_unit"
    assert contract["roles"] == {"experimental_unit": "id", "group": "group"}
    assert contract["experimental_design"] == {"kind": "independent", "confirmed": True}
    assert contract["aggregation"] == [{"operation": "explicit_summary"}]
    assert result.table.attrs["units"] == {"I": "A"}


def test_experimental_unit_contract_requires_its_unit_key_even_with_a_sample_role():
    master = declared(
        pd.DataFrame({"sample": ["S1", "S2"], "master_unit": ["M1", "M2"]}),
        "experimental_unit",
        {"sample_id": "sample", "experimental_unit": "master_unit"},
    )
    feature = declared(
        pd.DataFrame({"sample": ["S1", "S2"], "feature_unit": ["F1", "F2"], "value": [1, 2]}),
        "experimental_unit",
        {"sample_id": "sample", "experimental_unit": "feature_unit"},
    )
    sample_only_master = master[["sample"]].copy()
    sample_only_master.attrs = {}
    with pytest.raises(ValueError, match="master.*specimen identity.*keys"):
        associate(master, feature, on="sample")
    with pytest.raises(ValueError, match="feature.*specimen identity.*keys"):
        associate(sample_only_master, feature, on="sample")


def test_native_merge_cache_refreshes_source_evidence_when_only_source_attrs_change():
    from lfx.schema import DataFrame

    from materials_quality.science.catalog import component_class

    master = DataFrame({"sample_id": ["S1"]})
    feature = DataFrame({"sample_id": ["S1"], "value": [1]})
    feature.attrs.update(source_name="old.csv", source_sha256="1" * 64)
    node = component_class("preprocess.merge")().set(
        input_table=master,
        input_tables=[feature],
        cfg_method="specimen",
        cfg_on=["sample_id"],
        cfg_allow_undeclared_features=True,
    )
    first = node.build_report().data["data"]["sources"][1]

    feature.attrs.update(source_name="new.csv", source_sha256="2" * 64)
    second = node.build_report().data["data"]["sources"][1]
    assert first["table_sha256"] == second["table_sha256"]
    assert first["source_name"] == "old.csv"
    assert second["source_name"] == "new.csv"
    assert second["source_sha256"] == "2" * 64
