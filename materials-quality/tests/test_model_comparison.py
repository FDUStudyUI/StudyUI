"""Competing estimators share identical heldout rows and preprocessing boundaries."""

import json

import numpy as np
import pandas as pd
import pytest


def compare(table, config):
    from materials_quality.science.model_comparison import compare_models

    return compare_models(table, config)


@pytest.mark.parametrize(
    "mode,method", [("random", "holdout"), ("chronological_split", "holdout"), ("blocked_cv", "cv")]
)
def test_models_use_identical_splits_and_return_native_score_table(mode, method):
    frame = pd.DataFrame({"time": np.arange(40), "x": np.arange(40), "y": np.arange(40) * 2 + 3}).sample(
        frac=1, random_state=3
    )
    result = compare(
        frame,
        {
            "models": ["linear", "ridge", "random_forest"],
            "features": ["x"],
            "target": "y",
            "time_column": "time",
            "validation_split": mode,
            "method": method,
            "folds": 3,
            "n_estimators": 10,
        },
    )
    assert result.table.model.tolist() == ["linear", "ridge", "random_forest"]
    assert {"mae", "rmse", "r2", "n"} <= set(result.table)
    assert result.artifacts == []
    splits = result.data["splits"]
    for model in result.data["model_results"]:
        assert model["splits"] == splits
        assert model["metrics"]["n"] == result.table.iloc[0]["n"]
    if mode != "random":
        for split in splits:
            assert (
                frame.iloc[split["train_positions"]].time.max()
                < frame.iloc[split["test_positions"]].time.min()
            )
    json.dumps(result.data, allow_nan=False)


@pytest.mark.parametrize("models", [[], ["linear", "linear"], ["linear", "unknown"], "linear"])
def test_invalid_model_selection_is_rejected(models):
    with pytest.raises(ValueError, match="models"):
        compare(
            pd.DataFrame({"x": range(20), "y": range(20)}),
            {"models": models, "features": ["x"], "target": "y"},
        )


def test_comparison_temporal_group_conflict_is_explicit():
    frame = pd.DataFrame({"time": range(20), "x": range(20), "y": range(20), "unit": ["A", "B"] * 10})
    with pytest.raises(ValueError, match="group|unit"):
        compare(
            frame,
            {
                "models": ["linear", "ridge"],
                "features": ["x"],
                "target": "y",
                "time_column": "time",
                "group_column": "unit",
                "validation_split": "chronological_split",
            },
        )


def test_native_component_uses_forms_and_runs_a_real_graph():
    from lfx.graph import Graph

    from components.materials_batch.model_comparison import MaterialModelComparison
    from examples.demo_source import MaterialDemoTable

    source = MaterialDemoTable().set(
        records_json=json.dumps([{"time": i, "x": i, "y": 2 * i + 3} for i in range(24)])
    )
    node = MaterialModelComparison().set(
        input_table=source.build_table,
        models=["linear", "ridge"],
        features=["x"],
        target="y",
        method="cv",
        folds=3,
        validation_split="blocked_cv",
        time_column="time",
    )
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert "config_json" not in template
    assert {"linear", "ridge", "random_forest"} <= set(template["models"]["options"])
    assert template["models"]["value"] == ["linear", "ridge"]
    assert template["time_column"]["show"] and template["folds"]["show"]
    assert "time" in template["time_column"]["options"]
    graph = Graph.from_payload(Graph(start=source, end=node).dump(name="Native model comparison"))
    for step in graph.start():
        assert not hasattr(step, "valid") or step.valid, step
    result = graph.get_vertex(node.get_id()).results
    assert result["scores"].model.tolist() == ["linear", "ridge"]
    assert result["report"].data["data"]["validation_split"] == "blocked_cv"
    assert len(result["report"].data["data"]["splits"]) == 3


def test_native_component_preserves_explicit_empty_model_selection():
    from lfx.schema import DataFrame

    from components.materials_batch.model_comparison import MaterialModelComparison

    node = MaterialModelComparison().set(input_table=DataFrame({"x": range(20), "y": range(20)}), models=[])
    assert node._parameters["models"] == []
    with pytest.raises(ValueError, match="models"):
        node.build_scores()


def test_native_score_output_preserves_target_metric_units():
    from lfx.schema import DataFrame

    from components.materials_batch.model_comparison import MaterialModelComparison

    frame = DataFrame({"x": range(20), "y": range(20)})
    frame.attrs["units"] = {"y": "MPa"}
    node = MaterialModelComparison().set(input_table=frame, models=["linear", "ridge"])
    assert node.build_scores().attrs["units"] == {"mae": "MPa", "rmse": "MPa", "r2": "dimensionless"}


def test_native_science_schemas_expose_temporal_and_comparison_controls():
    from materials_quality.science.catalog import component_class
    from materials_quality.science.ui_schema import fields_for, form_config

    fields = {field["path"]: field for field in fields_for("stats.evaluate")}
    assert set(fields["validation_split"]["choices"]) == {"random", "chronological_split", "blocked_cv"}
    assert fields["models"]["kind"] == "list"
    node = component_class("stats.evaluate")().set(
        ui_mode="form",
        cfg_evaluation_task="train",
        cfg_features=["x"],
        cfg_target="y",
        cfg_method="cv",
        cfg_validation_split="blocked_cv",
        cfg_time_column="time",
        cfg_models=["linear", "ridge"],
    )
    config = form_config(node, "stats.evaluate")
    assert config["validation_split"] == "blocked_cv" and config["models"] == ["linear", "ridge"]
