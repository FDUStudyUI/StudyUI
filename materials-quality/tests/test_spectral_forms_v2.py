"""Exercise ordinary spectral controls and semantic cache boundaries in LFX."""

import asyncio
import json

import numpy as np
import pandas as pd
import pytest
from lfx.custom.eval import eval_custom_component_code
from lfx.graph import Graph
from lfx.schema import DataFrame

from components.materials_batch.batch_spectrum_analyzer import BatchSpectrumAnalyzer
from materials_quality.science.catalog import component_class
from materials_quality.science.table_contract import attach_contract, make_contract, read_contract
from materials_quality.science.ui_schema import form_config


def source():
    x = np.arange(450.0, 901.0)
    return DataFrame(
        {
            "curve_id": ["001"] * len(x),
            "group": ["a"] * len(x),
            "x": x,
            "y": 2 * np.exp(-0.5 * ((x - 730) / 5) ** 2),
        }
    )


def declared(table=None, **metadata):
    table = source() if table is None else table
    return attach_contract(
        table,
        make_contract(
            table,
            granularity="point",
            roles={"curve_id": "curve_id", "group": "group", "x": "x", "response": "y"},
            **metadata,
        ),
    )


def batch(**kwargs):
    return BatchSpectrumAnalyzer().set(input_table=source(), x_unit="nm", intensity_unit="counts", **kwargs)


def test_batch_chinese_threshold_controls_preserve_old_auto_toggle_and_physical_units():
    automatic = batch()._config()
    assert "prominence" not in automatic
    assert "prominence_mode" not in automatic
    manual = batch(auto_prominence=False, prominence=0.5)._config()
    assert manual["prominence"] == 0.5
    assert manual.get("prominence_mode", "absolute") == "absolute"
    explicit = batch(
        prominence_mode="显式阈值", prominence=0.5, peak_distance_x_enabled=True, peak_distance_x=12
    )._config()
    assert explicit["prominence_mode"] == "absolute" and explicit["prominence"] == 0.5
    assert explicit["peak_distance_x"] == 12
    noise = batch(
        prominence_mode="噪声参考", noise_window_low=450, noise_window_high=480, noise_multiplier=4
    )._config()
    assert noise["noise_window"] == [450, 480] and noise["noise_multiplier"] == 4
    assert noise["prominence_mode"] == "noise_reference" and "prominence" not in noise


def test_batch_forms_show_relevant_fields_and_use_candidate_language():
    node = batch(prominence_mode="噪声参考", lambda10_enabled=True)
    form = node.to_frontend_node()["data"]["node"]["template"]
    assert form["noise_window_low"]["show"] and form["noise_multiplier"]["show"]
    assert not form["prominence"]["show"]
    assert "窗口候选" in form["lambda10_enabled"]["display_name"]
    assert "物理" in form["lambda10_enabled"]["info"]
    assert "突出度最大候选" in form["lambda10_selection"]["options"]
    assert "config_json" not in form


def test_batch_native_serialization_keeps_chinese_controls_and_legacy_alias_results():
    from examples.demo_source import MaterialDemoTable

    emitter = MaterialDemoTable().set(records_json=source().to_json(orient="records"))
    node = BatchSpectrumAnalyzer().set(
        input_table=emitter.build_table,
        x_unit="nm",
        intensity_unit="counts",
        prominence_mode="显式阈值",
        prominence=0.5,
        lambda10_enabled=True,
        lambda10_min_nm=650,
        lambda10_max_nm=850,
        lambda10_selection="最红端候选",
    )
    payload = json.loads(json.dumps(Graph(start=emitter, end=node).dump()))
    template = next(
        n["data"]["node"]["template"]
        for n in payload["data"]["nodes"]
        if "prominence_mode" in n["data"]["node"]["template"]
    )
    assert template["prominence_mode"]["value"] == "显式阈值"
    restored = eval_custom_component_code(template["code"]["value"])().set(
        input_table=source(),
        x_unit="nm",
        intensity_unit="counts",
        prominence_mode="显式阈值",
        prominence=0.5,
        lambda10_enabled=True,
        lambda10_min_nm=650,
        lambda10_max_nm=850,
        lambda10_selection="最红端候选",
    )
    row = restored.build_report().data["data"]["curve_summary"][0]
    assert row["window_candidate_nm"] == row["lambda10_nm"] == 730
    assert row["selection_rule"] == "redmost"


def test_batch_explicit_independence_control_is_false_by_default():
    assert batch()._config()["bootstrap_independence_confirmed"] is False
    assert batch(bootstrap_independence_confirmed=True)._config()["bootstrap_independence_confirmed"] is True


