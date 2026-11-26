"""Temporal model evaluation never trains on later observations or split units."""

import numpy as np
import pandas as pd
import pytest

from materials_quality.science import stats_models as models


def temporal():
    frame = pd.DataFrame({"time": np.repeat(np.arange(12), 2), "x": np.repeat(np.arange(12), 2)})
    frame["y"] = 3 * frame.x + 2
    frame["id"] = [f"s{i}" for i in range(len(frame))]
    return frame.sample(frac=1, random_state=7)


@pytest.fixture
def no_save(monkeypatch):
    monkeypatch.setattr(models, "_save", lambda model, config, metadata, verify: (dict(metadata), []))


def config(**extra):
    return {"features": ["x"], "target": "y", "id_column": "id", "time_column": "time", **extra}


def test_chronological_holdout_sorts_time_keeps_ties_and_fits_scale_on_past_only(no_save):
    frame = temporal()
    original = frame.copy(deep=True)
    result = models.fit_model(frame, config(validation_split="chronological_split", test_size=0.25))
    train, test = result.data["train_positions"], result.data["test_positions"]
    assert frame.iloc[train].time.max() < frame.iloc[test].time.min()
    assert frame.iloc[train].time.is_monotonic_increasing
    assert frame.iloc[test].time.is_monotonic_increasing
    assert result.data["scaler_mean"] == pytest.approx([frame.iloc[train].x.mean()])
    assert result.data["validation_split"] == "chronological_split"
    pd.testing.assert_frame_equal(frame, original)


def test_blocked_cv_scores_future_blocks_only_and_reports_initial_warmup():
    frame = temporal()
    result = models.evaluate_model(frame, config(method="cv", validation_split="blocked_cv", folds=3), {})
    assert result.data["validation_split"] == "blocked_cv"
    assert len(result.data["folds"]) == 3
    assert result.data["warmup_positions"]
    assert set(result.data["warmup_positions"]).isdisjoint(result.table.row_position)
    for fold in result.data["folds"]:
        train, test = fold["train_positions"], fold["test_positions"]
        assert frame.iloc[train].time.max() < frame.iloc[test].time.min()
        assert fold["scaler_mean"] == pytest.approx([frame.iloc[train].x.mean()])
    assert result.data["metrics"]["n"] == len(result.table)
    assert result.data["metrics"]["rmse"] < 1e-10


@pytest.mark.parametrize("mode,method", [("chronological_split", "holdout"), ("blocked_cv", "cv")])
def test_temporal_split_rejects_repeated_units_across_time_instead_of_random_fallback(mode, method, no_save):
    frame = temporal()
    frame["specimen"] = np.tile(["A", "B"], 12)
    with pytest.raises(ValueError, match="group|unit|specimen"):
        models.evaluate_model(
            frame, config(method=method, validation_split=mode, group_column="specimen", folds=3), {}
        )


@pytest.mark.parametrize("bad", [None, float("inf"), True, "not-a-time"])
def test_temporal_splits_reject_invalid_times(bad, no_save):
    frame = temporal().astype({"time": object})
    frame.iloc[0, frame.columns.get_loc("time")] = bad
    with pytest.raises(ValueError, match="time"):
        models.fit_model(frame, config(validation_split="chronological_split"))


def test_random_split_default_is_identical_to_explicit_random(no_save):
    frame = temporal()
    first = models.fit_model(frame, config())
    second = models.fit_model(frame, config(validation_split="random"))
    assert first.data["train_positions"] == second.data["train_positions"]
    assert first.data["test_positions"] == second.data["test_positions"]
    np.testing.assert_allclose(first.table.y_pred, second.table.y_pred)


@pytest.mark.parametrize("time_kind", ["datetime", "large_integer"])
def test_temporal_order_preserves_timestamps_and_large_integer_precision(time_kind, no_save):
    frame = temporal()
    if time_kind == "datetime":
        frame["time"] = pd.Timestamp("2026-01-01", tz="UTC") + pd.to_timedelta(frame.time, unit="h")
    else:
        frame["time"] = frame.time + 10**18
    result = models.fit_model(frame, config(validation_split="chronological_split"))
    assert (
        frame.iloc[result.data["train_positions"]].time.max()
        < frame.iloc[result.data["test_positions"]].time.min()
    )


