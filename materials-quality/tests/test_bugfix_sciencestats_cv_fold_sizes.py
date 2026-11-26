import numpy as np
import pandas as pd
import pytest

from materials_quality.science import stats_models
from materials_quality.science.model_comparison import compare_models


def singleton_group_frame():
    frame = pd.DataFrame({"x": np.arange(12, dtype=float), "y": 2.0 * np.arange(12) + 1.0})
    frame["specimen"] = ["A"] * 11 + ["B"]
    return frame


def test_grouped_cv_with_singleton_unit_names_the_undersized_fold():
    config = {
        "features": ["x"],
        "target": "y",
        "group_column": "specimen",
        "method": "cv",
        "folds": 2,
    }
    with pytest.raises(ValueError, match="fold"):
        stats_models.evaluate_model(singleton_group_frame(), config, {})


def test_grouped_cv_with_singleton_unit_fails_clearly_for_model_comparison():
    config = {
        "features": ["x"],
        "target": "y",
        "group_column": "specimen",
        "models": ["linear"],
        "method": "cv",
        "folds": 2,
    }
    with pytest.raises(ValueError, match="fold"):
        compare_models(singleton_group_frame(), config)
