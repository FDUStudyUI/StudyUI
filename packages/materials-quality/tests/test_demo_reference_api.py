"""Reference demos create session-owned, sanitized flows without executing anything."""

import threading
import uuid
from functools import lru_cache

import pytest
from fastapi.testclient import TestClient

from materials_quality.agent.server import create_app

IDS = ["ti64_tensile", "raman_spectra", "material_contrast", "zirconia_xrd", "battery_cycle"]


@lru_cache(maxsize=1)
def installed_demo_catalog():
    from components.materials_batch.batch_spectrum_analyzer import BatchSpectrumAnalyzer
    from components.materials_batch.contrast_study import ContrastStudy
    from components.materials_sources.science_fixture_bundle import ScienceFixtureBundle
    from materials_quality.science.catalog import component_class

    classes = [ScienceFixtureBundle, BatchSpectrumAnalyzer, ContrastStudy] + [
        component_class(key)
        for key in (
            "io.table_import",
            "materials.mechanics",
            "materials.xrd",
            "preprocess.filter",
            "preprocess.reshape",
            "viz.mechanics",
            "viz.spectra",
            "viz.performance",
            "export.table",
            "export.report",
        )
    ]
    return {"materials_demo": {cls().name: cls().to_frontend_node()["data"]["node"] for cls in classes}}


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    for name in ("workflows", "components", "frontend/assets"):
        (tmp_path / name).mkdir(parents=True)
    app = create_app(
        tmp_path / "agent.sqlite3", tmp_path / "workflows", tmp_path / "components", tmp_path / "frontend"
    )
    harness = app.state.harness
    harness.langflow._catalog_loader = installed_demo_catalog
    harness.langflow._catalog = None

    class NoModel:
        model = "must-not-run"

        def complete(self, *args, **kwargs):
            pytest.fail("Opening a reference invoked a model")

    harness.model = NoModel()
    monkeypatch.setattr(
        harness, "run_canvas_workflow", lambda *args, **kwargs: pytest.fail("Opening a reference executed it")
    )
    project = harness.store.create_project("Demo project")
    session = harness.new_session(project_id=project)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        yield app, client, session, project


@pytest.mark.parametrize("dataset_id", IDS)
def test_reference_endpoint_creates_without_model_or_run(demo_app, monkeypatch, dataset_id):
    app, client, session, project = demo_app
    response = client.post("/api/demo-datasets/reference", json={"id": dataset_id, "session_id": session})
    assert response.status_code == 201, response.text
    result = response.json()
    flow = app.state.harness.langflow.get_flow(result["flow_id"])
    assert flow["folder_id"] == project
    assert flow["data"]["nodes"] and flow["data"]["edges"]
    assert result["url"].startswith("/canvas/flow/" + flow["id"])
    assert session in result["url"]
    assert result["expected_summary"] and "运行" in result["instructions"]
    events = app.state.harness.store.events(session)
    assert any(e["kind"] == "workflow_created" and e["detail"]["flow_id"] == flow["id"] for e in events)
    assert not any(e["kind"] in {"canvas_run_authorized", "tool_call"} for e in events)


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"id": "../../unsafe", "session_id": "valid"}, 404),
        ({"id": "ti64_tensile", "session_id": "bad"}, 400),
        ({"id": "ti64_tensile", "session_id": str(uuid.uuid4())}, 404),
        ({"id": "ti64_tensile", "session_id": None}, 400),
        ({"id": "ti64_tensile", "session_id": "valid", "flow": {"code": "malicious"}}, 400),
        ({"id": "ti64_tensile", "session_id": "valid", "project_id": "other"}, 400),
    ],
)
def test_reference_rejects_invalid_input_without_writes(demo_app, payload, status):
    app, client, session, _ = demo_app
    payload = {
        **payload,
        "session_id": session if payload["session_id"] == "valid" else payload["session_id"],
    }
    result = client.post("/api/demo-datasets/reference", json=payload)
    assert result.status_code == status, result.text
    assert app.state.harness.langflow.list_flows() == []


@pytest.mark.parametrize("preset", ["read_only", "per_action"])
def test_reference_obeys_project_permissions(demo_app, preset):
    app, client, session, project = demo_app
    app.state.harness.permissions.set_preset(project, preset)
    result = client.post("/api/demo-datasets/reference", json={"id": "ti64_tensile", "session_id": session})
    assert result.status_code == 403, result.text
    assert app.state.harness.langflow.list_flows() == []


