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
    frame, x, y, ids, groups = _dataset(table, c)
    pipeline, method = _pipeline(c, default)
    train, test = _split(len(frame), c, groups)
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
        if groups is None
        else []
    )
    if output["metrics"]["r2"] is None:
        warnings.append("R2 is undefined because the heldout target is constant.")
    return NodeResult(result, output, artifacts, warnings)


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
        return NodeResult(
            pd.DataFrame({"y_true": y, "y_pred": p}),
            {
                "evaluation": "provided_predictions",
                "metrics": _metrics(y, p),
                "provenance": data.get("provenance", "Caller supplied; independence not verified"),
            },
        )
    if table is not None and c.get("y_true") and c.get("y_pred"):
        values = numeric_matrix(table, [c["y_true"], c["y_pred"]])
        return evaluate_model(None, {}, {"y_true": values[:, 0], "y_pred": values[:, 1]})
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
        return NodeResult(
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
            else ["Use holdout/CV metadata to establish independence; this dataset may overlap training."],
        )
    evaluation = c.get("method", "holdout")
    if evaluation == "holdout":
        model_c = {**c, "method": c.get("model_method", "linear")}
        return fit_model(table, model_c)
    if evaluation != "cv":
        raise ValueError("evaluation method must be holdout or cv")
    frame, x, y, ids, groups = _dataset(table, c)
    pipeline, method = _pipeline(c, "linear")
    folds = c.get("folds", 5)
    if type(folds) is not int or not 2 <= folds <= len(frame) // 2:
        raise ValueError("folds must allow at least two test observations in every fold")
    if groups is None:
        splitter = KFold(n_splits=folds, shuffle=True, random_state=_seed(c))
    else:
        if len(np.unique(groups)) < folds:
            raise ValueError("fold count exceeds number of independent groups")
        splitter = GroupKFold(n_splits=folds)
    predictions, fold_ids, details = np.empty(len(y)), np.empty(len(y), int), []
    for fold, (train, test) in enumerate(splitter.split(x, y, groups)):
        fitted = clone(pipeline).fit(x[train], y[train])
        predicted = fitted.predict(x[test])
        predictions[test], fold_ids[test] = predicted, fold
        details.append(
            {
                "fold": fold,
                "train_positions": train.tolist(),
                "test_positions": test.tolist(),
                "train_ids": [ids[i] for i in train],
                "test_ids": [ids[i] for i in test],
                "scaler_mean": fitted.named_steps["scale"].mean_.tolist(),
                "metrics": _metrics(y[test], predicted),
            }
        )
    out = pd.DataFrame(
        {
            "row_position": np.arange(len(y)),
            "sample_id": ids,
            "y_true": y,
            "y_pred": predictions,
            "residual": y - predictions,
            "fold": fold_ids,
            "split": "out_of_fold",
        }
    )
    return NodeResult(
        out,
        {
            "evaluation": "cross_validation",
            "model_method": method,
            "seed": _seed(c),
            "metrics": _metrics(y, predictions),
            "folds": details,
            "preprocessing": "Each fold fits its own pipeline on that fold's training rows.",
        },
        warnings=[]
        if groups is not None
        else ["Row-level CV assumes independent rows; group_column prevents specimen leakage."],
    )
