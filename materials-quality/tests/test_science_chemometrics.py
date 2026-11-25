"""Independent synthetic references for spectral transforms and train-only models."""

import importlib

import numpy as np
import pandas as pd
import pytest
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from materials_quality.science.materials import spectra


def chem(frame, **config):
    module = importlib.import_module("materials_quality.science.chemometrics")
    return module.chemometrics(frame, config=config)


@pytest.mark.parametrize("order, expected", [(1, lambda x: 6 * x + 2), (2, lambda x: x * 0 + 6)])
def test_sg_derivatives_use_real_spacing_and_preserve_quantitative_signal(order, expected):
    x = np.linspace(10, 20, 51)
    y = 3 * x * x + 2 * x + 5
    result = spectra(
        pd.DataFrame({"x": x, "y": y}),
        config={
            "derivative_order": order,
            "smooth_window": 7,
            "smooth_order": 2,
            "x_unit": "nm",
            "y_unit": "counts",
        },
    )
    np.testing.assert_allclose(result.table.processed, expected(x), atol=1e-8)
    np.testing.assert_allclose(result.table.raw_y, y)
    np.testing.assert_allclose(result.table.smoothed, y)
    assert result.table.attrs["units"]["processed"] == f"counts/(nm)^{order}"
    assert result.data["area_signal"] == "baseline-corrected smoothed signal before normalization"


def test_asls_recovers_linear_baseline_beneath_narrow_positive_peaks():
    x = np.linspace(0, 100, 501)
    baseline = 2 + 0.01 * x
    y = baseline + 5 * np.exp(-0.5 * ((x - 35) / 1.5) ** 2)
    result = spectra(
        pd.DataFrame({"x": x, "y": y}),
        config={
            "baseline": {"method": "asls", "lambda": 1e6, "p": 0.001, "iterations": 30},
        },
    )
    np.testing.assert_allclose(result.table.baseline, baseline, atol=0.025)
    np.testing.assert_allclose(result.table.raw_y, y)
    np.testing.assert_allclose(result.table.corrected, y - result.table.baseline)


def test_snv_is_per_spectrum_and_requires_intensity_loss_consent():
    frame = pd.DataFrame({"x": np.arange(9.0), "y": np.arange(9.0) ** 2 + 3})
    with pytest.raises(ValueError, match="allow_intensity_loss"):
        spectra(frame, config={"normalization": "snv"})
    result = spectra(frame, config={"normalization": "snv", "allow_intensity_loss": True})
    expected = (frame.y - frame.y.mean()) / frame.y.std(ddof=1)
    np.testing.assert_allclose(result.table.processed, expected)
    assert result.table.attrs["units"]["processed"] == "dimensionless"
    assert result.data["normalization"]["ddof"] == 1
    assert result.warnings


@pytest.mark.parametrize(
    "config, x, y, match",
    [
        ({"normalization": "snv", "allow_intensity_loss": True}, np.arange(9.0), np.ones(9), "variance"),
        (
            {"derivative_order": 1, "smooth_window": 5, "x_unit": "nm", "y_unit": "counts"},
            np.arange(9.0) ** 2,
            np.arange(9.0),
            "evenly",
        ),
        ({"derivative_order": 1, "smooth_window": 5}, np.arange(9.0), np.arange(9.0), "unit"),
        ({"derivative_order": 1}, np.arange(9.0), np.arange(9.0), "window"),
        ({"baseline": {"method": "asls", "p": 1}}, np.arange(9.0), np.arange(9.0), "p"),
        ({"baseline": "asls"}, np.arange(9.0) ** 2, np.arange(9.0), "evenly"),
    ],
)
def test_spectral_preconditions(config, x, y, match):
    with pytest.raises(ValueError, match=match):
        spectra(pd.DataFrame({"x": x, "y": y}), config=config)


def model_data():
    rng = np.random.default_rng(9)
    x = rng.normal(size=(24, 4))
    frame = pd.DataFrame(x, columns=["a", "b", "c", "d"])
    frame["target"] = x @ np.array([2.0, -1, 0.5, 0]) + 0.01 * rng.normal(size=24)
    frame["sample"] = [f"s{i}" for i in range(24)]
    frame["split"] = ["train"] * 18 + ["test"] * 6
    return frame


def model_config(**extra):
    return dict(
        method="pls",
        feature_columns=["a", "b", "c", "d"],
        target_column="target",
        sample_column="sample",
        split_column="split",
        n_components=3,
        **extra,
    )


def test_pls_matches_independent_train_only_pipeline_and_identifies_rows():
    frame = model_data()
    result = chem(frame, **model_config())
    reference = make_pipeline(StandardScaler(), PLSRegression(n_components=3, scale=False))
    reference.fit(frame.loc[:17, ["a", "b", "c", "d"]], frame.loc[:17, "target"])
    expected = reference.predict(frame[["a", "b", "c", "d"]]).ravel()
    np.testing.assert_allclose(result.table.prediction, expected, atol=1e-12)
    assert result.data["train_sample_ids"] == frame.loc[:17, "sample"].tolist()
    assert result.data["test_sample_ids"] == frame.loc[18:, "sample"].tolist()
    assert result.data["metrics"]["test"]["n_samples"] == 6
    assert list(result.features.columns) == [
        "sample_id",
        "split",
        "component_1",
        "component_2",
        "component_3",
    ]