def test_reference_rejects_busy_session(demo_app):
    app, client, session, _ = demo_app
    entered, release = threading.Event(), threading.Event()

    def running(progress):
        entered.set()
        assert release.wait(10)
        return {}

    app.state.tasks.submit(session, "busy-demo", running)
    assert entered.wait(2)
    try:
        response = client.post(
            "/api/demo-datasets/reference", json={"id": "ti64_tensile", "session_id": session}
        )
        assert response.status_code == 409, response.text
        assert app.state.harness.langflow.list_flows() == []
    finally:
        release.set()


@pytest.mark.parametrize("dataset_id", IDS)
def test_demo_agent_load_uses_verified_packaged_bytes(demo_app, dataset_id):
    from pathlib import Path

    from materials_quality.demos.catalog import get_dataset, read_demo_bytes

    _, client, session, _ = demo_app
    response = client.post("/api/demo-datasets/load", json={"id": dataset_id, "session_id": session})
    assert response.status_code == 200, response.text
    result = response.json()
    assert Path(result["path"]).read_bytes() == read_demo_bytes(dataset_id)
    assert result["sha256"] == get_dataset(dataset_id)["sha256"]
    assert '"' + result["path"] + '"' in result["prompt"]


def test_reference_copies_are_unique_and_bound_to_each_session_project(demo_app):
    app, client, session, project = demo_app
    other_project = app.state.harness.store.create_project("Other")
    other_session = app.state.harness.new_session(project_id=other_project)
    first = client.post(
        "/api/demo-datasets/reference", json={"id": "ti64_tensile", "session_id": session}
    ).json()
    second = client.post(
        "/api/demo-datasets/reference", json={"id": "ti64_tensile", "session_id": other_session}
    ).json()
    assert first["flow_id"] != second["flow_id"]
    first_flow = app.state.harness.langflow.get_flow(first["flow_id"])
    second_flow = app.state.harness.langflow.get_flow(second["flow_id"])
    assert first_flow["folder_id"] == project
    assert second_flow["folder_id"] == other_project
    with pytest.raises(PermissionError):
        app.state.harness._require_project_flow(session, second_flow)


def test_reference_sanitizes_packaged_node_code_before_storage(demo_app, monkeypatch):
    from materials_quality.agent import demo_reference

    app, client, session, _ = demo_app
    reference = demo_reference.load_reference_flow("ti64_tensile")
    node = reference["data"]["nodes"][0]
    node["data"]["node"]["template"]["code"]["value"] = "raise RuntimeError('untrusted saved code')"
    monkeypatch.setattr(demo_reference, "load_reference_flow", lambda _: reference)
    response = client.post("/api/demo-datasets/reference", json={"id": "ti64_tensile", "session_id": session})
    assert response.status_code == 201, response.text
    saved = app.state.harness.langflow.get_flow(response.json()["flow_id"])
    code = saved["data"]["nodes"][0]["data"]["node"]["template"]["code"]["value"]
    assert "untrusted saved code" not in code
    assert (
        code == installed_demo_catalog()["materials_demo"][node["data"]["type"]]["template"]["code"]["value"]
    )


def test_reference_rejects_unknown_node_before_creating_file(demo_app, monkeypatch):
    from materials_quality.agent import demo_reference

    app, client, session, _ = demo_app
    reference = demo_reference.load_reference_flow("ti64_tensile")
    reference["data"]["nodes"][0]["data"]["type"] = "UntrustedNode"
    monkeypatch.setattr(demo_reference, "load_reference_flow", lambda _: reference)
    response = client.post("/api/demo-datasets/reference", json={"id": "ti64_tensile", "session_id": session})
    assert response.status_code == 400, response.text
    assert app.state.harness.langflow.list_flows() == []


def test_failed_reference_update_does_not_leave_a_blank_workflow(demo_app, monkeypatch):
    app, client, session, _ = demo_app

    def failed_update(*args):
        raise OSError("simulated write failure")

    monkeypatch.setattr(app.state.harness.langflow, "update_flow", failed_update)
    response = client.post("/api/demo-datasets/reference", json={"id": "ti64_tensile", "session_id": session})
    assert response.status_code == 400
    assert app.state.harness.langflow.list_flows() == []
    assert not any(e["kind"] == "workflow_created" for e in app.state.harness.store.events(session))
