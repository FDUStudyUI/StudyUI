from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from materials_quality.science.material_tasks import assess_protocol, task_catalog


def example(task):
    x = np.linspace(0, 0.02, 401) if task == "mechanics" else np.linspace(10, 80, 701)
    y = (
        np.where(x <= 0.001, 200000 * x, 199 + 1000 * x)
        if task == "mechanics"
        else 100 * np.exp(-(((x - 40) / 2) ** 2))
    )
    spec = {
        "task": task,
        "x": "x",
        "y": "y",
        "x_unit": "fraction" if task == "mechanics" else "deg" if task == "xrd" else "nm",
        "y_unit": "MPa" if task == "mechanics" else "counts",
    }
    spec.update(
        {"fit_range": [0, 0.0008], "yield_offset": 0.002}
        if task == "mechanics"
        else {"baseline": "none", "prominence": 1}
    )
    return pd.DataFrame({"x": x, "y": y}), spec


@pytest.mark.parametrize("task", ["mechanics", "spectra", "xrd"])
def test_method_checks_report_evidence_and_leave_input_unchanged(task):
    frame, spec = example(task)
    before, config = frame.copy(deep=True), deepcopy(spec)
    result = assess_protocol(frame, spec)
    assert result["status"] == "ready"
    assert len(result["checks"]) == 12
    assert all(c["outcome"] == "pass" and c["expected"] for c in result["checks"])
    assert len(result["cards"]) == 6
    pd.testing.assert_frame_equal(frame, before)
    assert spec == config


def test_material_notes_bind_real_operations_and_sources():
    from materials_quality.component_manifest import component_manifest
    from materials_quality.science.catalog import entries

    operations = {e["key"] for e in entries()}
    manifest = component_manifest(Path(__file__).resolve().parents[1] / "components")
    operations.update(name for names in manifest.values() for name in names)
    cards = [c for t in task_catalog() for c in t["cards"]]
    assert len({c["id"] for c in cards}) == 18
    assert all(c["operation"] in operations for c in cards)
    assert all(c["source"]["url"].startswith("https://") for c in cards)


def test_missing_method_information_provides_form_actions():
    frame, spec = example("mechanics")
    del spec["fit_range"]
    result = assess_protocol(frame, spec)
    assert result["status"] == "need_info"
    assert any(
        c["check_id"] == "mechanics.fit_range" and c["outcome"] == "need_info" for c in result["checks"]
    )
    assert result["next_actions"]


def test_transmittance_and_wrong_xrd_axis_select_another_method():
    frame, spec = example("spectra")
    spec["signal_kind"] = "transmittance"
    assert assess_protocol(frame, spec)["status"] == "change_method"
    frame, spec = example("xrd")
    frame["x"] += 200
    assert assess_protocol(frame, spec)["status"] == "change_method"


def test_compiled_protocol_embeds_versioned_checks_and_method_cards(tmp_path):
    from materials_quality.agent.material_protocols import compile_material_protocol

    frame, spec = example("mechanics")
    path = tmp_path / "curve.csv"
    frame.to_csv(path, index=False)
    result = compile_material_protocol({**spec, "path": str(path)})
    assert result["protocol"]["assessment"]["status"] == "ready"
    assert len(result["protocol"]["assessment"]["checks"]) == 12


@pytest.mark.parametrize(
    "task,condition,status",
    [
        ("mechanics", "missing_column", "need_info"),
        ("spectra", "missing_column", "need_info"),
        ("xrd", "missing_column", "need_info"),
        ("mechanics", "missing_unit", "need_info"),
        ("mechanics", "invalid_fit", "need_info"),
        ("mechanics", "negative_slope", "change_method"),
        ("spectra", "missing_baseline", "need_info"),
        ("spectra", "zero_threshold", "need_info"),
        ("spectra", "repeated_coordinate", "change_method"),
        ("spectra", "transmittance", "change_method"),
        ("xrd", "wrong_unit", "need_info"),
        ("xrd", "wrong_angle", "change_method"),
    ],
)
def test_method_conditions_separate_missing_information_from_inapplicable_methods(task, condition, status):
    table, spec = example(task)
    if condition == "missing_column":
        spec["x"] = "absent"
    elif condition == "missing_unit":
        spec["y_unit"] = ""
    elif condition == "invalid_fit":
        spec["fit_range"] = [0.8, 1.0]
    elif condition == "negative_slope":
        table["y"] *= -1
    elif condition == "missing_baseline":
        spec.pop("baseline")
    elif condition == "zero_threshold":
        spec["prominence"] = 0
    elif condition == "repeated_coordinate":
        table.loc[1, "x"] = table.loc[0, "x"]
    elif condition == "transmittance":
        spec["signal_kind"] = "transmittance"
    elif condition == "wrong_unit":
        spec["x_unit"] = "rad"
    elif condition == "wrong_angle":
        table["x"] += 200
    result = assess_protocol(table, spec)
    assert result["status"] == status
    assert result["next_actions"]
