"""Method selection must never confuse a keyword hit with scientific eligibility."""

import importlib.util
from types import SimpleNamespace

import pandas as pd
import pytest


def api():
    assert importlib.util.find_spec("materials_quality.science.method_cards") is not None, (
        "Evidence-backed method recommendation is not implemented"
    )
    from materials_quality.science import method_cards

    return method_cards


def select(method_id, **config):
    result = api().recommend_methods(config={"method_ids": [method_id], **config})
    return result.data["candidates"][0]


def curve_conditions(**extra):
    return {"signal_type": "nir_absorbance", "x_unit": "nm", "y_unit": "absorbance", **extra}


def test_sources_have_traceable_scope_and_no_experimental_recipe_claims():
    cards = api().load_cards()
    assert len(cards) >= 10
    assert len({c["id"] for c in cards}) == len(cards)
    for card in cards:
        assert card["source"]["url"].startswith("https://")
        assert all(card["source"][key] for key in ("title", "version", "locator", "quote", "verified_on"))
        assert card["source"]["kind"] in {"algorithm_documentation", "original_research"}
        assert card["parameter_origin"] == "StudyUI adaptation; not an experimental recipe"
        assert card["limitations"]


def test_same_material_different_signal_blocks_snv():
    row = select(
        "snv",
        material="milk",
        **curve_conditions(signal_type="darkfield_intensity"),
        allow_intensity_loss=True,
        nonzero_variance=True,
    )
    assert row["status"] == "blocked"
    assert "signal_type" in row["blocked"]
    assert row["execution"] is None


def test_unknown_conditions_stay_missing_and_do_not_supply_executable_plan():
    row = select("snv")
    assert row["status"] == "missing"
    assert {"signal_type", "x_unit", "allow_intensity_loss"} <= set(row["missing"])
    assert row["execution"] is None


def test_absolute_intensity_goal_blocks_snv_even_with_other_conditions():
    row = select(
        "snv",
        **curve_conditions(),
        goal="absolute_intensity",
        allow_intensity_loss=False,
        nonzero_variance=True,
    )
    assert row["status"] == "blocked"


def test_verified_conditions_produce_mapping_but_not_scientific_validation():
    row = select("snv", **curve_conditions(), allow_intensity_loss=True, nonzero_variance=True)
    assert row["status"] == "eligible"
    assert row["execution"]["operation"] == "materials.spectra"
    assert row["execution"]["config"]["normalization"] == "snv"
    assert row["scientifically_validated"] is False


def test_sequence_blocks_snv_to_nonnegative_factorization():
    result = api().recommend_methods(
        config={
            "sequence": ["snv", "nmf"],
            **curve_conditions(),
            "allow_intensity_loss": True,
            "nonzero_variance": True,
            "nonnegative": True,
        }
    )
    assert result.data["sequence_check"]["status"] == "blocked"
    assert "snv->nmf" in result.data["sequence_check"]["blocked"]


def test_learning_transform_rejects_leakage_and_unknown_split():
    assert select("pca", **curve_conditions())["status"] == "missing"
    row = select(
        "pca", **curve_conditions(), fit_scope="all_data", split_confirmed=True, groups_disjoint=True
    )
    assert "fit_scope" in row["blocked"]


def test_input_coordinates_override_incorrect_declared_spacing():
    table = pd.DataFrame({"x": [1.0, 2.0, 4.0, 5.0, 7.0], "y": [2.0, 3.0, 5.0, 3.0, 2.0]})
    result = api().recommend_methods(
        table,
        config={
            "method_ids": ["sg_smooth"],
            **curve_conditions(),
            "equally_spaced": True,
            "smooth_window": 5,
            "smooth_order": 2,
        },
    )
    assert "equally_spaced" in result.data["candidates"][0]["blocked"]


def test_unrelated_query_has_no_arbitrary_topk_candidates():
    result = api().recommend_methods(config={"query": "volcanic dinosaur taxonomy"})
    assert result.table.empty
    assert result.data["candidates"] == []


def test_retrieval_is_repeatable_and_defensive_copies_sources():
    first = api().recommend_methods(config={"query": "SNV", "top_k": 3})
    second = api().recommend_methods(config={"query": "SNV", "top_k": 3})
    pd.testing.assert_frame_equal(first.table, second.table)
    assert first.table.iloc[0]["method_id"] == "snv"
    first.data["candidates"][0]["source"]["title"] = "corrupt"
    assert api().load_cards()[3]["source"]["title"] != "corrupt"


def test_sg_mapping_binds_selected_window_and_columns():
    row = select(
        "sg_smooth",
        **curve_conditions(),
        equally_spaced=True,
        smooth_window=9,
        smooth_order=3,
        x="wavelength",
        y="abs",
    )
    assert row["execution"]["config"]["smooth_window"] == 9
    assert row["execution"]["config"]["x"] == "wavelength"


