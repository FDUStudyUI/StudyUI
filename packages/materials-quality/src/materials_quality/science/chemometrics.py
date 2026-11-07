"""Deterministic PCA/PLS with explicit identity-safe partitions and train-only fitting.

Fixed per-spectrum preprocessing belongs upstream. This node never estimates a
transform from the full dataset and never uses test metrics to choose components.
"""

import warnings as warning_module
from copy import deepcopy

import numpy as np
import pandas as pd
from sklearn.cross_decomposition import PLSRegression
from sklearn.decomposition import PCA
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .contracts import NodeResult, numeric_matrix, require_table


def _identities(frame, column, name):
    if not isinstance(column, str) or not column.strip():
        raise ValueError(f"{name} must name an explicit identity column")
    require_table(frame, [column])
    values = frame[column]
    if values.isna().any() or values.map(lambda v: not str(v).strip()).any():
        raise ValueError(f"{name} contains missing identities")
    # Avoid converting different typed identities into the same text identifier.
    if values.map(type).nunique() != 1:
        raise ValueError(f"{name} identities must use one consistent scalar type")
    if values.map(lambda value: not isinstance(value, (str, int, float, np.integer, np.floating))).any():
        raise ValueError(f"{name} identities must be text or finite numbers")
    if values.map(lambda value: isinstance(value, (float, np.floating)) and not np.isfinite(value)).any():
        raise ValueError(f"{name} contains non-finite identities")
    return values.astype(str).to_numpy()


def _fit(x, y, method, components, scale):
    if np.any(np.ptp(x, axis=0) == 0):
        raise ValueError("training features contain zero variance; remove explicitly before modeling")
    rank = int(np.linalg.matrix_rank(x - x.mean(axis=0)))
    if components > rank:
        raise ValueError(f"n_components exceeds centered training rank ({rank})")
    if method == "pls" and np.ptp(y) == 0:
        raise ValueError("PLS training target must have nonzero variance")
    estimator = (
        PCA(n_components=components, svd_solver="full")
        if method == "pca"
        else PLSRegression(n_components=components, scale=False, max_iter=1000, tol=1e-06)
    )
    pipeline = Pipeline([("scale", StandardScaler(with_std=scale)), ("model", estimator)])
    with warning_module.catch_warnings(record=True) as caught:
        warning_module.simplefilter("always")
        pipeline.fit(x, y if method == "pls" else None)
    if any(issubclass(item.category, ConvergenceWarning) for item in caught):
        raise ValueError("PLS did not converge; review component count and training data")
    # Constant residual warnings can mean requested PLS components do not exist.
    if method == "pls" and len(estimator.n_iter_) < components:
        raise ValueError("PLS exhausted target residual before n_components; reduce component count")
    return pipeline


def _metrics(actual, predicted):
    if not len(actual):
        return None
    return {
        "n_samples": len(actual),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "mae": float(mean_absolute_error(actual, predicted)),
        "r2": float(r2_score(actual, predicted)) if len(actual) > 1 and np.ptp(actual) > 0 else None,
    }


