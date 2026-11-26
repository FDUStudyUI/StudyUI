"""Sprint 4 tests: decoupled 3-dimension real-instrument evaluation and studyui CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from materials_quality.cli import main as cli_main
from materials_quality.cli import run_doctor
from materials_quality.evaluation import (
    build_decoupled_summary,
    evaluate_negative_boundaries,
    export_expert_review_sheet,
    merge_expert_review_scores,
    render_evaluation_markdown,
    run_materials_evaluation_suite,
)
from materials_quality.material_examples import examples


def test_negative_boundary_cases_all_blocked_by_runtime_guards() -> None:
    """All 6 out-of-scope / physically invalid negative cases must be blocked by GUARD."""
    neg = evaluate_negative_boundaries()
    assert neg["total"] == 6
    assert neg["blocked"] == 6
    assert neg["block_rate"] == 1.0
    for item in neg["cases"]:
        assert item["blocked"] is True
        assert item["matched_expected_code"] is True


def test_decoupled_summary_separates_reproducibility_from_method_correctness() -> None:
    """Prove reproducibility and method correctness are strictly independent dimensions."""
    neg = evaluate_negative_boundaries()
    synthetic_runs = [
        {
            "id": "case_good",
            "task": "mechanics",
            "workflow_built": True,
            "execution": True,
            "repeatable": True,
            "method_contract": True,
            "numerical_reference": {"passed": True},
        },
        {
            # Reproducible byte-for-byte, yet methodologically wrong
            "id": "case_repeatable_but_wrong_method",
            "task": "spectra",
            "workflow_built": True,
            "execution": True,
            "repeatable": True,
            "method_contract": False,
            "numerical_reference": {"passed": False},
        },
        {
            # Method contract right, yet failed to reproduce consistently
            "id": "case_right_method_not_repeatable",
            "task": "xrd",
            "workflow_built": True,
            "execution": True,
            "repeatable": False,
            "method_contract": True,
            "numerical_reference": {"passed": True},
        },
        {
            # Build failed
            "id": "case_build_failed",
            "task": "mechanics",
            "workflow_built": False,
            "execution": False,
            "repeatable": False,
            "method_contract": False,
            "error": "KeyError: missing column mapping for strain",
        },
    ]

    # Evaluation lock must reject non-off evolution modes
    with pytest.raises(ValueError, match="evolution_mode must be 'off'"):
        build_decoupled_summary(synthetic_runs, neg, mode="synthetic", repeats=3, evolution_mode="manual")

    report = build_decoupled_summary(synthetic_runs, neg, mode="synthetic", repeats=3, evolution_mode="off")
    assert report["workflow_build"]["total"] == 4
    assert report["workflow_build"]["built_valid"] == 3
    assert report["workflow_build"]["build_rate"] == 0.75
    assert report["workflow_build"]["failure_breakdown"]["column_mapping"] == 1

    # Reproducibility: 2 / 3 executed runs are repeatable
    assert report["reproducibility"]["executed"] == 3
    assert report["reproducibility"]["repeatable"] == 2
    assert report["reproducibility"]["reproducibility_rate"] == pytest.approx(2 / 3, abs=1e-3)

    # Method correctness: 2 / 3 built runs pass method contract, 6 / 6 negative cases blocked
    assert report["method_correctness"]["method_contract_passed"] == 2
    assert report["method_correctness"]["negative_boundary_blocked"] == 6

    # Decoupling diagnostics explicitly expose both asymmetric failure modes
    assert report["decoupling_diagnostics"]["reproducible_but_method_wrong"] == 1
    assert report["decoupling_diagnostics"]["method_right_but_not_repeatable"] == 1

    md = render_evaluation_markdown(report)
    assert "维度 A" in md and "维度 B" in md and "维度 C" in md
    assert "可重复但方法不合规案例数：`1`" in md


def test_real_instrument_suite_with_cold_replay_and_expert_review_merge(tmp_path: Path) -> None:
    """Run real-instrument suite (subset with 2 cold replays) + expert blind review sheet merge."""
    # Pick 1 mechanics + 1 spectra + 1 xrd real instrument case to keep CI fast while testing all 3 families
    by_task: dict[str, str] = {}
    for item in examples():
        task = item["protocol"]["task"]
        by_task.setdefault(task, item["id"])
    selected = list(by_task.values())
    assert len(selected) == 3

    report = run_materials_evaluation_suite(
        tmp_path / "eval_out",
        repeats=2,
        skip_replay=False,
        case_ids=selected,
    )
    assert report["governance_lock"]["evolution_mode"] == "off"
    assert report["workflow_build"]["built_valid"] == 3
    assert report["workflow_build"]["build_rate"] == 1.0
    assert report["reproducibility"]["executed"] == 3
    assert report["reproducibility"]["repeatable"] == 3
    assert report["reproducibility"]["numeric_reference_passed"] == 3
    assert report["method_correctness"]["method_contract_passed"] == 3
    assert report["method_correctness"]["negative_boundary_blocked"] == 6

    assert (tmp_path / "eval_out" / "evaluation_report.json").is_file()
    assert (tmp_path / "eval_out" / "evaluation_report.md").is_file()
    sheets = export_expert_review_sheet(report, tmp_path / "eval_out")
    assert Path(sheets["csv"]).is_file()
    assert Path(sheets["markdown"]).is_file()

    # Simulate materials expert filling in blind scores and merging back
    filled = [
        {
            "case_id": case_id,
            "method_selection_1_to_5": "5",
            "parameter_validity_1_to_5": "4.5",
            "limitation_rigor_1_to_5": "5",
            "reviewer_notes": "参数与边界声明规范",
        }
        for case_id in selected
    ]
    merged = merge_expert_review_scores(report, filled)
    er = merged["method_correctness"]["expert_review"]
    assert er["status"] == "collected"
    assert er["collected_count"] == 3
    assert er["averages"]["method_selection_1_to_5"] == 5.0
    assert er["averages"]["parameter_validity_1_to_5"] == 4.5


def test_studyui_cli_doctor_and_assets_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify studyui doctor --json (E01-E06) and assets summary --json CLI commands."""
    doc = run_doctor(runtime_dir=tmp_path)
    assert doc["healthy"] is True
    assert doc["error_count"] == 0
    codes = [c["code"] for c in doc["checks"]]
    assert codes == ["E01", "E02", "E03", "E04", "E05", "E06"]

    rc_doc = cli_main(["doctor", "--json", "--runtime-dir", str(tmp_path)])
    assert rc_doc == 0
    out_doc = json.loads(capsys.readouterr().out)
    assert out_doc["healthy"] is True

    rc_assets = cli_main(["assets", "summary", "--json"])
    assert rc_assets == 0
    out_assets = json.loads(capsys.readouterr().out)
    assert out_assets["error_count"] == 0
    assert out_assets["total_assets"] >= 100

    # CLI eval-suite (--skip-replay + --case-ids) and merge-review subcommand.
    eval_out = tmp_path / "cli_eval"
    first_id = examples()[0]["id"]
    rc_eval = cli_main(["eval-suite", "--output", str(eval_out), "--skip-replay", "--case-ids", first_id])
    assert rc_eval == 0
    capsys.readouterr()

    sheet_csv = eval_out / "expert_review_blind_sheet.csv"
    sheet_csv.write_text(
        "case_id,task_family,method_selection_1_to_5,p"
        "arameter_validity_1_to_5,limitation_rigor_1_t"
        "o_5,reviewer_notes\n"
        f"{first_id},mechanics,5,5,4,良好\n",
        encoding="utf-8",
    )
    rc_merge = cli_main(
        ["merge-review", "--report", str(eval_out / "evaluation_report.json"), "--scores", str(sheet_csv)]
    )
    assert rc_merge == 0
    merged_out = json.loads(capsys.readouterr().out)
    assert merged_out["status"] == "collected"
    assert merged_out["averages"]["method_selection_1_to_5"] == 5.0


