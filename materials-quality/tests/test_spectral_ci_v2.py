"""Spectral t intervals require declared units and honest small-sample policy."""

import asyncio

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from scipy.stats import t

from materials_quality.science.catalog import component_class
from materials_quality.science.table_contract import attach_contract, make_contract
from materials_quality.science.ui_schema import form_config
from materials_quality.science.visualization import spectra


def curves(n=3):
    return pd.DataFrame(
        {
            "curve_id": np.repeat([f"c{i}" for i in range(n)], 3),
            "group": ["G"] * (3 * n),
            "x": np.tile([1.0, 2.0, 3.0], n),
            "y": np.concatenate([np.array([0.0, 2.0, 4.0]) + 2 * i for i in range(n)]),
        }
    )


def options(tmp_path, **extra):
    return {
        "method": "band",
        "x": "x",
        "y": "y",
        "curve_id": "curve_id",
        "group": "group",
        "band": "ci95",
        "output_dir": str(tmp_path),
        **extra,
    }


def test_generic_spectral_ci_requires_explicit_independence_without_contract(tmp_path):
    with pytest.raises(ValueError, match="independence_confirmed|独立"):
        spectra(curves(), config=options(tmp_path))


@pytest.mark.parametrize("n", [1, 2])
def test_default_small_sample_ci_stops_and_does_not_leak_figures(tmp_path, n):
    before = set(plt.get_fignums())
    with pytest.raises(ValueError, match="three|3|小样本|two"):
        spectra(curves(n), config=options(tmp_path, independence_confirmed=True))
    assert set(plt.get_fignums()) == before
    assert not list(tmp_path.iterdir())


def test_model_based_two_curve_ci_matches_t_reference_with_declared_assumptions(tmp_path):
    result = spectra(
        curves(2), config=options(tmp_path, independence_confirmed=True, small_sample_policy="model_based")
    )
    band = result.data["plot_data"]["bands"][0]
    expected_margin = t.ppf(0.975, 1)
    assert band["lower"] == pytest.approx(np.array([1, 3, 5]) - expected_margin)
    assert band["upper"] == pytest.approx(np.array([1, 3, 5]) + expected_margin)
    assert band["n_independent_units"] == 2 and band["degrees_of_freedom"] == 1
    assert band["small_sample_policy"] == "model_based"
    assert "normal" in " ".join(result.data["assumptions"]).lower()


def test_declared_three_curve_ci_records_design_method_and_pointwise_limits(tmp_path):
    result = spectra(curves(), config=options(tmp_path, independence_confirmed=True))
    band = result.data["plot_data"]["bands"][0]
    margin = t.ppf(0.975, 2) * 2 / np.sqrt(3)
    assert band["lower"] == pytest.approx(np.array([2, 4, 6]) - margin)
    assert band["n_independent_units"] == 3 and band["degrees_of_freedom"] == 2
    assert band["ci_status"] == "estimated"
    assert band["small_sample_policy"] == "descriptive"
    assert "not a simultaneous" in result.data["statistical_definition"]


def test_model_based_policy_cannot_make_single_unit_ci_estimable(tmp_path):
    with pytest.raises(ValueError, match="two|2|不可|不足"):
        spectra(
            curves(1),
            config=options(tmp_path, independence_confirmed=True, small_sample_policy="model_based"),
        )


@pytest.mark.parametrize("design", ["independent", "paired"])
def test_explicit_flag_cannot_override_known_unit_clustering_or_paired_design(tmp_path, design):
    table = curves()
    table["sample"] = ["s1"] * 6 + ["s2"] * 3
    table = attach_contract(
        table,
        make_contract(
            table,
            granularity="point",
            roles={"curve_id": "curve_id", "experimental_unit": "sample", "x": "x", "response": "y"},
            experimental_design={"kind": design, "confirmed": True},
        ),
    )
    with pytest.raises(ValueError, match="unit|独立|paired|汇总"):
        spectra(table, config=options(tmp_path, independence_confirmed=True))


@pytest.mark.parametrize("unit_column", ["sample", "curve_id"])
def test_already_aggregated_one_curve_per_unit_accepts_declared_ci(tmp_path, unit_column):
    table = curves()
    table["sample"] = table.curve_id
    table = attach_contract(
        table,
        make_contract(
            table,
            granularity="point",
            roles={"curve_id": "curve_id", "experimental_unit": unit_column, "x": "x", "response": "y"},
            experimental_design={"kind": "independent", "confirmed": True},
            aggregation=[{"operation": "sample_mean"}],
        ),
    )
    result = spectra(table, config=options(tmp_path, independence_confirmed=True))
    assert result.data["plot_data"]["bands"][0]["n_independent_units"] == 3


@pytest.mark.parametrize("band", ["iqr", "sd"])
def test_descriptive_spectral_bands_do_not_claim_curve_independence(tmp_path, band):
    result = spectra(curves(2), config=options(tmp_path, band=band))
    assert not any("Each curve is one independent" in a for a in result.data["assumptions"])
    assert "n_independent_units" not in result.data["plot_data"]["bands"][0]


@pytest.mark.parametrize(
    "extra",
    [
        {"independence_confirmed": "true"},
        {"independence_confirmed": True, "small_sample_policy": "unknown"},
        {"independence_confirmed": True, "small_sample_policy": []},
    ],
)
def test_ci_declaration_and_policy_types_are_validated(tmp_path, extra):
    with pytest.raises(ValueError, match="independence_confirmed|small_sample_policy"):
        spectra(curves(), config=options(tmp_path, **extra))


def test_native_spectral_ci_controls_are_conditional_and_execute_without_json(tmp_path):
    cls = component_class("viz.spectra")
    node = cls().set(
        input_table=curves(2),
        ui_mode="form",
        cfg_method="band",
        cfg_y="y",
        cfg_band="ci95",
        cfg_independence_confirmed=True,
        cfg_small_sample_policy="明确模型假设推断",
        cfg_output_dir=str(tmp_path),
    )
    config = form_config(node, "viz.spectra")
    assert config["independence_confirmed"] is True
    assert config["small_sample_policy"] == "model_based"
    form = node.to_frontend_node()["data"]["node"]["template"]
    assert form["cfg_independence_confirmed"]["show"]
    node.set(cfg_band="iqr")
    assert not node.to_frontend_node()["data"]["node"]["template"]["cfg_independence_confirmed"]["show"]
    node.set(cfg_band="ci95")
    result = asyncio.run(node.resolve_output("report")).data
    assert result["data"]["plot_data"]["bands"][0]["n_independent_units"] == 2


@pytest.mark.parametrize("partial", [False, True])
def test_identical_unit_responses_do_not_produce_estimated_zero_width_ci(tmp_path, partial):
    table = curves(6)
    table["y"] = np.tile([1.0, 2.0, 3.0], 6)
    if partial:
        table.loc[table.x == 2, "y"] += np.arange(6)
    result = spectra(table, config=options(tmp_path, independence_confirmed=True))
    band = result.data["plot_data"]["bands"][0]
    assert band["ci_status"] == ("partially_estimable" if partial else "zero_between_unit_variance")
    assert band["lower"][0] is None and band["upper"][2] is None
    assert band["ci_reason"]
    assert any("variance" in warning for warning in result.warnings)
    if partial:
        assert band["lower"][1] < band["upper"][1]