def test_pls_repeated_sample_across_split_blocks_even_if_declared_safe():
    table = pd.DataFrame(
        {
            "sample": ["a", "b", "a", "c"],
            "split": ["train", "train", "test", "test"],
            "f1": [1.0, 2.0, 3.0, 4.0],
            "target": [3.0, 4.0, 5.0, 6.0],
        }
    )
    result = api().recommend_methods(
        table,
        config={
            "method_ids": ["pls"],
            **curve_conditions(),
            "sample_column": "sample",
            "split_column": "split",
            "target_column": "target",
            "feature_columns": ["f1"],
            "n_components": 1,
            "fit_scope": "train_only",
            "split_confirmed": True,
            "groups_disjoint": True,
        },
    )
    assert "groups_disjoint" in result.data["candidates"][0]["blocked"]


def test_ui_defaults_preserve_unknown_conditions_and_avoid_json():
    assert importlib.util.find_spec("materials_quality.science.ui_specs_methods") is not None
    from materials_quality.science.ui_specs_methods import SPECS

    fields = SPECS["lit.method_recommend"]
    assert not any(f["kind"] == "json" for f in fields)
    defaults = {f["path"]: f["default"] for f in fields if f["default"] is not None}
    defaults["method_ids"] = ["snv"]
    assert api().recommend_methods(config=defaults).data["candidates"][0]["status"] == "missing"


def test_integral_form_rows_bind_physical_intervals():
    from materials_quality.science.ui_schema import form_config

    node = SimpleNamespace(
        ui_mode="form", cfg_goal="area", cfg_area_ranges=[{"lower": 500.0, "upper": 600.0}]
    )
    config = form_config(node, "lit.method_recommend")
    assert config["area_ranges"] == [[500.0, 600.0]]


def test_native_form_goal_ignores_irrelevant_model_and_curve_controls():
    from materials_quality.science.ui_schema import form_config

    node = SimpleNamespace(
        ui_mode="form",
        cfg_goal="normalization",
        cfg_feature_columns=["leaked"],
        cfg_area_ranges=[{"lower": 500.0, "upper": 600.0}],
        cfg_allow_intensity_loss="yes",
    )
    config = form_config(node, "lit.method_recommend")
    assert "feature_columns" not in config
    assert "area_ranges" not in config
    assert config["allow_intensity_loss"] == "yes"


def test_unspecified_derivative_unit_is_missing():
    row = select(
        "sg_derivative1",
        **curve_conditions(y_unit="unspecified"),
        equally_spaced=True,
        smooth_window=5,
        smooth_order=2,
    )
    assert "y_unit" in row["missing"]
    assert row["execution"] is None


def test_table_missing_curve_columns_cannot_be_declared_eligible():
    result = api().recommend_methods(
        pd.DataFrame({"other": [1, 2, 3]}),
        config={
            "method_ids": ["snv"],
            **curve_conditions(),
            "allow_intensity_loss": True,
            "nonzero_variance": True,
        },
    )
    assert "curve_columns" in result.data["candidates"][0]["blocked"]


@pytest.mark.parametrize("prominence", [0, -1, float("nan"), True])
def test_invalid_prominence_is_blocked(prominence):
    row = select("peak_detection", **curve_conditions(), positive_peaks=True, prominence=prominence)
    assert "prominence" in row["blocked"]


def test_integral_outside_measured_window_is_blocked():
    result = api().recommend_methods(
        pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [2.0, 4.0, 2.0]}),
        config={"method_ids": ["trapezoid"], **curve_conditions(), "area_ranges": [[0.0, 4.0]]},
    )
    assert "area_ranges" in result.data["candidates"][0]["blocked"]


@pytest.mark.parametrize(
    "features,components,want",
    [
        (["f1", "sample"], 1, "identity_in_features"),
        (["f1"], 3, "n_components"),
        (["flat"], 1, "zero_variance_features"),
        (["invalid"], 1, "nonfinite_features"),
    ],
)
def test_known_model_data_failures_cannot_be_eligible(features, components, want):
    table = pd.DataFrame(
        {
            "sample": [1, 2, 3, 4],
            "split": ["train", "train", "test", "test"],
            "f1": [1.0, 2.0, 3.0, 4.0],
            "flat": [1.0, 1.0, 1.0, 1.0],
            "invalid": [1.0, float("nan"), 3.0, 4.0],
        }
    )
    result = api().recommend_methods(
        table,
        config={
            "method_ids": ["pca"],
            **curve_conditions(),
            "sample_column": "sample",
            "split_column": "split",
            "feature_columns": features,
            "n_components": components,
            "fit_scope": "train_only",
        },
    )
    row = result.data["candidates"][0]
    assert want in row["blocked"]
    assert row["execution"] is None


@pytest.mark.parametrize(
    "config",
    [
        {"top_k": True},
        {"top_k": 0},
        {"method_ids": ["imaginary"]},
        {"allow_intensity_loss": "false"},
        {"sequence": ["imaginary"]},
    ],
)
def test_malformed_controls_do_not_silently_pass(config):
    with pytest.raises(ValueError):
        api().recommend_methods(config=config)