def test_disjoint_temporal_groups_are_supported_without_shuffling(no_save):
    frame = temporal()
    frame["specimen"] = frame.time
    result = models.fit_model(frame, config(validation_split="chronological_split", group_column="specimen"))
    assert set(frame.iloc[result.data["train_positions"]].specimen).isdisjoint(
        frame.iloc[result.data["test_positions"]].specimen
    )


def test_residual_diagnostics_on_provided_predictions_are_descriptive():
    result = models.evaluate_model(
        None, {"residual_diagnostics": True}, {"y_true": [1, 2, 4], "y_pred": [1, 3, 3]}
    )
    assert result.table.residual.tolist() == [0, -1, 1]
    assert result.data["residual_diagnostics"]["mean"] == 0
    assert result.data["residual_diagnostics"]["n"] == 3


def test_ols_mean_interval_is_labeled_and_withheld_outside_training_domain(no_save):
    frame = pd.DataFrame({"x": np.linspace(-5, 5, 80)})
    frame["y"] = 2 * frame.x + 3 + np.sin(np.arange(len(frame))) * 0.1
    result = models.fit_model(frame, {"features": ["x"], "target": "y", "linear_trend_ci": True})
    interval = result.data["linear_trend_ci"]
    assert interval["kind"] == "OLS mean response confidence interval"
    assert interval["predictive_interval"] is False
    assert interval["status"] == "available"
    assert np.all(
        result.table.loc[result.table.mean_ci_lower.notna(), "mean_ci_lower"]
        <= result.table.loc[result.table.mean_ci_lower.notna(), "mean_ci_upper"]
    )
    future = models.fit_model(
        frame.assign(time=np.arange(len(frame))),
        {
            "features": ["x"],
            "target": "y",
            "validation_split": "chronological_split",
            "time_column": "time",
            "linear_trend_ci": True,
        },
    )
    assert future.table.mean_ci_lower.isna().all()
    assert future.data["linear_trend_ci"]["outside_training_domain"] == len(future.table)


def test_detected_heteroskedasticity_withholds_classical_mean_interval(no_save):
    rng = np.random.default_rng(18)
    x = np.linspace(0.1, 30, 500)
    frame = pd.DataFrame({"x": x, "y": 2 * x + rng.normal(size=len(x)) * x})
    result = models.fit_model(frame, {"features": ["x"], "target": "y", "linear_trend_ci": True})
    assert result.data["linear_trend_ci"]["status"] == "withheld_heteroskedasticity"
    assert result.table.mean_ci_lower.isna().all()


def test_unsupported_model_does_not_claim_an_ols_confidence_interval(no_save):
    result = models.fit_model(temporal(), config(method="ridge", linear_trend_ci=True))
    assert result.data["linear_trend_ci"]["status"] == "unsupported_model"
    assert result.table.mean_ci_lower.isna().all()


def test_ols_mean_interval_uses_centered_coordinates_for_large_time_like_offsets(no_save):
    x = 10**12 + np.arange(80)
    frame = pd.DataFrame({"x": x, "y": 2 * np.arange(80) + np.sin(np.arange(80)) * 0.1})
    result = models.fit_model(frame, {"features": ["x"], "target": "y", "linear_trend_ci": True})
    assert result.data["linear_trend_ci"]["status"] == "available"
    assert result.table.mean_ci_lower.notna().any()


def test_blocked_cv_optional_mean_intervals_are_fold_specific():
    result = models.evaluate_model(
        temporal(),
        config(
            method="cv",
            validation_split="blocked_cv",
            folds=3,
            linear_trend_ci=True,
            residual_diagnostics=True,
        ),
        {},
    )
    assert result.data["linear_trend_ci"]["fold_specific"] is True
    assert len(result.data["linear_trend_ci"]["folds"]) == 3
    assert result.table.mean_ci_lower.isna().all()
    assert result.data["residual_diagnostics"]["n"] == len(result.table)


@pytest.mark.parametrize(
    "settings",
    [
        {"validation_split": "blocked_cv"},
        {"validation_split": "invented"},
        {"validation_split": "chronological_split"},
    ],
)
def test_invalid_temporal_requests_do_not_silently_use_random(settings, no_save):
    with pytest.raises(ValueError):
        models.fit_model(temporal(), {"features": ["x"], "target": "y", **settings})
