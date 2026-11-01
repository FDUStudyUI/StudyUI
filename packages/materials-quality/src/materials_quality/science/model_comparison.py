"""Evaluate multiple estimators on one fixed plan, without saving fitted models."""

from copy import deepcopy

import numpy as np
import pandas as pd
from sklearn.base import clone

from .contracts import NodeResult
from .stats_models import (
    _dataset,
    _evaluation_config,
    _evaluation_splits,
    _json,
    _linear_ci,
    _metrics,
    _option,
    _pipeline,
    _residual_diagnostics,
    _seed,
    _time_metadata,
)

MODEL_NAMES = ("linear", "polynomial", "ridge", "lasso", "random_forest", "gradient_boosting", "svr")


def compare_models(table, config):
    """Return scores and full heldout predictions using identical original rows.

    ``models`` is a distinct list of MODEL_NAMES. Existing holdout/CV options and
    temporal validation_split/time_column/group_column semantics are shared with
    stats_models. No winner is refit and no persisted model is produced.
    """
    if not isinstance(config, dict):
        raise ValueError("config must be an object containing models, features and target")
    c, evaluation = _evaluation_config(config)
    names = c.get("models")
    if (
        not isinstance(names, list)
        or not names
        or any(not isinstance(name, str) for name in names)
        or len(set(names)) != len(names)
        or set(names) - set(MODEL_NAMES)
    ):
        raise ValueError("models must be a nonempty distinct list of supported model names")
    if any(c.get(key) for key in ("model_path", "manifest_path", "y_true", "y_pred")):
        raise ValueError(
            "models comparison fits candidates; saved models/provided prediction routes cannot be combined"
        )
    frame, x, y, ids, groups = _dataset(table, c)
    splits, validation = _evaluation_splits(frame, c, groups, evaluation)
    plan = [
        {
            "fold": fold,
            "train_positions": train.tolist(),
            "test_positions": test.tolist(),
            "train_ids": [ids[i] for i in train],
            "test_ids": [ids[i] for i in test],
            **_time_metadata(frame, c, train, test),
        }
        for fold, (train, test) in enumerate(splits)
    ]
    diagnostics, interval = _option(c, "residual_diagnostics"), _option(c, "linear_trend_ci")
    rows, results = [], []
    for name in names:
        pipeline, method = _pipeline({**c, "model_method": name}, name)
        observed, predictions, positions, fold_metrics, intervals = [], [], [], [], []
        for fold, (train, test) in enumerate(splits):
            fitted = clone(pipeline).fit(x[train], y[train])
            predicted = fitted.predict(x[test])
            observed.extend(y[test].tolist())
            predictions.extend(predicted.tolist())
            positions.extend(test.tolist())
            fold_metrics.append(
                {
                    "fold": fold,
                    "metrics": _metrics(y[test], predicted),
                    "scaler_mean": fitted.named_steps["scale"].mean_.tolist(),
                }
            )
            if interval:
                lower, upper, details = _linear_ci(c, method, x[train], y[train], x[test])
                intervals.append(
                    {
                        "fold": fold,
                        **details,
                        "intervals": [
                            {
                                "row_position": int(position),
                                "lower": float(a) if np.isfinite(a) else None,
                                "upper": float(b) if np.isfinite(b) else None,
                            }
                            for position, a, b in zip(test, lower, upper, strict=True)
                        ],
                    }
                )
        metrics = _metrics(observed, predictions)
        rows.append({"model": name, **metrics})
        record = {
            "model": name,
            "metrics": metrics,
            "splits": deepcopy(plan),
            "folds": fold_metrics,
            "predictions": [
                {
                    "row_position": position,
                    "sample_id": ids[position],
                    "y_true": actual,
                    "y_pred": predicted,
                    "residual": actual - predicted,
                }
                for position, actual, predicted in zip(positions, observed, predictions, strict=True)
            ],
        }
        if diagnostics:
            record["residual_diagnostics"] = _residual_diagnostics(observed, predictions)
        if interval:
            record["linear_trend_ci"] = {
                "kind": "OLS mean response confidence interval",
                "predictive_interval": False,
                "folds": intervals,
            }
        results.append(record)
    evaluated = {int(position) for _, test in splits for position in test}
    output = pd.DataFrame(rows)
    units = frame.attrs.get("units", {})
    target_unit = units.get(c["target"]) if isinstance(units, dict) else None
    if target_unit:
        output.attrs["units"] = {"mae": target_unit, "rmse": target_unit, "r2": "dimensionless"}
    return NodeResult(
        output,
        _json(
            {
                "evaluation": "model_comparison",
                "evaluation_method": evaluation,
                "validation_split": validation,
                "models": list(names),
                "features": c["features"],
                "target": c["target"],
                "target_unit": target_unit,
                "time_column": c.get("time_column"),
                "group_column": c.get("group_column"),
                "seed": _seed(c),
                "splits": plan,
                "warmup_positions": [i for i in range(len(frame)) if i not in evaluated],
                "model_results": results,
                "preprocessing": "Every model/fold fits preprocessing on the same training positions.",
            }
        ),
        warnings=[
            "Selecting a model on these scores reuses evaluation data; "
            "use a separate untouched final test set for final assessment.",
            "Temporal scores describe later observations; they do not establish forecast coverage."
            if validation != "random"
            else "Row-random splits assume independent rows; use group_column for repeated units.",
        ],
    )