def test_agent_scripted_evaluation_suite_and_adversarial_boundaries(tmp_path: Path) -> None:
    """Verify agent_scripted mode measures StudyUIAgent workflow build + adversarial guard blocking."""
    by_task: dict[str, str] = {}
    for item in examples():
        by_task.setdefault(item["protocol"]["task"], item["id"])
    selected = list(by_task.values())

    report = run_materials_evaluation_suite(
        tmp_path / "agent_eval",
        mode="agent_scripted",
        repeats=2,
        skip_replay=True,
        case_ids=selected,
    )
    assert report["mode"] == "agent_scripted_decoupled_suite"
    assert report["workflow_build"]["built_valid"] == 3
    assert report["workflow_build"]["build_rate"] == 1.0
    assert report["method_correctness"]["method_contract_passed"] == 3
    adv = report["method_correctness"]["adversarial_agent_boundaries"]
    assert adv["total"] == 6
    assert adv["blocked"] == 6
    assert adv["block_rate"] == 1.0
    xrd_case = next(c for c in adv["cases"] if c["id"] == "neg_xrd_no_reference_phase_id")
    assert xrd_case["blocked_by_agent_or_guard"] is True


def test_expanded_minimal_catalog_and_dynamic_method_contract() -> None:
    """
    Verify _minimal_catalog includes all 5 task families and _check_method_contract reads protocol
    dynamically.
    """
    from materials_quality.evaluation.benchmark_suite import _check_method_contract, _minimal_catalog

    cat = _minimal_catalog()["materials_analysis"]
    for node_name in (
        "BatteryCycles",
        "ScienceMaterialsThermal",
        "ScienceVizPerformance",
        "SciencePreprocessFilter",
        "SciencePreprocessMissing",
        "SciencePreprocessUnits",
        "SciencePreprocessNormalize",
    ):
        assert node_name in cat

    # Dynamic spectra contract (non-default prominence=42, baseline=linear)
    spectra_flow = {
        "data": {
            "nodes": [
                {
                    "data": {
                        "type": "ScienceMaterialsSpectra",
                        "node": {
                            "template": {
                                "cfg_x": {"value": "wavenumber"},
                                "cfg_y": {"value": "absorbance"},
                                "cfg_x_unit": {"value": "cm^-1"},
                                "cfg_y_unit": {"value": "a.u."},
                                "cfg_baseline_method": {"value": "linear"},
                                "cfg_prominence": {"value": 42},
                            }
                        },
                    }
                }
            ]
        }
    }
    spectra_item = {
        "protocol": {
            "task": "spectra",
            "x": "wavenumber",
            "y": "absorbance",
            "x_unit": "cm^-1",
            "y_unit": "a.u.",
            "baseline": "linear",
            "prominence": 42,
        }
    }
    assert _check_method_contract(spectra_flow, spectra_item) is True
    spectra_item_mismatch = {"protocol": {**spectra_item["protocol"], "prominence": 100}}
    assert _check_method_contract(spectra_flow, spectra_item_mismatch) is False

    # Tightened battery contract
    battery_flow = {
        "data": {
            "nodes": [
                {
                    "data": {
                        "type": "BatteryCycles",
                        "node": {
                            "template": {
                                "mode": {"value": "summary"},
                                "cycle_column": {"value": "cycle"},
                                "cell_column": {"value": "cell_id"},
                                "discharge_capacity_column": {"value": "q_dis"},
                                "charge_capacity_column": {"value": "q_chg"},
                                "capacity_unit": {"value": "mAh"},
                            }
                        },
                    }
                }
            ]
        }
    }
    battery_item = {
        "protocol": {
            "task": "battery",
            "mode": "summary",
            "x": "cycle",
            "y": "q_dis",
            "y_unit": "mAh",
            "cell_col": "cell_id",
            "charge_col": "q_chg",
        }
    }
    assert _check_method_contract(battery_flow, battery_item) is True
    battery_bad_unit = {"protocol": {**battery_item["protocol"], "y_unit": "Ah"}}
    assert _check_method_contract(battery_flow, battery_bad_unit) is False


def test_agent_scripted_raw_input_evaluation(tmp_path: Path) -> None:
    """Verify raw_input=True evaluates agent_scripted directly on raw .xlsx/.txt/.dat files."""
    by_task: dict[str, str] = {}
    for item in examples():
        by_task.setdefault(item["protocol"]["task"], item["id"])
    selected = list(by_task.values())

    out_dir = tmp_path / "raw_agent_eval"
    report = run_materials_evaluation_suite(
        out_dir,
        mode="agent_scripted",
        repeats=2,
        skip_replay=False,
        case_ids=selected,
        raw_input=True,
    )
    assert report["workflow_build"]["built_valid"] == 3
    assert report["workflow_build"]["build_rate"] == 1.0
    assert report["reproducibility"]["executed"] == 3
    assert report["reproducibility"]["repeatable"] == 3
    assert report["reproducibility"]["numeric_reference_passed"] == 3
    assert report["method_correctness"]["method_contract_passed"] == 3
    for run in report["positive_runs"]:
        assert run["raw_input"] is True
        assert not (out_dir / run["id"] / "prepared_measurement.csv").exists()
