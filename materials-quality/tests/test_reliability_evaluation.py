"""Independent analytic oracle; no production detector defines expected truth."""

import json
import math

import numpy as np
import pytest


def test_generator_has_exact_analytic_truth_and_reproducible_inputs():
    from materials_quality.evaluation.spectral import generate_case

    first = generate_case("isolated", split="dev", cell=0, replicate=0)
    second = generate_case("isolated", split="dev", cell=0, replicate=0)
    assert first.truth == second.truth
    assert first.table.equals(second.table)
    peak = first.truth[0]["peaks"][0]
    assert peak["fwhm_nm"] == pytest.approx(2 * math.sqrt(2 * math.log(2)) * peak["sigma_nm"])
    assert first.truth[0]["targets_nm"]["redmost"] == peak["center_nm"]


def test_frozen_pool_separates_parameter_cells_seeds_and_mechanisms():
    from materials_quality.evaluation.spectral import build_pool

    cases = build_pool()
    assert 200 <= len(cases) <= 500
    dev = [c for c in cases if c.split == "dev"]
    holdout = [c for c in cases if c.split == "holdout"]
    assert {c.cell_key for c in dev}.isdisjoint(c.cell_key for c in holdout)
    assert {c.seed for c in dev}.isdisjoint(c.seed for c in holdout)
    assert {c.scenario for c in holdout} - {c.scenario for c in dev}
    assert len({c.case_id for c in cases}) == len(cases)


def test_scorer_detects_wrong_candidates_and_does_not_drop_missing_curves():
    from materials_quality.evaluation.spectral import generate_case, score_case

    case = generate_case("competing", split="dev", cell=0, replicate=0)
    good = {
        "curve_summary": [{"curve_id": "curve-01", "status": "completed", "window_candidate_nm": 730}],
        "features": [
            {"curve_id": "curve-01", "peak_position": 730},
            {"curve_id": "curve-01", "peak_position": 790},
        ],
    }
    score = score_case(case, good, selection="highest_prominence")
    assert score[0]["candidate_correct"] is True
    assert score[0]["matched_peaks"] == 2
    assert score_case(case, good, selection="redmost")[0]["candidate_correct"] is False
    missing = score_case(case, {"curve_summary": [], "features": []}, selection="redmost")
    assert len(missing) == 1
    assert missing[0]["candidate_correct"] is False
    assert missing[0]["analysis_status"] == "missing_summary"


def test_noise_only_truth_scores_false_positive_and_correct_absence_separately():
    from materials_quality.evaluation.spectral import generate_case, score_case

    case = generate_case("noise_only", split="dev", cell=0, replicate=0)
    assert case.truth[0]["peaks"] == []
    absent = {
        "curve_summary": [{"curve_id": "curve-01", "status": "completed", "window_candidate_nm": None}],
        "features": [],
    }
    score = score_case(case, absent, selection="redmost")[0]
    assert score["candidate_correct"] is True
    assert score["target_present"] is False
    assert score["true_peak_count"] == 0
    absent["curve_summary"][0]["window_candidate_nm"] = 760.0
    assert score_case(case, absent, selection="redmost")[0]["candidate_correct"] is False


def test_overlapping_components_are_not_scored_as_identifiable_peak_truth():
    from materials_quality.evaluation.spectral import generate_case, score_case

    case = generate_case("overlapping_shoulder", split="holdout", cell=0, replicate=0)
    score = score_case(case, {"curve_summary": [], "features": []}, selection="redmost")[0]
    assert score["candidate_correct"] is None
    assert score["matched_peaks"] is None
    assert "withheld" in score["truth_note"]


