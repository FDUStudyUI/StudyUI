"""Regression tests: request-body validation and approval failure state."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from materials_quality.agent.server import create_app


@pytest.fixture
def client(tmp_path):
    for name in ("workflows", "components", "frontend/assets"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "frontend" / "index.html").write_text("StudyUI", encoding="utf-8")
    app = create_app(
        tmp_path / "agent.sqlite3", tmp_path / "workflows", tmp_path / "components", tmp_path / "frontend"
    )
    with TestClient(app, base_url="http://127.0.0.1:7880", raise_server_exceptions=False) as test_client:
        session = test_client.post("/api/sessions", json={"title": "routes"}).json()["id"]
        yield app, test_client, session


@pytest.mark.parametrize("body", [[], "text", 7])
def test_message_route_rejects_non_object_json_body(client, body):
    _, test_client, session = client
    response = test_client.post(f"/api/sessions/{session}/messages", json=body)
    assert response.status_code == 400, (response.status_code, response.text)
    assert "error" in response.json()


def test_failed_approved_action_resolves_waiting_task(client, monkeypatch):
    app, test_client, session = client
    harness = app.state.harness
    approval_id = str(uuid.uuid4())
    harness.store.create_approval(
        approval_id,
        session,
        None,
        "data.inspect",
        "读取本地数据",
        {"kind": "tool_call", "tool": "data.inspect", "args": {}},
    )

    def waiting(progress):
        return {"message": "waiting", "task_pending_approvals": [{"id": approval_id}]}

    task = app.state.tasks.submit(session, "waiting-approval-task", waiting)
    current = app.state.tasks.get(task["id"])
    for _ in range(300):
        if current["terminal"]:
            break
        time.sleep(0.01)
        current = app.state.tasks.get(task["id"])
    assert current["status"] == "waiting_approval"

    def failed_dispatch(*args, **kwargs):
        raise RuntimeError("simulated dispatch failure")

    monkeypatch.setattr(harness, "decide_approval", failed_dispatch)
    response = test_client.post(f"/api/approvals/{approval_id}/approve", json={})
    assert response.status_code == 400, response.text
    resolved = app.state.tasks.get(task["id"])
    assert resolved["status"] != "waiting_approval", resolved
    assert resolved["status"] == "failed"