def chemometrics(table=None, *, config=None, data=None, tables=None):
    """Fit PCA or single-target PLS on rows explicitly labelled train; transform test only.

    Required: feature_columns, sample_column, split_column (values train/test).
    PLS additionally requires target_column. Repeated sample/group identities are
    kept together in held-out partitions and all optional component-selection folds.
    n_components is fixed unless cv_folds >= 2 (PLS), where it is a search upper bound.
    """
    config = dict(config or {})
    frame = require_table(table, min_rows=3)
    method = config.get("method", "pca")
    if method not in {"pca", "pls"}:
        raise ValueError("method must be pca or pls")
    columns = config.get("feature_columns")
    if (
        not isinstance(columns, list)
        or not columns
        or any(not isinstance(c, str) for c in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("feature_columns must be a nonempty list of unique column names")
    sample_column, split_column = config.get("sample_column"), config.get("split_column")
    sample_ids = _identities(frame, sample_column, "sample_column")
    split = _identities(frame, split_column, "split_column")
    if not set(split) <= {"train", "test"}:
        raise ValueError("split_column must contain only explicit train/test labels")
    train = split == "train"
    test = split == "test"
    if train.sum() < 3:
        raise ValueError("at least three train rows are required")
    if set(sample_ids[train]) & set(sample_ids[test]):
        raise ValueError("sample identities must not cross train/test split")
    group_column = config.get("group_column")
    groups = _identities(frame, group_column, "group_column") if group_column else sample_ids.copy()
    if set(groups[train]) & set(groups[test]):
        raise ValueError("group identities must not cross train/test split")
    assignments = pd.DataFrame({"sample": sample_ids, "group": groups})
    if (assignments.groupby("sample").group.nunique() > 1).any():
        raise ValueError("each repeated sample must belong to one group for group-safe folds")
    target = config.get("target_column")
    protected = {sample_column, split_column, group_column, target} - {None, ""}
    if set(columns) & protected:
        raise ValueError("feature_columns must exclude target, sample, group and split columns")
    if method == "pls" and (not isinstance(target, str) or not target):
        raise ValueError("PLS requires target_column")
    x = numeric_matrix(frame, columns)
    y = numeric_matrix(frame, [target]).ravel() if method == "pls" else None
    scale = config.get("scale", True)
    if type(scale) is not bool:
        raise ValueError("scale must be a boolean")
    components = config.get("n_components", 2)
    if type(components) is not int or not 1 <= components <= min(int(train.sum()) - 1, len(columns)):
        raise ValueError("n_components must be positive and <= min(n_train-1, n_features)")
    folds_count = config.get("cv_folds", 0)
    if type(folds_count) is not int or folds_count < 0 or folds_count == 1:
        raise ValueError("cv_folds must be 0 (fixed components) or an integer >=2")
    if method == "pca" and folds_count:
        raise ValueError("PCA uses explicit n_components; CV component selection is only offered for PLS")
    xt, yt, ids, gt = x[train], y[train] if y is not None else None, sample_ids[train], groups[train]
    cv = {"enabled": bool(folds_count), "folds": [], "candidates": [], "selection_metric": None}
    if folds_count:
        if folds_count > len(set(gt)):
            raise ValueError("cv_folds exceeds independent training group count")
        splits = list(GroupKFold(n_splits=folds_count).split(xt, yt, gt))
        for fit, validation in splits:
            if len(fit) < 3:
                raise ValueError("each CV training fold needs at least three rows")
            cv["folds"].append(
                {
                    "train_sample_ids": ids[fit].tolist(),
                    "validation_sample_ids": ids[validation].tolist(),
                    "train_group_ids": sorted(set(gt[fit])),
                    "validation_group_ids": sorted(set(gt[validation])),
                }
            )
        for candidate in range(1, components + 1):
            prediction = np.empty(len(yt))
            try:
                for fit, validation in splits:
                    pipeline = _fit(xt[fit], yt[fit], method, candidate, scale)
                    prediction[validation] = pipeline.predict(xt[validation]).ravel()
                rmse = float(np.sqrt(mean_squared_error(yt, prediction)))
                cv["candidates"].append({"n_components": candidate, "rmse": rmse, "status": "valid"})
            except ValueError as exc:
                cv["candidates"].append(
                    {"n_components": candidate, "rmse": None, "status": "invalid", "reason": str(exc)}
                )
        valid = [row for row in cv["candidates"] if row["status"] == "valid"]
        if not valid:
            raise ValueError(
                "no valid component count in training-only CV; inspect training fold variance/rank"
            )
        components = min(valid, key=lambda row: (row["rmse"], row["n_components"]))["n_components"]
        cv["selection_metric"] = "pooled out-of-fold RMSE on training rows only; ties select fewer components"
    pipeline = _fit(xt, yt, method, components, scale)
    scaler, model = pipeline.named_steps["scale"], pipeline.named_steps["model"]
    scores = pipeline.transform(x)
    if not np.isfinite(scores).all():
        raise ValueError("model returned non-finite component scores")
    output = pd.DataFrame({"source_row": np.arange(len(frame)), "sample_id": sample_ids, "split": split})
    features = output[["sample_id", "split"]].copy()
    if group_column:
        output["group_id"] = groups
    for i in range(components):
        output[f"component_{i + 1}"] = scores[:, i]
        features[f"component_{i + 1}"] = scores[:, i]
    model_data = {
        "method": method,
        "n_components": components,
        "feature_columns": list(columns),
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist() if scale else [1.0] * len(columns),
        "fit_partition": "train",
        "implementation": "sklearn Pipeline(StandardScaler, PCA/PLSRegression)",
    }
    metrics = {"train": None, "test": None}
    if method == "pls":
        predicted = pipeline.predict(x).ravel()
        if not np.isfinite(predicted).all():
            raise ValueError("PLS returned non-finite predictions")
        output["observed"], output["prediction"] = y, predicted
        output["residual"] = y - predicted
        target_unit = frame.attrs.get("units", {}).get(target, "unspecified")
        output.attrs["units"] = dict.fromkeys(["observed", "prediction", "residual"], target_unit)
        model_data["target_column"] = target
        model_data["target_unit"] = target_unit
        metrics = {"train": _metrics(y[train], predicted[train]), "test": _metrics(y[test], predicted[test])}
        model_data.update(
            {
                "coefficients_scaled_features": model.coef_.tolist(),
                "intercept": model.intercept_.tolist(),
                "x_rotations": model.x_rotations_.tolist(),
                "x_loadings": model.x_loadings_.tolist(),
                "n_iter": model.n_iter_,
            }
        )
    else:
        model_data.update(
            {
                "components": model.components_.tolist(),
                "pca_mean": model.mean_.tolist(),
                "explained_variance": model.explained_variance_.tolist(),
                "explained_variance_ratio": model.explained_variance_ratio_.tolist(),
            }
        )
    warnings = [
        "Identity isolation follows the supplied sample/group labels; "
        "verify repeated specimens and instruments share identities."
    ]
    if not test.any():
        warnings.append("No independent test set: training/CV results do not assess held-out generalization.")
    if method == "pca":
        warnings.append("PCA scores describe variance; they are not class or concentration predictions.")
    return NodeResult(
        table=output,
        features=features,
        data={
            "method": method,
            "config": deepcopy(config),
            "model": model_data,
            "cv": cv,
            "train_sample_ids": sample_ids[train].tolist(),
            "test_sample_ids": sample_ids[test].tolist(),
            "train_group_ids": sorted(set(groups[train])),
            "test_group_ids": sorted(set(groups[test])),
            "feature_columns": list(columns),
            "metrics": metrics,
            "generalization_assessed": bool(method == "pls" and test.any()),
            "split_policy": "explicit train/test labels; fit/selection on training rows only",
        },
        warnings=warnings,
    )


CATALOG = [
    {
        "key": "materials.chemometrics",
        "title": "PCA/PLS 化学计量学",
        "function": "materials_quality.science.chemometrics:chemometrics",
        "category": "材料专业分析",
        "requirement": "显式样品划分的 PCA 特征与 PLS 回归",
        "table_input": True,
        "data_input": False,
        "tables_input": False,
        "default_config": {"method": "pca", "n_components": 2, "scale": True, "cv_folds": 0},
    }
]
