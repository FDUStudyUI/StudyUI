"""Regression tests: /api/v2 run overrides must be authorized and sanitized as executed."""

import uuid

import pytest
from fastapi.testclient import TestClient

from materials_quality.agent import workflow_host
from materials_quality.agent.file_workflow_client import FileWorkflowClient
from materials_quality.agent.server import create_app
from materials_quality.agent.workflow_host import FileWorkflowHost

CATALOG = {
    "materials_analysis": {
        "StudyUIAIAnalysis": {
            "template": {
                "code": {"value": "trusted-ai-code"},
                "ui_mode": {"value": "form", "show": True},
            },
            "outputs": [],
        },
        "SafeNode": {
            "template": {
                "code": {"value": "trusted-safe-code"},
                "ui_mode": {"value": "form", "show": True},
            },
            "outputs": [],
        },
    }
}


class FakeGraph:
    vertices = []

    def prepare(self, **kwargs):
        return None


@pytest.fixture
def canvas(tmp_path, monkeypatch):
    # Trusted installed catalog: every run must rebind to this code, never to
    # bytes supplied in the request body.
    monkeypatch.setattr(FileWorkflowClient, "component_catalog", lambda self: CATALOG)
    for name in ("workflows", "components", "frontend/assets"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "frontend" / "index.html").write_text("StudyUI", encoding="utf-8")
    app = create_app(
        tmp_path / "agent.sqlite3", tmp_path / "workflows", tmp_path / "components", tmp_path / "frontend"
    )
    harness = app.state.harness
    project = harness.store.create_project("Project")
    flow = {
        "id": str(uuid.uuid4()),
        "name": "safe flow",
        "folder_id": project,
        "data": {"nodes": [], "edges": []},
    }
    harness.langflow.store.save(flow, create_only=True)
    state = {"loaded": None, "ran": False}

    async def fake_aload(payload, **kwargs):
        state["loaded"] = payload
        return FakeGraph()

    async def fake_run_sync(self, parsed, flow, caller, **kwargs):
        state["ran"] = True
        return {"outputs": {}}

    monkeypatch.setattr(workflow_host, "aload_flow_from_json", fake_aload)
    monkeypatch.setattr(FileWorkflowHost, "run_sync", fake_run_sync)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        yield client, flow, state


def _override_node(node_type, code):
    return {
        "nodes": [
            {
                "id": "injected",
                "data": {
                    "type": node_type,
                    "node": {"template": {"code": {"value": code}}},
                },
            }
        ],
        "edges": [],
    }


def test_request_data_cannot_add_unapproved_ai_analysis_node(canvas):
    client, flow, state = canvas
    response = client.post(
        "/canvas/api/v2/workflows",
        json={"flow_id": flow["id"], "data": _override_node("StudyUIAIAnalysis", "trusted-ai-code")},
    )
    assert response.status_code == 403, response.text
    assert state["ran"] is False


def test_request_data_cannot_inject_untrusted_component_code(canvas):
    client, flow, state = canvas
    response = client.post(
        "/canvas/api/v2/workflows",
        json={"flow_id": flow["id"], "data": _override_node("SafeNode", "raise SystemExit(1)")},
    )
    assert response.status_code == 200, response.text
    assert state["ran"] is True
    assert state["loaded"] is not None
    node = state["loaded"]["data"]["nodes"][0]
    assert node["data"]["node"]["template"]["code"]["value"] == "trusted-safe-code"


def test_request_data_must_only_contain_installed_components(canvas):
    client, flow, state = canvas
    response = client.post(
        "/canvas/api/v2/workflows",
        json={"flow_id": flow["id"], "data": _override_node("UninstalledNode", "import os")},
    )
    assert response.status_code == 422, response.text
    assert state["ran"] is False
