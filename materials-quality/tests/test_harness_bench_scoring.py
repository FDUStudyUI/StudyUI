"""Deterministic scoring and prompt rendering for the harness benchmark."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_harnesses.py"
spec = importlib.util.spec_from_file_location("evaluate_harnesses", SCRIPT)
bench = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["evaluate_harnesses"] = bench
spec.loader.exec_module(bench)


def test_extract_answer_uses_last_json_object():
    text = 'work {"intermediate": 1} then ```json\n{"final": 2}\n``` trailing text'
    assert bench.extract_answer(text) == {"final": 2}


def test_numeric_checks_use_declared_tolerance_and_integer_types():
    number = {"type": "number", "key": "x", "expected": 10.0, "rel": 0.01}
    assert bench.run_check(number, {"x": 10.05}) == (True, "")
    assert bench.run_check(number, {"x": 10.2})[0] is False
    integer = {"type": "integer", "key": "n", "expected": 3}
    assert bench.run_check(integer, {"n": 3}) == (True, "")
    assert bench.run_check(integer, {"n": 3.0}) == (True, "")
    assert bench.run_check(integer, {"n": 3.5}) == (False, "not_integer:n")


def test_score_run_separates_success_from_tool_use():
    task = {
        "id": "demo",
        "checks": [{"type": "number", "key": "x", "expected": 2.0, "abs": 0.01}],
        "evidence": ["result"],
        "tool_evidence": ["run_science_operation"],
    }
    result = {
        "status": "ok",
        "final_text": 'The result is 2.\n{"x": 2.0}',
        "tool_calls": [{"name": "run_science_operation"}],
        "tool_text": "run_science_operation",
    }
    score = bench.score_run(task, result)
    assert score["task_success"] is True
    assert score["tool_use_correct"] is True
    assert score["numerical_correctness"] == 1.0

    no_tool = bench.score_run(task, {**result, "tool_calls": [], "tool_text": ""})
    assert no_tool["task_success"] is True
    assert no_tool["tool_use_correct"] is False
    assert "no_tool_call" in no_tool["failure_modes"]


def test_score_run_reports_failure_modes():
    task = {
        "id": "demo",
        "checks": [{"type": "integer", "key": "n", "expected": 3}],
        "evidence": ["duplicate"],
        "tool_evidence": ["audit_table_quality"],
    }
    result = {
        "status": "ok",
        "final_text": '{"n": 2}',
        "tool_calls": [{"name": "audit_table_quality"}],
        "tool_text": "audit_table_quality",
    }
    score = bench.score_run(task, result)
    assert score["task_success"] is False
    assert "wrong:n" in score["failure_modes"]
    assert "evidence:duplicate" in score["failure_modes"]


def test_render_prompt_resolves_file_placeholders(tmp_path):
    task = {"prompt": "Read {file:data.csv} and write {workspace}."}
    resolved = bench.render_prompt(task, tmp_path)
    assert str(tmp_path / "data.csv") in resolved
    assert str(tmp_path) in resolved


def test_boolean_and_artifact_checks_drive_partial_score():
    task = {
        "id": "report",
        "checks": [
            {"type": "number", "key": "x", "expected": 2.0, "abs": 0.01},
            {"type": "boolean", "key": "saved", "expected": True},
        ],
        "evidence": ["report"],
        "artifacts": [{"name_pattern": "report", "content_pattern": "x=2"}],
        "tool_evidence": ["run_science_operation"],
    }
    result = {
        "status": "ok",
        "final_text": 'The report is saved.\n{"x": 2.0, "saved": true}',
        "tool_calls": [{"name": "run_science_operation"}],
        "tool_text": "run_science_operation",
        "artifact_texts": {"report.md": "modulus x=2 and evidence"},
    }
    score = bench.score_run(task, result)
    assert score["task_success"] is True
    assert score["partial_score"] == 1.0
    assert score["artifact_correctness"] == 1.0

    missing = bench.score_run(task, {**result, "artifact_texts": {}})
    assert missing["task_success"] is False
    assert missing["partial_score"] == pytest.approx(0.75)
    assert "artifact_missing:report" in missing["failure_modes"]


def test_hard_task_suite_loads_and_has_expected_coverage():
    tasks = bench.load_tasks(None, Path(bench.__file__).parent.parent / "testfixtures" / "harness_bench" / "tasks_hard.json")
    assert len(tasks) == 14
    categories = {category for task in tasks for category in task.get("categories", [])}
    for required in {
        "multi_step",
        "units",
        "mixed_specimens",
        "duplicates",
        "missing_data",
        "near_miss",
        "error_recovery",
        "long_table",
        "method_selection",
        "literature_evidence",
        "workflow",
        "adversarial",
    }:
        assert required in categories
    assert any(task.get("artifacts") for task in tasks)