def test_batch_outputs_have_actual_contract_grain_and_portable_report_envelopes():
    node = batch().set(input_table=declared())
    curves, features, groups = node.build_curves(), node.build_features(), node.build_groups()
    assert read_contract(curves)["granularity"] == "point"
    assert read_contract(features)["granularity"] == "peak"
    assert read_contract(groups)["granularity"] == "group_summary"
    assert read_contract(curves)["roles"]["response"] == "smoothed"
    assert read_contract(features)["roles"]["x"] == "peak_position"
    report = json.loads(json.dumps(node.build_report().data))
    assert report["table_contract"] == read_contract(curves)
    assert report["features_contract"] == read_contract(features)
    assert report["groups_contract"] == read_contract(groups)
    assert report["table_contract"]["experimental_design"]["kind"] == "descriptive"


def test_actual_batch_runtime_rechecks_metadata_changes_and_rejects_wrong_grain():
    node = batch().set(input_table=declared(units_state={"source": "first"}))
    first = asyncio.run(node.resolve_output("report")).data
    node.set(input_table=declared(units_state={"source": "second"}))
    second = asyncio.run(node.resolve_output("report")).data
    assert first["provenance"]["input_sha256"] != second["provenance"]["input_sha256"]
    assert first["provenance"]["input_contract_sha256"] != second["provenance"]["input_contract_sha256"]
    table = source()
    wrong = attach_contract(
        table, make_contract(table, granularity="group_summary", roles={"group": "group"})
    )
    node.set(input_table=wrong)
    with pytest.raises(ValueError, match="point|逐点|测量点"):
        asyncio.run(node.resolve_output("report"))


def test_batch_rejects_conflicting_declared_source_role_bindings():
    table = source()
    wrong = attach_contract(
        table, make_contract(table, granularity="point", roles={"x": "y", "response": "x"})
    )
    with pytest.raises(ValueError, match="role|角色|conflict"):
        batch().set(input_table=wrong).build_report()


def test_batch_independence_toggle_cannot_override_known_shared_experimental_units():
    first = source()
    second = source()
    second["curve_id"] = "002"
    table = DataFrame(pd.concat([first, second], ignore_index=True))
    table["sample"] = "one-unit"
    contract = make_contract(
        table,
        granularity="point",
        roles={"curve_id": "curve_id", "x": "x", "response": "y", "experimental_unit": "sample"},
        experimental_design={"kind": "independent", "confirmed": True},
    )
    table = attach_contract(table, contract)
    node = batch(bootstrap_samples=200, bootstrap_independence_confirmed=True).set(input_table=table)
    with pytest.raises(ValueError, match="independent|独立|汇总"):
        node.build_report()
    descriptive = batch().set(input_table=table).build_report().data
    assert descriptive["data"]["counts"]["completed"] == 2


def test_batch_legacy_no_contract_still_runs_without_invented_design():
    node = batch()
    assert read_contract(node.build_curves()) is None
    assert "table_contract" not in node.build_report().data
    assert node.build_groups().statistics_unit.str.contains("not inferred").all()


def clustered_source(*, design="independent", unit_column="sample"):
    records = []
    for identifier, sample in ((7, 101), ("007", 101), (9, "101")):
        frame = source()
        frame["curve_id"] = identifier
        frame[unit_column] = sample
        frame["pair"] = sample
        records.append(frame)
    frame = DataFrame(pd.concat(records, ignore_index=True))
    return attach_contract(
        frame,
        make_contract(
            frame,
            granularity="point",
            roles={
                "curve_id": "curve_id",
                "x": "x",
                "response": "y",
                "group": "group",
                "sample_id": unit_column,
                "experimental_unit": unit_column,
                "pair_id": "pair",
            },
            experimental_design={"kind": design, "confirmed": True, "aggregation_unit": "experimental_unit"},
            aggregation=[{"operation": "instrument_import"}],
        ),
    )


@pytest.mark.parametrize("design", ["independent", "paired"])
def test_batch_output_preserves_known_units_and_downstream_ci_cannot_pseudoreplicate(tmp_path, design):
    from materials_quality.science.visualization import spectra

    table = clustered_source(design=design)
    node = batch().set(input_table=table)
    for output in (node.build_curves(), node.build_features()):
        contract = read_contract(output)
        assert contract["experimental_design"] == read_contract(table)["experimental_design"]
        assert contract["aggregation"] == read_contract(table)["aggregation"]
        assert contract["roles"]["sample_id"] == contract["roles"]["experimental_unit"]
        units = output.drop_duplicates("curve_id")[contract["roles"]["experimental_unit"]].tolist()
        assert units == [101, 101, "101"]
        assert [type(value) for value in units] == [int, int, str]
        assert output.curve_id.drop_duplicates().tolist() == [7, "007", 9]
    assert read_contract(node.build_groups())["experimental_design"]["kind"] == "descriptive"
    with pytest.raises(ValueError, match="experimental unit|paired|independent|汇总"):
        spectra(
            node.build_curves(),
            config={
                "method": "band",
                "band": "ci95",
                "x": "x",
                "y": "smoothed",
                "curve_id": "curve_id",
                "independence_confirmed": True,
                "output_dir": str(tmp_path),
            },
        )


