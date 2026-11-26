"""Design-aware pipeline vs independent, explicitly calculated inference oracle."""

import json

import numpy as np
import pytest


@pytest.mark.parametrize("design", ["independent", "paired"])
def test_real_pipeline_matches_closed_form_on_unit_means(design):
    from materials_quality.evaluation.design import evaluate_trial, generate_trial

    trial = generate_trial(
        seed=821, n_per_group=8, technical_replicates=3, effect=2.0, variance="heterogeneous", design=design
    )
    result = evaluate_trial(trial)
    assert result["n_a"] == result["n_b"] == 8
    assert result["technical_rows"] == 48
    assert result["mean_difference"] == pytest.approx(result["oracle_mean_difference"], abs=1e-12)
    assert result["p_raw"] == pytest.approx(result["oracle_p_raw"], abs=1e-12)
    assert result["ci_low"] == pytest.approx(result["oracle_ci_low"], abs=1e-12)
    assert result["ci_high"] == pytest.approx(result["oracle_ci_high"], abs=1e-12)
    assert result["oracle_agreement"] is True
    assert result["ci_status"] == "estimated"


def test_technical_repeats_do_not_inflate_pipeline_n_but_naive_n_is_visible():
    from materials_quality.evaluation.design import evaluate_trial, generate_trial

    trial = generate_trial(seed=52, n_per_group=4, technical_replicates=3, effect=0.0, variance="balanced")
    result = evaluate_trial(trial)
    assert result["n_a"] == 4
    assert result["naive_n_a"] == 12
    assert result["naive_ci_width"] != pytest.approx(result["ci_width"])
    # A fixed trial is not used to assert universal narrowing, Type I or coverage.


def test_iid_simulation_manifest_has_unique_trial_seeds_and_prespecified_strata():
    from materials_quality.evaluation.design import build_trials

    trials = build_trials(repetitions=2)
    assert len(trials) == 32
    assert len({t.seed for t in trials}) == len(trials)
    assert len({t.trial_id for t in trials}) == len(trials)
    assert {t.truth["true_difference"] for t in trials} == {0.0, 2.0}
    assert {t.truth["n_per_group"] for t in trials} == {4, 8}
    assert {t.truth["technical_replicates"] for t in trials} == {1, 3}
    assert trials[0].table.equals(build_trials(repetitions=2)[0].table)


def test_mc_metrics_have_trial_denominators_and_do_not_call_power_type_one():
    from materials_quality.evaluation.design import build_trials, evaluate_trials, summarize_design

    rows = evaluate_trials(build_trials(repetitions=2))
    summary = summarize_design(rows)
    assert summary["independent_trials"] == 32
    assert summary["oracle_mismatches"] == 0
    assert len(summary["strata"]) == 16
    for stratum in summary["strata"]:
        assert stratum["trials"] == 2
        assert stratum["coverage"]["denominator"] == 2
        assert 0 <= stratum["coverage"]["wilson_low"] <= stratum["coverage"]["wilson_high"] <= 1
        assert np.isfinite(stratum["coverage"]["monte_carlo_se"])
        if stratum["true_difference"] == 0:
            assert stratum["rejection_interpretation"] == "type_I_error"
        else:
            assert stratum["rejection_interpretation"] == "power_at_declared_shift"


@pytest.mark.parametrize(
    "n,policy,estimated", [(1, "model_based", False), (2, "descriptive", False), (2, "model_based", True)]
)
def test_small_sample_outcomes_follow_explicit_policy(n, policy, estimated):
    from materials_quality.evaluation.design import generate_trial
    from materials_quality.science.contrast_study import contrast_study

    trial = generate_trial(seed=71, n_per_group=n, technical_replicates=3, effect=2.0, variance="balanced")
    actual = contrast_study(trial.table, config={**trial.config, "small_sample_policy": policy}).data
    row = actual["pairwise"][0]
    assert (row["mean_difference_ci_low"] is not None) == estimated
    assert row["ci_status"] == (
        "estimated_small_n_model_assumptions" if estimated else "not_estimated_small_n_policy"
    )


def test_design_artifacts_write_fresh_directory_with_source_and_rng_metadata(tmp_path):
    from materials_quality.evaluation.design import build_trials, run_design_evaluation

    output = tmp_path / "design-results"
    summary = run_design_evaluation(output, trials=build_trials(repetitions=1))
    assert summary["independent_trials"] == 16
    assert summary["oracle_mismatches"] == 0
    metadata = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert metadata["source_sha256"]
    assert "independent" in metadata["rng_policy"]
    assert (output / "per_trial.csv").is_file()
    assert (output / "per_trial.json").is_file()
    with pytest.raises(FileExistsError):
        run_design_evaluation(output, trials=[])