@pytest.mark.parametrize("method", ["pca", "pls"])
def test_test_perturbation_cannot_change_train_fit_or_cv_selection(method):
    frame = model_data()
    config = model_config(cv_folds=3 if method == "pls" else 0)
    config["method"] = method
    original = chem(frame, **config)
    changed = frame.copy()
    changed.loc[18:, ["a", "b", "c", "d", "target"]] *= 1000
    perturbed = chem(changed, **config)
    assert original.data["model"] == perturbed.data["model"]
    assert original.data["cv"] == perturbed.data["cv"]
    pd.testing.assert_frame_equal(original.features.iloc[:18], perturbed.features.iloc[:18])


def test_repeated_sample_and_group_identities_must_not_cross_split():
    frame = model_data()
    frame.loc[18, "sample"] = frame.loc[0, "sample"]
    with pytest.raises(ValueError, match="sample.*split"):
        chem(frame, **model_config())
    frame = model_data()
    frame["group"] = [f"g{i // 2}" for i in range(24)]
    frame.loc[18, "group"] = frame.loc[0, "group"]
    with pytest.raises(ValueError, match="group.*split"):
        chem(frame, **model_config(group_column="group"))


def test_cv_records_group_safe_folds_and_no_test_ids():
    frame = model_data()
    frame["group"] = [f"g{i // 2}" for i in range(24)]
    result = chem(frame, **model_config(group_column="group", cv_folds=3))
    for fold in result.data["cv"]["folds"]:
        assert not set(fold["train_group_ids"]) & set(fold["validation_group_ids"])
        assert not set(fold["train_sample_ids"] + fold["validation_sample_ids"]) & set(
            frame.loc[18:, "sample"]
        )
    x = frame.loc[:17, ["a", "b", "c", "d"]].to_numpy()
    y = frame.loc[:17, "target"].to_numpy()
    for candidate in result.data["cv"]["candidates"]:
        predictions = np.empty(18)
        for fit, validation in GroupKFold(3).split(x, y, frame.loc[:17, "group"]):
            reference = make_pipeline(
                StandardScaler(), PLSRegression(n_components=candidate["n_components"], scale=False)
            )
            reference.fit(x[fit], y[fit])
            predictions[validation] = reference.predict(x[validation]).ravel()
        assert candidate["rmse"] == pytest.approx(np.sqrt(np.mean((predictions - y) ** 2)), abs=1e-12)


def test_training_only_has_no_test_metrics_or_generalization_claim():
    frame = model_data()
    frame["split"] = "train"
    result = chem(frame, **model_config())
    assert result.data["metrics"]["test"] is None
    assert result.data["generalization_assessed"] is False
    assert any("independent test" in warning for warning in result.warnings)


def test_pls_preserves_target_units_for_evidence_and_serializable_fit():
    import json

    frame = model_data()
    frame.attrs["units"] = {"target": "mass_percent"}
    result = chem(frame, **model_config())
    assert result.table.attrs["units"]["prediction"] == "mass_percent"
    assert result.table.attrs["units"]["residual"] == "mass_percent"
    json.dumps(result.data, allow_nan=False)


@pytest.mark.parametrize(
    "change, match",
    [
        ({"split_column": None}, "split_column"),
        ({"n_components": 100}, "components"),
        ({"feature_columns": ["a", "target"]}, "target"),
        ({"feature_columns": ["a", "split"]}, "split"),
    ],
)
def test_model_preconditions(change, match):
    config = model_config()
    config.update(change)
    with pytest.raises(ValueError, match=match):
        chem(model_data(), **config)


def test_zero_variance_and_nonfinite_features_fail():
    frame = model_data()
    frame.loc[:17, "a"] = 1
    with pytest.raises(ValueError, match="variance"):
        chem(frame, **model_config())
    frame.loc[0, "a"] = np.inf
    with pytest.raises(ValueError, match="finite"):
        chem(frame, **model_config())


def test_visual_forms_expose_new_scientific_controls_without_json():
    spectra_module = importlib.import_module("materials_quality.science.ui_specs_materials")
    controls = {field["path"]: field for field in spectra_module.SPECS["materials.spectra"]}
    assert "asls" in controls["baseline.method"]["choices"]
    for name in [
        "baseline.lambda",
        "baseline.p",
        "baseline.iterations",
        "derivative_order",
        "allow_intensity_loss",
        "y_unit",
    ]:
        assert controls[name]["kind"] != "json"
    assert "snv" in controls["normalization"]["choices"]
    module = importlib.import_module("materials_quality.science.ui_specs_chemometrics")
    fields = {field["path"]: field for field in module.SPECS["materials.chemometrics"]}
    for name in [
        "method",
        "feature_columns",
        "sample_column",
        "split_column",
        "group_column",
        "n_components",
        "cv_folds",
    ]:
        assert fields[name]["kind"] != "json"