def test_entity_column_collision_does_not_overwrite_peak_values_or_units():
    node = batch().set(input_table=clustered_source(unit_column="height"))
    features = node.build_features()
    contract = read_contract(features)
    assert contract["roles"]["experimental_unit"] != "height"
    assert features.height.tolist() == [2, 2, 2]
    assert features.attrs["units"]["height"] == "counts"
    assert features[contract["roles"]["experimental_unit"]].tolist() == [101, 101, "101"]


def test_batch_rejects_multiple_declared_units_within_one_curve_even_without_bootstrap():
    frame = source()
    frame["unit"] = np.arange(len(frame))
    frame = attach_contract(
        frame,
        make_contract(
            frame,
            granularity="point",
            roles={"curve_id": "curve_id", "x": "x", "response": "y", "experimental_unit": "unit"},
            experimental_design={"kind": "independent", "confirmed": True},
        ),
    )
    with pytest.raises(ValueError, match="curve|曲线|角色"):
        batch().set(input_table=frame).build_report()


def test_batch_envelope_fingerprints_bind_actual_entity_enriched_output_tables():
    from materials_quality.context import table_fingerprint

    node = batch().set(input_table=clustered_source())
    report = node.build_report().data
    assert report["table_fingerprint"] == table_fingerprint(node.build_curves())
    assert report["features_fingerprint"] == table_fingerprint(node.build_features())


def test_native_batch_does_not_override_units_stored_only_in_contract():
    table = source()
    table = attach_contract(
        table,
        make_contract(
            table,
            granularity="point",
            roles={"curve_id": "curve_id", "x": "x", "response": "y"},
            units_state={"source": "instrument", "units": {"x": "nm", "y": "counts"}},
        ),
    )
    with pytest.raises(ValueError, match="unit|conflict"):
        batch().set(input_table=table, x_unit="um").build_report()


def test_native_batch_reuses_public_output_contracts_without_duplicate_entity_columns():
    from materials_quality.science.spectrum_batch import analyze_spectra

    node = batch().set(input_table=clustered_source())
    direct = analyze_spectra(node.input_table, node._config())
    assert list(node.build_curves().columns) == list(direct.table.columns)
    assert list(node.build_features().columns) == list(direct.features.columns)
    assert read_contract(node.build_curves()) == read_contract(direct.table)


@pytest.mark.parametrize("key", ["materials.spectra", "materials.xrd"])
def test_single_spectrum_form_modes_keep_legacy_optional_threshold_compatibility(key):
    cls = component_class(key)
    old = cls().set(ui_mode="form", cfg_prominence=0.5)
    assert form_config(old, key)["prominence"] == 0.5
    assert "prominence_mode" not in form_config(old, key)
    auto = cls().set(ui_mode="form")
    assert "prominence_mode" not in form_config(auto, key)
    explicit = cls().set(ui_mode="form", cfg_prominence_mode="显式阈值", cfg_prominence=0.5)
    assert form_config(explicit, key)["prominence_mode"] == "absolute"
    relative = cls().set(ui_mode="form", cfg_prominence_mode="旧版全谱相对阈值", cfg_prominence=0.5)
    assert "prominence" not in form_config(relative, key)
    noise = cls().set(
        ui_mode="form",
        cfg_prominence_mode="噪声参考",
        cfg_noise_window_min=450,
        cfg_noise_window_max=480,
        cfg_noise_multiplier=4,
        cfg_peak_distance_x=12,
    )
    config = form_config(noise, key)
    assert config["prominence_mode"] == "noise_reference" and "prominence" not in config
    assert config["noise_window"] == [450, 480] and config["noise_multiplier"] == 4
    assert config["peak_distance_x"] == 12
    form = noise.to_frontend_node()["data"]["node"]["template"]
    assert form["cfg_noise_window_min"]["show"]
    assert not form["cfg_prominence"]["show"]
    assert form["cfg_noise_window_min"]["type"] != "json"


def test_single_spectrum_new_controls_execute_real_numeric_analysis():
    node = component_class("materials.spectra")().set(
        input_table=source(),
        ui_mode="form",
        cfg_x_unit="nm",
        cfg_prominence_mode="显式阈值",
        cfg_prominence=0.5,
        cfg_peak_distance_x=12,
    )
    report = asyncio.run(node.resolve_output("report")).data
    assert report["data"]["peak_detection"]["prominence_mode"] == "absolute"
    assert report["data"]["peak_detection"]["peak_distance_x"] == 12
    assert report["data"]["peaks"][0]["position"] == 730
