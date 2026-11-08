"""Boundary matrix: wrong-typed / degenerate inputs must fail as clean ValueErrors.

Each case previously escaped as an unexpected exception type (TypeError,
AttributeError, ZeroDivisionError, OverflowError or a math-domain ValueError
with no actionable message), which surfaces as a node traceback instead of a
diagnosable input error.
"""

import math

import pandas as pd
import pytest

from materials_quality.evaluation.design import (
    binomial_mc,
    closed_form_interval,
    generate_trial,
)
from materials_quality.science import literature, method_cards, result_evidence
from materials_quality.science.contracts import artifact_path
from materials_quality.skills import model
from materials_quality.skills.planning import make_plan


def test_search_rejects_non_object_local_records():
    for records in ([None], ["text"], [5], [[]], [{"title": "ok"}, None]):
        with pytest.raises(ValueError, match="record"):
            literature.search(data={"records": records}, config={"provider": "local", "query": "zno"})


def test_metadata_rejects_non_string_doi_config():
    for doi in (1, 1.5, True, [], {}, b"10.1234/a"):
        with pytest.raises(ValueError, match="DOI"):
            literature.metadata(config={"provider": "local", "doi": doi})


def test_artifact_path_rejects_non_path_output_directory():
    for output_dir in (1, True, [], {"a": 1}):
        with pytest.raises(ValueError, match="output_dir"):
            artifact_path({"output_dir": output_dir}, "literature-sources.json")


def test_recommend_methods_rejects_non_text_goal():
    for goal in ([], {}, 5, True):
        with pytest.raises(ValueError, match="goal"):
            method_cards.recommend_methods(
                config={
                    "method_ids": ["snv"],
                    "signal_type": "nir_absorbance",
                    "x_unit": "nm",
                    "y_unit": "absorbance",
                    "goal": goal,
                    "allow_intensity_loss": True,
                    "nonzero_variance": True,
                }
            )


def test_result_evidence_rejects_non_mapping_units_attribute():
    for units in ([], "MPa", None, 5):
        frame = pd.DataFrame({"x": [1.0]})
        frame.attrs["units"] = units
        with pytest.raises(ValueError, match="units"):
            result_evidence.result_evidence(frame, config={"columns": ["x"]})


def test_mapping_converter_rejects_non_object_value():
    from materials_quality.science.ui_schema import _convert

    spec = {"kind": "dict", "path": "lexicon", "label": "属性 → 术语列表", "converter": "list_mapping"}
    for value in ("not-an-object", "[]", " ", [1], 5, True):
        with pytest.raises(ValueError, match="映射"):
            _convert(value, spec)


def test_closed_form_rejects_degenerate_and_nonfinite_variance():
    with pytest.raises(ValueError, match="variance|degenerate"):
        closed_form_interval([1.0, 1.0], [1.0, 1.0])
    with pytest.raises(ValueError, match="finite"):
        closed_form_interval([math.inf, 1.0], [1.0, 2.0])
    with pytest.raises(ValueError, match="finite"):
        closed_form_interval([math.nan, 1.0], [1.0, 2.0])


def test_generate_trial_rejects_unhashable_or_nonfinite_inputs():
    for variance in ([], {}):
        with pytest.raises(ValueError, match="variance"):
            generate_trial(seed=1, n_per_group=2, technical_replicates=1, effect=0.0, variance=variance)
    for design in ([], {}):
        with pytest.raises(ValueError, match="design"):
            generate_trial(
                seed=1, n_per_group=2, technical_replicates=1, effect=0.0, variance="balanced", design=design
            )
    for effect in (None, "1", [1]):
        with pytest.raises(ValueError, match="effect"):
            generate_trial(seed=1, n_per_group=2, technical_replicates=1, effect=effect, variance="balanced")


def test_binomial_mc_rejects_invalid_counts():
    for successes, denominator in ((5, 3), (-1, 3), (1, "2"), (1, 2.0), (True, 2), (1, True)):
        with pytest.raises(ValueError, match="successes|denominator"):
            binomial_mc(successes, denominator)


def test_suggest_plan_rejects_wrong_typed_controls_before_network():
    table = pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]})
    with pytest.raises(ValueError, match="base|模型|URL"):
        model.suggest_plan(table, "compare", base_url=5, model="m")
    with pytest.raises(ValueError, match="task|unknown"):
        model.suggest_plan(table, "compare", base_url="http://127.0.0.1:1", model="m", task=[])


def test_make_plan_still_rejects_non_object_parameters():
    table = pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]})
    with pytest.raises(ValueError, match="parameters"):
        make_plan(table, parameters=[{"x_unit": "nm"}])
