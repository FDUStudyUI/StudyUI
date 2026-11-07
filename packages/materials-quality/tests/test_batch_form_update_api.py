"""Installed native batch forms refresh without executing request-supplied code."""

import copy

import pytest
from fastapi.testclient import TestClient

from components.materials_batch.batch_spectrum_analyzer import BatchSpectrumAnalyzer
from materials_quality.agent.file_workflow_client import FileWorkflowClient
from materials_quality.agent.workbench import create_app


@pytest.fixture
def batch_update_client(tmp_path, monkeypatch):
    component = BatchSpectrumAnalyzer().to_frontend_node()["data"]["node"]
    monkeypatch.setattr(
        FileWorkflowClient,
        "component_catalog",
        lambda _: {"materials_batch": {"BatchSpectrumAnalyzer": component}},
    )
    frontend = tmp_path / "ui"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("StudyUI", encoding="utf-8")
    (tmp_path / "components").mkdir()
    with TestClient(create_app(tmp_path / "workflows", tmp_path / "components", frontend)) as client:
        yield client, component


@pytest.mark.parametrize(
    "field,value,visible,hidden",
    [
        (
            "prominence_mode",
            "noise_reference",
            ["noise_window_low", "noise_window_high", "noise_multiplier"],
            ["prominence"],
        ),
        (
            "prominence_mode",
            "absolute",
            ["prominence"],
            ["noise_window_low", "noise_window_high", "noise_multiplier"],
        ),
        ("lambda10_enabled", True, ["lambda10_min_nm", "lambda10_max_nm", "lambda10_selection"], []),
        ("lambda10_enabled", False, [], ["lambda10_min_nm", "lambda10_max_nm", "lambda10_selection"]),
    ],
)
def test_batch_form_refresh_preserves_values_and_recomputes_visibility(
    batch_update_client, field, value, visible, hidden
):
    client, component = batch_update_client
    template = copy.deepcopy(component["template"])
    template["prominence"]["value"] = 0.75
    template["lambda10_min_nm"]["value"] = 650
    template["lambda10_max_nm"]["value"] = 850
    response = client.post(
        "/api/v1/custom_component/update",
        json={
            "code": template["code"]["value"],
            "frontend_node": {"metadata": {"component_class_name": "BatchSpectrumAnalyzer"}},
            "template": template,
            "field": field,
            "field_value": value,
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()["template"]
    assert updated[field]["value"] == value
    assert updated["prominence"]["value"] == 0.75
    assert updated["lambda10_min_nm"]["value"] == 650
    assert updated["lambda10_max_nm"]["value"] == 850
    for name in visible:
        assert updated[name]["show"] is True
    for name in hidden:
        assert updated[name]["show"] is False
    assert updated["code"] == component["template"]["code"]


def test_batch_form_rejects_modified_request_code(batch_update_client):
    client, component = batch_update_client
    response = client.post(
        "/api/v1/custom_component/update",
        json={
            "code": component["template"]["code"]["value"] + '\nraise RuntimeError("untrusted")',
            "frontend_node": {"metadata": {"component_class_name": "BatchSpectrumAnalyzer"}},
            "template": component["template"],
            "field": "lambda10_enabled",
            "field_value": True,
        },
    )
    assert response.status_code == 403


def test_batch_form_cannot_overwrite_code_through_changed_field(batch_update_client):
    client, component = batch_update_client
    response = client.post(
        "/api/v1/custom_component/update",
        json={
            "code": component["template"]["code"]["value"],
            "frontend_node": {"metadata": {"component_class_name": "BatchSpectrumAnalyzer"}},
            "template": component["template"],
            "field": "code",
            "field_value": "untrusted code",
        },
    )
    assert response.status_code == 422


def test_batch_refresh_retains_selected_column_without_accepting_request_options(batch_update_client):
    client, component = batch_update_client
    template = copy.deepcopy(component["template"])
    template["x_column"]["value"] = "wavelength_nm"
    template["y_column"]["value"] = "intensity_counts"
    template["x_column"]["options"] = ["injected-option"]
    template["x_column"]["display_name"] = "Injected schema"
    response = client.post(
        "/api/v1/custom_component/update",
        json={
            "code": component["template"]["code"]["value"],
            "frontend_node": {"metadata": {"component_class_name": "BatchSpectrumAnalyzer"}},
            "template": template,
            "field": "lambda10_enabled",
            "field_value": True,
        },
    )
    assert response.status_code == 200
    updated = response.json()["template"]
    assert "wavelength_nm" in updated["x_column"]["options"]
    assert "intensity_counts" in updated["y_column"]["options"]
    assert "injected-option" not in updated["x_column"]["options"]
    assert updated["x_column"]["display_name"] == component["template"]["x_column"]["display_name"]


def test_batch_refresh_loads_packaged_source_without_top_level_components(
    batch_update_client, tmp_path, monkeypatch
):
    import builtins
    from pathlib import Path

    from materials_quality.agent import workbench

    client, component = batch_update_client
    package = tmp_path / "installed" / "materials_quality"
    source = package / "component_sources" / "materials_batch" / "batch_spectrum_analyzer.py"
    source.parent.mkdir(parents=True)
    original = Path(__file__).resolve().parents[1] / "components/materials_batch/batch_spectrum_analyzer.py"
    source.write_bytes(original.read_bytes())
    monkeypatch.setattr(workbench, "__file__", str(package / "agent/workbench.py"))
    original_import = builtins.__import__

    def wheel_import(name, *args, **kwargs):
        if name == "components" or name.startswith("components."):
            raise ModuleNotFoundError("Wheel has no top-level components package")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", wheel_import)
    response = client.post(
        "/api/v1/custom_component/update",
        json={
            "code": component["template"]["code"]["value"],
            "frontend_node": {"metadata": {"component_class_name": "BatchSpectrumAnalyzer"}},
            "template": component["template"],
            "field": "lambda10_enabled",
            "field_value": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["template"]["lambda10_min_nm"]["show"] is True