def test_noiseless_reference_stop_is_distinguished_from_rejection_of_applicable_method():
    from materials_quality.evaluation.spectral import evaluate_cases, generate_case, summarize

    case = generate_case("isolated", split="dev", cell=0, replicate=0)
    rows = evaluate_cases([case], strategies=("noise_reference",), selections=("redmost",))
    assert rows[0]["strategy_applicability"] == "no_stochastic_reference_noise"
    assert rows[0]["valid_input_rejected"] is True
    assert rows[0]["correct_stop"] is True
    assert rows[0]["unexpected_rejection"] is False
    # Preserve the numerical-candidate failure instead of silently dropping it.
    assert rows[0]["candidate_correct"] is False
    total = summarize(rows)["overall"]
    assert total["valid_input_rejections"] == 1
    assert total["unexpected_rejections"] == 0


def test_invalid_duplicates_rejected_but_long_table_ids_are_legal():
    from materials_quality.evaluation.spectral import evaluate_cases, generate_case

    cases = [
        generate_case(s, split="dev", cell=0, replicate=0)
        for s in ("duplicate_coordinates", "malformed_unit", "legal_repeats")
    ]
    records = evaluate_cases(cases, strategies=("absolute",), selections=("redmost",))
    invalid = [r for r in records if r["scenario"] != "legal_repeats"]
    assert all(r["rejection_correct"] is True for r in invalid)
    legal = [r for r in records if r["scenario"] == "legal_repeats"]
    assert len(legal) == 2
    assert all(r["analysis_status"] == "completed" for r in legal)
    assert all(r["candidate_correct"] is True for r in legal)


def test_controlled_analytic_subset_passes_frozen_absolute_acceptance():
    from materials_quality.evaluation.spectral import evaluate_cases, generate_case

    cases = [
        generate_case(s, split="dev", cell=0, replicate=0)
        for s in ("isolated", "competing", "external_interference", "unit_um", "uneven_grid")
    ]
    rows = evaluate_cases(cases, strategies=("absolute",))
    assert len(rows) == 10
    assert all(r["candidate_correct"] is True for r in rows)
    assert all(r["matched_peaks"] == r["true_peak_count"] for r in rows)
    assert all(r["unmatched_detected_peaks"] == 0 for r in rows)
    assert all(r["peak_position_mae_nm"] <= r["tolerance_nm"] for r in rows)


def test_summary_retains_denominators_and_does_not_invent_iid_intervals():
    from materials_quality.evaluation.spectral import evaluate_cases, generate_case, summarize

    cases = [
        generate_case(s, split="dev", cell=0, replicate=0)
        for s in ("isolated", "duplicate_coordinates", "legal_repeats")
    ]
    result = summarize(evaluate_cases(cases, strategies=("absolute",), selections=("redmost",)))
    total = result["overall"]
    assert total["task_runs"] == 3
    assert total["curve_runs"] == 4
    assert total["candidate_scored_curves"] == 3
    assert total["rejection_scored_curves"] == 1
    assert total["candidate_correct_curves"] == 3
    assert total["target_present_curves"] == 3
    assert total["target_absent_curves"] == 0
    assert all("cell_key" in row for row in result["strata"])
    assert result["uncertainty"]["interval"] is None
    assert "not IID" in result["uncertainty"]["reason"]


def test_artifact_run_is_readable_reproducible_and_never_overwrites(tmp_path):
    from materials_quality.evaluation.spectral import generate_case, run_evaluation

    cases = [generate_case("isolated", split="holdout", cell=0, replicate=0)]
    output = tmp_path / "results"
    result = run_evaluation(output, cases=cases, strategies=("absolute",), selections=("redmost",))
    assert result["overall"]["candidate_correct_curves"] == 1
    metadata = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert metadata["truth_scope"] == "analytic spectral candidates; no physical mode identity"
    assert metadata["seed_split_policy"]
    assert metadata["config_sha256"] and metadata["source_sha256"]
    assert (output / "per_case.csv").is_file()
    rows = json.loads((output / "per_case.json").read_text(encoding="utf-8"))
    assert len(rows) == 1 and np.isfinite(rows[0]["elapsed_seconds"])
    with pytest.raises(FileExistsError):
        run_evaluation(output, cases=cases)
