"""Native forms describe the real materials and plotting operations."""

import importlib
import json

import pytest

from materials_quality.science.catalog import entries


def schemas():
    modules = [
        importlib.import_module("materials_quality.science.ui_specs_materials"),
        importlib.import_module("materials_quality.science.ui_specs_visualization"),
    ]
    return (
        {key: value for module in modules for key, value in module.SPECS.items()},
        {key: value for module in modules for key, value in module.CONTRACTS.items()},
    )


def fields(key):
    return {item["path"]: item for item in schemas()[0][key]}


def test_every_domain_operation_has_serializable_native_fields_and_real_contract():
    specs, contracts = schemas()
    expected = {
        item["key"] for item in entries() if item["key"].startswith(("materials.", "viz.", "export."))
    }
    assert len(expected) == 12
    assert set(specs) == set(contracts) == expected
    json.dumps([specs, contracts], allow_nan=False)
    for key, controls in specs.items():
        assert controls, key
        assert len({item["path"] for item in controls}) == len(controls), key
        for item in controls:
            assert item["label"] and item["info"], (key, item)
            assert item["kind"] != "json" or item["advanced"], (key, item)
        contract = contracts[key]
        assert type(contract["table_output"]) is bool
        assert type(contract["artifacts_output"]) is bool
        assert isinstance(contract["upload_types"], list)
        assert contract["icon"]


def test_mechanics_form_has_explicit_columns_units_elastic_bounds_and_evidence_flag():
    form = fields("materials.mechanics")
    assert form["x"]["default"] == "strain"
    assert form["y"]["default"] == "stress"
    assert form["strain_unit"]["choices"] == ["fraction", "%"]
    assert form["stress_unit"]["default"] == "MPa"
    assert form["fit_range"]["kind"] == "range"
    assert form["fit_range"]["required"]
    assert form["fit_range"]["default"] is None
    assert form["yield_offset"]["default"] == 0.002
    assert "fraction" in form["yield_offset"]["info"]
    assert form["fracture_confirmed"]["default"] is False


def test_thermal_and_morphology_forms_expose_method_specific_controls():
    thermal = fields("materials.thermal")
    assert thermal["endotherm"]["when"] == {"kind": ["dsc"]}
    assert thermal["heating_rate"]["when"] == {"kind": ["dsc"], "x_unit": ["degC", "K"]}
    assert thermal["initial_mass"]["when"] == {"kind": ["tg"]}
    assert thermal["y_unit"]["default"] == "%"
    image = fields("materials.sem_eds")
    assert set(image["method"]["choices"]) == {"image", "eds"}
    assert image["element_column"]["when"] == {"method": ["eds"]}
    assert image["threshold"]["when"] == {"method": ["image"], "segmentation": ["threshold"]}
    assert image["ml_features"]["when"] == {"method": ["image"], "segmentation": ["ml"]}
    assert image["pixel_size"]["default"] is None
    assert image["spatial_unit"]["default"] is None


@pytest.mark.parametrize("key", ["materials.xrd", "materials.spectra", "materials.thermal"])
def test_curve_forms_have_native_baseline_smoothing_and_peak_controls(key):
    form = fields(key)
    for path in (
        "x",
        "y",
        "sort",
        "baseline.method",
        "baseline.value",
        "smooth_window",
        "smooth_order",
        "prominence",
        "peak_distance",
    ):
        assert path in form
        assert form[path]["kind"] != "json"
    assert form["baseline.value"]["when"] == {"baseline.method": ["constant"]}
    assert form["smooth_window"]["default"] == 0
    assert form["prominence"]["default"] is None


def test_materials_and_figures_ports_match_actual_node_results():
    _, contracts = schemas()
    for key, contract in contracts.items():
        assert contract["table_output"] == (key.startswith("materials.") or key == "export.table")
        assert contract["artifacts_output"] == (
            key in {"materials.sem_eds", "materials.microstructure", "export.table", "export.report"}
            or key.startswith("viz.")
        )
    assert contracts["materials.sem_eds"]["upload_types"]
    assert contracts["materials.microstructure"]["upload_types"]
    for key, contract in contracts.items():
        if key not in {"materials.sem_eds", "materials.microstructure"}:
            assert contract["upload_types"] == []


def test_plotting_forms_expose_all_methods_and_native_units():
    expected = {
        "viz.performance": {"scatter", "bar", "box", "violin"},
        "viz.spectra": {"line", "overlay", "difference", "band"},
        "viz.mechanics": {"overlay", "mean_error"},
        "viz.statistics": {"histogram", "correlation", "residual", "prediction"},
    }
    for key, choices in expected.items():
        form = fields(key)
        assert set(form["method"]["choices"]) == choices
        assert form["units"]["kind"] == "dict"
        assert form["labels"]["kind"] == "dict"
        assert form["formats"]["kind"] == "list"
        assert form["output_dir"]["kind"] == "str"
    assert fields("viz.performance")["x"]["when"] == {"method": ["scatter"]}
    assert fields("viz.spectra")["offset"]["when"] == {"method": ["overlay"]}
    assert fields("viz.mechanics")["error"]["when"] == {"method": ["mean_error"]}
    assert fields("viz.statistics")["y_true"]["when"] == {"method": ["residual", "prediction"]}


def test_exports_require_no_json_and_defer_format_dependent_filename():
    for key in ("export.table", "export.report"):
        form = fields(key)
        assert form["filename"]["default"] is None
        assert form["output_dir"]["kind"] == "str"
        assert form["format"]["kind"] == "choice"
        assert not any(item["kind"] == "json" and not item["advanced"] for item in form.values())
    assert fields("export.table")["id_columns"]["kind"] == "list"
    assert fields("export.table")["units"]["kind"] == "dict"
