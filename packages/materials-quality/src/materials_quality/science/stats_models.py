"""Train-split pipelines, honest evaluation and restricted skops persistence."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Lasso, LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit, KFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from sklearn.svm import SVR

from .contracts import NodeResult, artifact_path, numeric_matrix, require_table

# Only this explicitly reviewed nondefault skops type is needed by the models
# generated here. Never trust an entire module prefix or arbitrary file contents.
_TRUSTED_TYPES = {
    "sklearn.ensemble._gb_losses.LeastSquaresError",
    "sklearn._loss.loss.HalfSquaredError",
    "sklearn._loss._loss.CyHalfSquaredError",
    "sklearn._loss.link.IdentityLink",
    "sklearn._loss.link.Interval",
}


def _json(value):
    return json.loads(
        json.dumps(
            value, default=lambda x: x.item() if isinstance(x, np.generic) else str(x), allow_nan=False
        )
    )


def _seed(c):
    seed = c.get("seed", 42)
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    return seed


def _pipeline(c, default):
    method = c.get("model_method", c.get("method", default))
    if method in {"holdout", "cv"}:
        method = default
    seed = _seed(c)
    alpha = float(c.get("alpha", 1.0))
    if not np.isfinite(alpha) or alpha < 0:
        raise ValueError("regularization alpha must be finite and nonnegative")
    estimators = {
        "linear": lambda: LinearRegression(),
        "polynomial": lambda: LinearRegression(),
        "ridge": lambda: Ridge(alpha=alpha),
        "lasso": lambda: Lasso(alpha=alpha, max_iter=int(c.get("max_iter", 10000))),
        "random_forest": lambda: RandomForestRegressor(
            n_estimators=int(c.get("n_estimators", 100)),
            random_state=seed,
            n_jobs=1,
            max_depth=c.get("max_depth"),
        ),
        "gradient_boosting": lambda: GradientBoostingRegressor(
            random_state=seed,
            n_estimators=int(c.get("n_estimators", 100)),
            max_depth=int(c.get("max_depth", 3)),
        ),
        "svr": lambda: SVR(
            C=float(c.get("C", 10)), epsilon=float(c.get("epsilon", 0.1)), kernel=c.get("kernel", "rbf")
        ),
    }
    if method not in estimators:
        raise ValueError(f"unknown model_method: {method}")
    steps = []
    if method == "polynomial":
        degree = c.get("degree", 2)
        if type(degree) is not int or not 1 <= degree <= 8:
            raise ValueError("polynomial degree must be an integer between 1 and 8")
        steps.append(("polynomial", PolynomialFeatures(degree=degree, include_bias=False)))
    steps.extend([("scale", StandardScaler()), ("model", estimators[method]())])
    return Pipeline(steps), method


def _dataset(table, c):
    features, target = c.get("features"), c.get("target")
    if not isinstance(features, list) or not features or len(set(features)) != len(features):
        raise ValueError("features must be a nonempty distinct column list")
    if target in features:
        raise ValueError("target cannot also be a predictor feature")
    frame = require_table(table, [*features, target], min_rows=5)
    x = numeric_matrix(frame, features)
    y = numeric_matrix(frame, [target])[:, 0]
    ids = list(range(len(frame)))
    id_col = c.get("id_column")
    if id_col:
        require_table(frame, [id_col])
        if frame[id_col].isna().any() or frame[id_col].duplicated().any():
            raise ValueError("id_column must contain unique, nonmissing row IDs")
        ids = _json(frame[id_col].tolist())
    group_col = c.get("group_column")
    groups = None
    if group_col:
        require_table(frame, [group_col])
        if frame[group_col].isna().any() or frame[group_col].nunique() < 2:
            raise ValueError("group_column requires nonmissing labels and at least two groups")
        groups = frame[group_col].to_numpy()
    return frame, x, y, ids, groups


def _metrics(y, prediction):
    y, prediction = np.asarray(y, float), np.asarray(prediction, float)
    if y.ndim != 1 or prediction.shape != y.shape or len(y) < 2:
        raise ValueError("at least two aligned one-dimensional observed/predicted values required")
    if not np.isfinite(y).all() or not np.isfinite(prediction).all():
        raise ValueError("metrics require finite values")
    return {
        "mae": float(mean_absolute_error(y, prediction)),
        "rmse": float(np.sqrt(mean_squared_error(y, prediction))),
        "r2": None if np.ptp(y) == 0 else float(r2_score(y, prediction)),
        "n": len(y),
    }


def _row_fingerprints(frame, features, target, id_column=None):
    values = numeric_matrix(frame, [*features, target])
    fingerprints = []
    for i, row in enumerate(values):
        record = {"features": features, "target": target, "values": row.tolist()}
        if id_column:
            record["sample_id"] = _json(frame.iloc[i][id_column])
        encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
        fingerprints.append(hashlib.sha256(encoded).hexdigest())
    return fingerprints


def _summary(pipeline, features):
    fitted = pipeline.named_steps["model"]
    terms = features
    if "polynomial" in pipeline.named_steps:
        terms = pipeline.named_steps["polynomial"].get_feature_names_out(features).tolist()
    if hasattr(fitted, "coef_"):
        scale = pipeline.named_steps["scale"]
        coef = fitted.coef_ / scale.scale_
        intercept = float(fitted.intercept_ - np.dot(coef, scale.mean_))
        return {
            "terms": terms,
            "coefficients": coef.tolist(),
            "intercept": intercept,
            "coefficient_scale": "original feature units (polynomial terms where configured)",
        }
    if hasattr(fitted, "feature_importances_"):
        return {
            "terms": terms,
            "feature_importances": fitted.feature_importances_.tolist(),
            "importance_definition": "impurity-based importance; not causal effects",
        }
    return {"terms": terms, "kernel": fitted.kernel, "support_vectors": int(len(fitted.support_))}


def _split(n, c, groups):
    size = c.get("test_size", 0.2)
    if not isinstance(size, (int, float)) or isinstance(size, bool) or not 0 < size < 1:
        raise ValueError("test_size must be a fraction between zero and one")
    positions = np.arange(n)
    if groups is not None:
        train, test = next(
            GroupShuffleSplit(n_splits=1, test_size=size, random_state=_seed(c)).split(
                positions, groups=groups
            )
        )
    else:
        train, test = train_test_split(positions, test_size=size, random_state=_seed(c))
    if len(train) < 2 or len(test) < 2:
        raise ValueError("holdout requires at least two training and two test observations")
    return train, test


def _time_values(frame, c):
    column = c.get("time_column")
    if not isinstance(column, str) or not column.strip():
        raise ValueError("time_column is required for temporal validation")
    require_table(frame, [column])
    series = frame[column]
    if series.isna().any() or series.map(lambda value: isinstance(value, (bool, np.bool_))).any():
        raise ValueError("time_column must contain valid nonmissing times, never booleans")
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        parsed = pd.to_datetime(series, utc=True, errors="coerce")
        if parsed.isna().any():
            raise ValueError("time_column contains invalid timestamps")
        return parsed.astype("int64").to_numpy()
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().all():
        dtype = (
            ("uint64" if pd.api.types.is_unsigned_integer_dtype(numeric.dtype) else "int64")
            if pd.api.types.is_integer_dtype(numeric.dtype)
            else float
        )
        values = numeric.to_numpy(dtype=dtype)
        if not np.isfinite(values).all():
            raise ValueError("time_column contains non-finite times")
        return values
    if any(isinstance(value, (int, float, np.number)) for value in series):
        raise ValueError("time_column cannot mix numeric times and timestamps")
    parsed = pd.to_datetime(series, format="mixed", utc=True, errors="coerce")
    if parsed.isna().any():
        raise ValueError("time_column contains invalid timestamps")
    return parsed.astype("int64").to_numpy()


def _group_boundary(groups, train, test):
    if groups is not None and set(groups[train]).intersection(groups[test]):
        raise ValueError("temporal validation would split a group_column experimental unit across train/test")


def _check_fold_sizes(splits):
    for index, (train, test) in enumerate(splits):
        if len(train) < 2 or len(test) < 2:
            raise ValueError(
                f"cross-validation fold {index} must contain at least two training and two test "
                "observations; reduce folds or merge singleton groups"
            )
    return splits


def _evaluation_splits(frame, c, groups, evaluation):
    """Return original row positions; equal times never cross a temporal boundary."""
    mode = c.get("validation_split", "random")
    if mode not in {"random", "chronological_split", "blocked_cv"}:
        raise ValueError("validation_split must be random, chronological_split or blocked_cv")
    if evaluation not in {"holdout", "cv"}:
        raise ValueError("evaluation method must be holdout or cv")
    n = len(frame)
    if evaluation == "holdout" and mode == "random":
        return [_split(n, c, groups)], mode
    folds = c.get("folds", 5)
    if evaluation == "cv":
        if type(folds) is not int or not 2 <= folds <= n // 2:
            raise ValueError("folds must allow at least two test observations in every fold")
        if mode == "chronological_split":
            raise ValueError("chronological_split is a holdout strategy; select blocked_cv for temporal CV")
        if mode == "random":
            if groups is None:
                splitter = KFold(n_splits=folds, shuffle=True, random_state=_seed(c))
            else:
                if len(np.unique(groups)) < folds:
                    raise ValueError("fold count exceeds number of independent groups")
                splitter = GroupKFold(n_splits=folds)
            return _check_fold_sizes(list(splitter.split(np.arange(n), groups=groups))), mode
    elif mode == "blocked_cv":
        raise ValueError("blocked_cv requires method='cv', not a saved holdout model")
    times = _time_values(frame, c)
    order = np.argsort(times, kind="stable")
    if evaluation == "holdout":
        size = c.get("test_size", 0.2)
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not 0 < size < 1:
            raise ValueError("test_size must be a fraction between zero and one")
        desired = n - int(np.ceil(n * size))
        boundaries = [i for i in range(2, n - 1) if times[order[i - 1]] < times[order[i]]]
        if not boundaries:
            raise ValueError(
                "time_column needs a boundary with at least two past and two future observations"
            )
        cut = min(boundaries, key=lambda i: (abs(i - desired), i))
        splits = [(order[:cut], order[cut:])]
    else:
        unique_times = np.unique(times)
        if len(unique_times) < folds + 1:
            raise ValueError("blocked_cv requires at least folds+1 distinct time blocks")
        blocks = np.array_split(unique_times, folds + 1)
        splits = []
        for index in range(1, len(blocks)):
            train = order[times[order] < blocks[index][0]]
            test = order[np.isin(times[order], blocks[index])]
            if len(train) < 2 or len(test) < 2:
                raise ValueError("blocked_cv needs at least two training and two test observations per block")
            splits.append((train, test))
    for train, test in splits:
        _group_boundary(groups, train, test)
    return splits, mode


def _evaluation_config(c):
    c = dict(c)
    evaluation = c.get("method", "holdout")
    if evaluation == "chronological_split":
        evaluation = "holdout"
        c["validation_split"] = "chronological_split"
    elif evaluation == "blocked_cv":
        evaluation = "cv"
        c["validation_split"] = "blocked_cv"
    c["method"] = evaluation
    return c, evaluation


def _time_metadata(frame, c, train, test):
    if c.get("validation_split", "random") == "random":
        return {}
    column = c["time_column"]
    return {
        "time_column": column,
        "train_time_bounds": _json(frame.iloc[train][column].iloc[[0, -1]].tolist()),
        "test_time_bounds": _json(frame.iloc[test][column].iloc[[0, -1]].tolist()),
    }


def _option(c, name):
    value = c.get(name, False)
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _residual_diagnostics(y, predicted):
    residual = np.asarray(y, float) - np.asarray(predicted, float)
    denominator = float(np.dot(residual, residual))
    shapiro_p = None
    if 3 <= len(residual) <= 5000 and np.ptp(residual) > np.finfo(float).eps * max(
        1.0, float(np.max(np.abs(y)))
    ):
        from scipy.stats import shapiro

        value = float(shapiro(residual).pvalue)
        shapiro_p = value if np.isfinite(value) else None
    return {
        "n": len(residual),
        "mean": float(np.mean(residual)),
        "sample_std": float(np.std(residual, ddof=1)),
        "min": float(np.min(residual)),
        "max": float(np.max(residual)),
        "shapiro_pvalue": shapiro_p,
        "durbin_watson": float(np.dot(np.diff(residual), np.diff(residual)) / denominator)
        if denominator
        else None,
        "interpretation": (
            "Descriptive heldout residuals; order-dependent serial-correlation summary, "
            "not a proof of model assumptions."
        ),
    }


def _linear_ci(c, method, train_x, train_y, test_x):
    """Classical single-predictor OLS mean interval, restricted to training support."""
    n_test = len(test_x) if test_x is not None else 0
    lower, upper = np.full(n_test, np.nan), np.full(n_test, np.nan)
    details = {"kind": "OLS mean response confidence interval", "predictive_interval": False}
    confidence = c.get("confidence_level", 0.95)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 < confidence < 1:
        raise ValueError("confidence_level must be a fraction between zero and one")
    details["confidence_level"] = confidence
    if train_x is None or train_y is None:
        return lower, upper, {**details, "status": "training_data_unavailable"}
    if method != "linear" or train_x.shape[1] != 1:
        return (
            lower,
            upper,
            {
                **details,
                "status": "unsupported_model",
                "reason": "Only a single-predictor unregularized linear OLS mean is supported.",
            },
        )
    if len(train_y) < 4:
        return lower, upper, {**details, "status": "insufficient_training_rows"}
    x_center = float(np.mean(train_x[:, 0]))
    centered = train_x[:, 0] - x_center
    design = np.column_stack([np.ones(len(train_x)), centered])
    if np.linalg.matrix_rank(design) != 2:
        return lower, upper, {**details, "status": "rank_deficient"}
    beta = np.linalg.lstsq(design, train_y, rcond=None)[0]
    residual = train_y - design @ beta
    sigma2 = float(residual @ residual / (len(train_y) - 2))
    hetero_p = None
    if len(train_y) >= 8 and sigma2 > np.finfo(float).eps * max(1.0, float(np.var(train_y))):
        from statsmodels.stats.diagnostic import het_breuschpagan

        hetero_p = float(het_breuschpagan(residual, design)[1])
        if not np.isfinite(hetero_p):
            hetero_p = None
    details.update(
        training_domain=[float(train_x[:, 0].min()), float(train_x[:, 0].max())],
        heteroskedasticity_bp_pvalue=hetero_p,
        assumptions=(
            "Correct linear conditional mean, independent errors and constant residual variance. "
            "Gaussian errors are needed for exact finite-sample t coverage. "
            "A nonsignificant diagnostic does not establish these assumptions."
        ),
        scope=(
            "Within the training feature domain only; no extrapolation, "
            "individual prediction interval or forecast coverage claim."
        ),
    )
    if hetero_p is not None and hetero_p < 0.05:
        return lower, upper, {**details, "status": "withheld_heteroskedasticity"}
    from scipy.stats import t

    in_domain = (test_x[:, 0] >= train_x[:, 0].min()) & (test_x[:, 0] <= train_x[:, 0].max())
    test_design = np.column_stack([np.ones(n_test), test_x[:, 0] - x_center])
    error = np.sqrt(sigma2 * (1 / len(train_y) + (test_x[:, 0] - x_center) ** 2 / float(centered @ centered)))
    mean = test_design @ beta
    width = float(t.ppf((1 + confidence) / 2, len(train_y) - 2)) * error
    lower[in_domain], upper[in_domain] = (mean - width)[in_domain], (mean + width)[in_domain]
    return (
        lower,
        upper,
        {**details, "status": "available", "outside_training_domain": int((~in_domain).sum())},
    )


def _add_diagnostics(result, c, *, method=None, train_x=None, train_y=None, test_x=None):
    diagnostics, interval = _option(c, "residual_diagnostics"), _option(c, "linear_trend_ci")
    if diagnostics:
        result.table["residual"] = result.table.y_true - result.table.y_pred
        result.data["residual_diagnostics"] = _residual_diagnostics(result.table.y_true, result.table.y_pred)
    if interval:
        lower, upper, details = _linear_ci(c, method, train_x, train_y, test_x)
        if test_x is None:
            lower, upper = np.full(len(result.table), np.nan), np.full(len(result.table), np.nan)
        result.table["mean_ci_lower"], result.table["mean_ci_upper"] = lower, upper
        result.data["linear_trend_ci"] = details
        result.warnings.append(
            details.get(
                "scope",
                details.get(
                    "reason", "Training observations are required for an OLS mean confidence interval."
                ),
            )
        )
    return result


def _load(path, digest=None):
    import skops.io as sio

    path = Path(path).expanduser().resolve()
    if path.suffix != ".skops" or not path.is_file():
        raise ValueError("model format must be an existing .skops artifact")
    if digest and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("model SHA256 mismatch")
    unknown = set(sio.get_untrusted_types(file=path))
    if unknown - _TRUSTED_TYPES:
        raise ValueError(f"unreviewed skops types: {sorted(unknown - _TRUSTED_TYPES)}")
    model = sio.load(path, trusted=sorted(unknown))
    if not isinstance(model, Pipeline) or set(model.named_steps) - {"polynomial", "scale", "model"}:
        raise ValueError("model must be a generated sklearn pipeline")
    if not isinstance(
        model.named_steps.get("model"),
        (LinearRegression, Ridge, Lasso, RandomForestRegressor, GradientBoostingRegressor, SVR),
    ):
        raise ValueError("model estimator type is outside the supported allowlist")
    return model


def _save(model, c, metadata, verify_x):
    import skops.io as sio

    path = artifact_path(c, "model.skops")
    sio.dump(model, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"format": "materials-quality-skops-v1", "model_path": str(path), "sha256": digest, **metadata}
    restored = _load(path, digest)
    np.testing.assert_allclose(restored.predict(verify_x), model.predict(verify_x), rtol=1e-12, atol=1e-12)
    manifest_path = artifact_path({**c, "output_dir": str(path.parent)}, "model-manifest.json")
    manifest_path.write_text(json.dumps(_json(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest, [str(path), str(manifest_path)]


def fit_model(table, c, default="linear"):
    _option(c, "residual_diagnostics")
    if _option(c, "linear_trend_ci"):
        level = c.get("confidence_level", 0.95)
        if isinstance(level, bool) or not isinstance(level, (int, float)) or not 0 < level < 1:
            raise ValueError("confidence_level must be a fraction between zero and one")
    frame, x, y, ids, groups = _dataset(table, c)
    pipeline, method = _pipeline(c, default)
    splits, validation = _evaluation_splits(frame, c, groups, "holdout")
    train, test = splits[0]
    pipeline.fit(x[train], y[train])
    prediction = pipeline.predict(x[test])
    metadata = {
        "model_method": method,
        "features": c["features"],
        "target": c["target"],
        "seed": _seed(c),
        "train_positions": train.tolist(),
        "test_positions": test.tolist(),
        "train_ids": [ids[i] for i in train],
        "test_ids": [ids[i] for i in test],
        "scaler_mean": pipeline.named_steps["scale"].mean_.tolist(),
        "validation_split": validation,
        **_time_metadata(frame, c, train, test),
    }
    fingerprints = _row_fingerprints(frame, c["features"], c["target"], c.get("id_column"))
    metadata.update(
        id_column=c.get("id_column"),
        train_fingerprints=[fingerprints[i] for i in train],
        test_fingerprints=[fingerprints[i] for i in test],
        model_summary=_summary(pipeline, c["features"]),
    )
    manifest, artifacts = _save(pipeline, c, metadata, x[test])
    output = {
        **manifest,
        "evaluation": "holdout",
        "metrics": _metrics(y[test], prediction),
        "parameters": _json(c),
        "preprocessing": "polynomial features if configured, then train-fitted standard scaling",
    }
    result = pd.DataFrame(
        {
            "row_position": test,
            "sample_id": [ids[i] for i in test],
            "y_true": y[test],
            "y_pred": prediction,
            "residual": y[test] - prediction,
            "split": "test",
        }
    )
    warnings = (
        [
            "Row-random holdout assumes independent rows. "
            "Supply group_column for repeated specimen measurements."
        ]
        if groups is None and validation == "random"
        else []
    )
    if output["metrics"]["r2"] is None:
        warnings.append("R2 is undefined because the heldout target is constant.")
    if validation == "chronological_split":
        warnings.append(
            "Chronological holdout scores later observed rows; it does not establish forecasting validity."
        )
        output["time_column"] = c["time_column"]
    return _add_diagnostics(
        NodeResult(result, output, artifacts, warnings),
        c,
        method=method,
        train_x=x[train],
        train_y=y[train],
        test_x=x[test],
    )


def _manifest(c, data):
    path = c.get("model_path") or data.get("model_path")
    manifest_path = c.get("manifest_path") or data.get("manifest_path")
    if path and Path(path).suffix == ".json":
        manifest_path, path = path, None
    manifest = dict(data)
    if manifest_path:
        p = Path(manifest_path).expanduser().resolve()
        manifest = json.loads(p.read_text(encoding="utf-8"))
        if manifest.get("format") != "materials-quality-skops-v1":
            raise ValueError("unsupported model manifest format")
        path = path or manifest.get("model_path")
    if not path:
        raise ValueError("provide a model_path or model manifest")
    # A bare path uses its adjacent generated manifest; callers may alternatively
    # supply declared feature order explicitly, but never guess it from a table.
    if not manifest.get("features") and not c.get("features"):
        adjacent = Path(path).parent / "model-manifest.json"
        if adjacent.is_file():
            candidate = json.loads(adjacent.read_text(encoding="utf-8"))
            if Path(candidate.get("model_path", "")).resolve() == Path(path).resolve():
                manifest = candidate
    return path, manifest


def has_saved_model(c, data):
    upstream = data if isinstance(data, dict) else {}
    return any(c.get(key) or upstream.get(key) for key in ("model_path", "manifest_path"))


def predict_saved(table, c, data):
    path, manifest = _manifest(c, data)
    model = _load(path, manifest.get("sha256"))
    features = c.get("features") or manifest.get("features")
    if not features:
        raise ValueError("model manifest or config must declare feature order")
    if c.get("features") and manifest.get("features") and c["features"] != manifest["features"]:
        raise ValueError("feature order differs from fitted manifest")
    frame = require_table(table, features)
    x = numeric_matrix(frame, features)
    pred = model.predict(x)
    if not np.isfinite(pred).all():
        raise ValueError("model predictions are nonfinite")
    out = frame.copy()
    out["row_position"], out["y_pred"] = np.arange(len(frame)), pred
    return NodeResult(
        out,
        {
            "method": "saved_model_prediction",
            "features": features,
            "model_path": str(Path(path).resolve()),
            "n": len(frame),
            "model_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        },
    )


def evaluate_model(table, c, data):
    if "y_true" in data and "y_pred" in data:
        y, p = np.asarray(data["y_true"], float), np.asarray(data["y_pred"], float)
        return _add_diagnostics(
            NodeResult(
                pd.DataFrame({"y_true": y, "y_pred": p}),
                {
                    "evaluation": "provided_predictions",
                    "metrics": _metrics(y, p),
                    "provenance": data.get("provenance", "Caller supplied; independence not verified"),
                },
            ),
            c,
        )
    if table is not None and c.get("y_true") and c.get("y_pred"):
        values = numeric_matrix(table, [c["y_true"], c["y_pred"]])
        return evaluate_model(None, c, {"y_true": values[:, 0], "y_pred": values[:, 1]})
    if has_saved_model(c, data):
        _, manifest = _manifest(c, data)
        target = c.get("target") or manifest.get("target")
        frame = require_table(table, [target])
        prediction = predict_saved(frame, c, data)
        y = numeric_matrix(frame, [target])[:, 0]
        prediction.table["y_true"] = y
        fingerprints = _row_fingerprints(
            frame, manifest.get("features", c.get("features")), target, manifest.get("id_column")
        )
        verified_holdout = fingerprints == manifest.get("test_fingerprints") and not set(
            fingerprints
        ).intersection(manifest.get("train_fingerprints", []))
        return _add_diagnostics(
            NodeResult(
                prediction.table,
                {
                    **prediction.data,
                    "evaluation": "manifest_holdout" if verified_holdout else "provided_model_dataset",
                    "metrics": _metrics(y, prediction.table.y_pred.to_numpy()),
                    "provenance": "Exact fingerprint match to test rows; disjoint from training rows."
                    if verified_holdout
                    else "Caller-provided evaluation dataset; disjointness from training is not assumed.",
                },
                warnings=[]
                if verified_holdout
                else [
                    "Use holdout/CV metadata to establish independence; this dataset may overlap training."
                ],
            ),
            c,
        )
    c, evaluation = _evaluation_config(c)
    if evaluation == "holdout":
        model_c = {**c, "method": c.get("model_method", "linear")}
        return fit_model(table, model_c)
    if evaluation != "cv":
        raise ValueError("evaluation method must be holdout or cv")
    frame, x, y, ids, groups = _dataset(table, c)
    pipeline, method = _pipeline(c, "linear")
    splits, validation = _evaluation_splits(frame, c, groups, "cv")
    predictions, fold_ids, details = np.full(len(y), np.nan), np.full(len(y), -1, int), []
    lower, upper, interval_details = np.full(len(y), np.nan), np.full(len(y), np.nan), []
    interval = _option(c, "linear_trend_ci")
    for fold, (train, test) in enumerate(splits):
        fitted = clone(pipeline).fit(x[train], y[train])
        predicted = fitted.predict(x[test])
        predictions[test], fold_ids[test] = predicted, fold
        if interval:
            lower[test], upper[test], ci = _linear_ci(c, method, x[train], y[train], x[test])
            interval_details.append({"fold": fold, **ci})
        details.append(
            {
                "fold": fold,
                "train_positions": train.tolist(),
                "test_positions": test.tolist(),
                "train_ids": [ids[i] for i in train],
                "test_ids": [ids[i] for i in test],
                "scaler_mean": fitted.named_steps["scale"].mean_.tolist(),
                "metrics": _metrics(y[test], predicted),
                **_time_metadata(frame, c, train, test),
            }
        )
    selected = np.flatnonzero(fold_ids >= 0)
    if validation == "blocked_cv":
        times = _time_values(frame, c)
        selected = selected[np.argsort(times[selected], kind="stable")]
    out = pd.DataFrame(
        {
            "row_position": selected,
            "sample_id": [ids[i] for i in selected],
            "y_true": y[selected],
            "y_pred": predictions[selected],
            "residual": y[selected] - predictions[selected],
            "fold": fold_ids[selected],
            "split": "out_of_fold",
        }
    )
    result = NodeResult(
        out,
        {
            "evaluation": "cross_validation",
            "model_method": method,
            "seed": _seed(c),
            "metrics": _metrics(y[selected], predictions[selected]),
            "folds": details,
            "preprocessing": "Each fold fits its own pipeline on that fold's training rows.",
            "validation_split": validation,
            "warmup_positions": np.flatnonzero(fold_ids < 0).tolist(),
        },
        warnings=[]
        if groups is not None or validation == "blocked_cv"
        else ["Row-level CV assumes independent rows; group_column prevents specimen leakage."],
    )
    if validation == "blocked_cv":
        result.data["time_column"] = c["time_column"]
        result.warnings.append(
            "Walk-forward scores use only prior times for training; initial warmup rows are not evaluated. "
            "No forecast interval is implied."
        )
    _add_diagnostics(result, {**c, "linear_trend_ci": False})
    if interval:
        result.table["mean_ci_lower"], result.table["mean_ci_upper"] = lower[selected], upper[selected]
        result.data["linear_trend_ci"] = {
            "kind": "OLS mean response confidence interval",
            "predictive_interval": False,
            "fold_specific": True,
            "folds": interval_details,
        }
        result.warnings.append(
            "Each mean interval uses only its fold's training observations and training feature domain; "
            "it is not an individual prediction or forecasting interval."
        )
    return result
