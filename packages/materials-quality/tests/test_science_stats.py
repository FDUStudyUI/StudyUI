"""Synthetic numerical truth and design/leakage failures for statistics nodes."""

import importlib
import json

import numpy as np
import pandas as pd
import pytest


def api():
    return importlib.import_module("materials_quality.science.statistics")


def groups():
    return pd.DataFrame(
        {
            "sample": list(range(15)),
            "group": np.repeat(["a", "b", "c"], 5),
            "value": [1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
        }
    )


def test_grouped_preserves_all_descriptors_and_input():
    t = groups()
    r = api().grouped(t, config={"group": "group", "columns": ["value"]})
    row = r.table.query("group == 'a'").iloc[0]
    assert row["count"] == 5 and row["mean"] == 3 and row["std"] == pytest.approx(5**0.5 / 2**0.5)
    assert [row[k] for k in ["median", "q25", "q75", "min", "max"]] == [3, 2, 4, 1, 5]
    assert len(t) == 15


def test_distribution_exports_numeric_histogram_and_qq(tmp_path):
    r = api().distribution(groups(), config={"column": "value", "bins": 4, "output_dir": str(tmp_path)})
    assert sum(r.data["histogram"]["count"]) == 15
    assert len(r.data["qq"]["ordered"]) == 15
    assert 0 <= r.data["shapiro"]["pvalue"] <= 1
    for p in r.artifacts:
        assert __import__("PIL.Image", fromlist=["open"]).open(p).size[0] > 300
    with pytest.raises(ValueError):
        api().distribution(pd.DataFrame({"x": [1, 1, 1]}), config={"column": "x"})


@pytest.mark.parametrize("method", ["pearson", "spearman", "kendall"])
def test_correlations_recover_perfect_relationship(method):
    r = api().correlation(
        pd.DataFrame({"x": range(8), "y": np.arange(8) * 3}), config={"columns": ["x", "y"], "method": method}
    )
    assert r.table.iloc[0]["coefficient"] == pytest.approx(1)
    assert r.table.iloc[0]["pvalue"] < 0.001


@pytest.mark.parametrize("method", ["independent_t", "welch", "mannwhitney", "anova", "kruskal"])
def test_significance_separates_groups_with_effect_and_assumptions(method):
    t = groups()
    if method not in ["anova", "kruskal"]:
        t = t[t.group != "b"]
    r = api().significance(
        t, config={"group": "group", "column": "value", "method": method, "subject": "sample"}
    )
    assert r.data["pvalue"] < 0.05
    assert r.data["effect"]["value"] > 0
    assert r.data["assumptions"]
    json.dumps(r.data, allow_nan=False)


def test_paired_requires_ids_aligns_pairs_and_rejects_replicates():
    t = pd.DataFrame({"id": [3, 1, 2, 2, 3, 1], "g": ["a"] * 3 + ["b"] * 3, "v": [30, 10, 20, 25, 34, 16]})
    c = {"group": "g", "column": "v", "method": "paired_t"}
    with pytest.raises(ValueError, match="pair"):
        api().significance(t, config=c)
    r = api().significance(t, config={**c, "pair_id": "id"})
    assert r.data["n_pairs"] == 3
    assert r.data["mean_difference"] == pytest.approx(-5)
    assert r.data["confidence_interval"][0] < -5 < r.data["confidence_interval"][1]
    with pytest.raises(ValueError, match="duplicate|replic"):
        api().significance(pd.concat([t, t.iloc[[0]]]), config={**c, "pair_id": "id"})
    with pytest.raises(ValueError, match="complete|missing"):
        api().significance(t.iloc[:-1], config={**c, "pair_id": "id"})


@pytest.mark.parametrize("method", ["tukey", "dunn"])
def test_pairwise_multiple_comparisons_have_adjusted_probabilities(method):
    r = api().multiple(groups(), config={"group": "group", "column": "value", "method": method})
    assert len(r.table) == 3
    assert r.table.p_adjusted.between(0, 1).all()
    assert r.table.query("group1 == 'a' and group2 == 'c'").iloc[0].p_adjusted < 0.01


@pytest.mark.parametrize("method, expected", [("holm", [0.03, 0.06, 0.06]), ("fdr", [0.03, 0.04, 0.04])])
def test_corrections_preserve_original_hypothesis_order(method, expected):
    r = api().multiple(pd.DataFrame({"p": [0.01, 0.04, 0.03]}), config={"column": "p", "method": method})
    assert r.table.p_adjusted.tolist() == pytest.approx(expected)


@pytest.mark.parametrize(
    "method", ["linear", "polynomial", "ridge", "lasso", "random_forest", "gradient_boosting", "svr"]
)
def test_models_holdout_and_safe_serialized_prediction(tmp_path, method):
    x = np.linspace(-3, 3, 60)
    t = pd.DataFrame({"id": [f"s{i}" for i in range(60)], "x": x, "y": 2 * x + 3})
    fn = api().regression if method in ["linear", "polynomial", "ridge", "lasso"] else api().predict
    c = {
        "features": ["x"],
        "target": "y",
        "method": method,
        "id_column": "id",
        "seed": 14,
        "alpha": 0.0001,
        "output_dir": str(tmp_path),
    }
    r = fn(t, config=c)
    assert r.data["evaluation"] == "holdout"
    assert set(r.data["train_ids"]).isdisjoint(r.data["test_ids"])
    assert len(r.table) == 12 and r.table.split.eq("test").all()
    assert r.data["metrics"]["r2"] > 0.85
    json.dumps(r.data, allow_nan=False)
    prediction = api().predict(t, config={"model_path": r.data["model_path"]}, data=r.data)
    assert len(prediction.table) == 60
    measured = prediction.table.set_index("row_position").loc[r.table.row_position, "y_pred"].to_numpy()
    np.testing.assert_allclose(measured, r.table.y_pred)


def test_cv_predictions_are_out_of_fold_and_scaling_fitted_on_train(tmp_path):
    t = pd.DataFrame({"x": np.arange(20, dtype=float), "y": np.arange(20) * 2.0})
    c = {
        "features": ["x"],
        "target": "y",
        "model_method": "linear",
        "method": "cv",
        "folds": 4,
        "output_dir": str(tmp_path),
        "seed": 9,
    }
    r = api().evaluate(t, config=c)
    assert r.data["metrics"]["rmse"] < 1e-10
    assert sorted(r.table.row_position) == list(range(20))
    assert len(r.data["folds"]) == 4
    for f in r.data["folds"]:
        assert set(f["train_positions"]).isdisjoint(f["test_positions"])
        assert f["scaler_mean"][0] == pytest.approx(t.iloc[f["train_positions"]].x.mean())


def test_evaluation_explicit_vectors_and_invalid_model_inputs(tmp_path):
    r = api().evaluate(data={"y_true": [1, 2, 3], "y_pred": [1, 3, 2]})
    assert r.data["metrics"]["mae"] == pytest.approx(2 / 3)
    assert r.data["metrics"]["rmse"] == pytest.approx((2 / 3) ** 0.5)
    assert r.data["metrics"]["r2"] == 0
    with pytest.raises(ValueError):
        api().regression(
            pd.DataFrame({"x": [1, np.nan, 2], "y": [2, 3, 4]}), config={"features": ["x"], "target": "y"}
        )
    bad = tmp_path / "evil.pkl"
    bad.write_bytes(b"invalid pickle")
    with pytest.raises(ValueError, match="skops|format"):
        api().predict(pd.DataFrame({"x": [1]}), config={"model_path": str(bad)})


def test_polynomial_recovers_quadratic_and_reports_original_scale_terms(tmp_path):
    x = np.linspace(-4, 4, 40)
    t = pd.DataFrame({"x": x, "y": 1 - 3 * x + 2 * x * x})
    r = api().regression(
        t,
        config={
            "features": ["x"],
            "target": "y",
            "method": "polynomial",
            "degree": 2,
            "output_dir": str(tmp_path),
        },
    )
    assert r.data["metrics"]["rmse"] < 1e-10
    assert r.data["model_summary"]["terms"] == ["x", "x^2"]
    assert r.data["model_summary"]["coefficients"] == pytest.approx([-3, 2])
    assert r.data["model_summary"]["intercept"] == pytest.approx(1)


def test_group_validation_prevents_pseudoreplication_and_paired_design_in_independent_test():
    t = groups()
    t["specimen"] = np.repeat(range(5), 3)
    with pytest.raises(ValueError, match="independent|replic"):
        api().significance(
            t, config={"method": "anova", "group": "group", "column": "value", "subject": "specimen"}
        )
    with pytest.raises(ValueError, match="paired|pair"):
        api().significance(
            t[t.group != "c"],
            config={"method": "welch", "group": "group", "column": "value", "pair_id": "sample"},
        )


def test_grouped_cv_and_holdout_do_not_split_specimens(tmp_path):
    t = pd.DataFrame({"x": range(30), "y": np.arange(30) * 2, "specimen": np.repeat(range(10), 3)})
    config = {
        "features": ["x"],
        "target": "y",
        "group_column": "specimen",
        "seed": 4,
        "output_dir": str(tmp_path),
    }
    r = api().regression(t, config=config)
    a, b = t.iloc[r.data["train_positions"]].specimen, t.iloc[r.data["test_positions"]].specimen
    assert set(a).isdisjoint(b)
    cv = api().evaluate(t, config={**config, "method": "cv", "folds": 5})
    for fold in cv.data["folds"]:
        assert set(t.iloc[fold["train_positions"]].specimen).isdisjoint(
            t.iloc[fold["test_positions"]].specimen
        )


def test_dunn_tie_correction_matches_hand_computed_rank_contrast():
    t = pd.DataFrame({"g": ["a"] * 3 + ["b"] * 3, "v": [1, 1, 2, 2, 3, 3]})
    r = api().multiple(t, config={"group": "g", "column": "v", "method": "dunn"})
    assert r.table.iloc[0].z == pytest.approx(-1.82574185835)
    assert r.table.iloc[0].p_adjusted == pytest.approx(0.06788915486)


def test_manifest_checksum_and_unknown_skops_type_rejected(tmp_path):
    import skops.io as sio

    t = pd.DataFrame({"x": range(10), "y": np.arange(10) * 2})
    r = api().regression(t, config={"features": ["x"], "target": "y", "output_dir": str(tmp_path)})
    from pathlib import Path

    model_path = Path(r.data["model_path"])
    model_path.write_bytes(model_path.read_bytes() + b"tampering")
    with pytest.raises(ValueError, match="SHA256"):
        api().predict(t, config={"model_path": str(model_path)}, data=r.data)
    evil = tmp_path / "unknown.skops"
    sio.dump({"custom_type": Path("hello")}, evil)
    with pytest.raises(ValueError, match="unreviewed|pipeline"):
        api().predict(t, config={"model_path": str(evil), "features": ["x"]})


def test_evaluate_saved_holdout_manifest_and_explicit_table_predictions(tmp_path):
    t = pd.DataFrame({"x": range(20), "y": np.arange(20) * 2})
    fitted = api().regression(t, config={"features": ["x"], "target": "y", "output_dir": str(tmp_path)})
    r = api().evaluate(t.iloc[fitted.data["test_positions"]], data=fitted.data)
    assert r.data["metrics"]["rmse"] < 1e-10
    assert r.data["evaluation"] == "manifest_holdout"
    t2 = pd.DataFrame({"real": [1, 2, 3], "prediction": [1, 3, 2]})
    r = api().evaluate(t2, config={"y_true": "real", "y_pred": "prediction"})
    assert r.data["metrics"]["r2"] == 0


@pytest.mark.parametrize(
    "operation, config",
    [
        ("correlation", {"columns": ["x", "y"]}),
        ("significance", {"group": "g", "column": "x"}),
        ("multiple", {"column": "x"}),
        ("grouped", {"group": "g", "columns": ["x"]}),
    ],
)
def test_statistical_methods_reject_missing_nonfinite_and_bad_probabilities(operation, config):
    t = pd.DataFrame({"g": ["a", "a", "b", "b"], "x": [1, 2, np.nan, 4], "y": [2, 4, 6, 8]})
    with pytest.raises(ValueError):
        getattr(api(), operation)(t, config=config)


def test_incomplete_pairs_drop_only_when_explicit():
    t = pd.DataFrame({"id": [1, 2, 3, 1, 2], "g": ["a"] * 3 + ["b"] * 2, "v": [1, 2, 3, 3, 6]})
    r = api().significance(
        t,
        config={
            "group": "g",
            "column": "v",
            "pair_id": "id",
            "method": "paired_t",
            "incomplete_pairs": "drop",
        },
    )
    assert r.data["n_pairs"] == 2 and r.data["dropped_pairs"] == 1


@pytest.mark.parametrize("operation", ["predict", "evaluate"])
@pytest.mark.parametrize(
    "route", ["config_manifest", "upstream_manifest", "config_json_model", "upstream_json_model"]
)
def test_manifest_only_routes_load_saved_model_without_retraining(tmp_path, operation, route):
    t = pd.DataFrame({"x": range(20), "y": np.arange(20) * 2 + 3})
    fitted = api().regression(t, config={"features": ["x"], "target": "y", "output_dir": str(tmp_path)})
    manifest = fitted.data["manifest_path"]
    routes = {
        "config_manifest": ({"manifest_path": manifest}, None),
        "upstream_manifest": ({}, {"manifest_path": manifest}),
        "config_json_model": ({"model_path": manifest}, None),
        "upstream_json_model": ({}, {"model_path": manifest}),
    }
    config, data = routes[route]
    heldout = t.iloc[fitted.data["test_positions"]]
    result = getattr(api(), operation)(heldout, config=config, data=data)
    np.testing.assert_allclose(result.table.y_pred, heldout.y.to_numpy(), atol=1e-10)
    if operation == "evaluate":
        assert result.data["evaluation"] == "manifest_holdout"
        assert result.data["metrics"]["rmse"] < 1e-10
    else:
        assert result.data["method"] == "saved_model_prediction"
    assert len(list(tmp_path.glob("*.skops"))) == 1
