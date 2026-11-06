from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from materials_quality.agent.server import create_app


@pytest.fixture
def app_client(tmp_path):
    for name in ("workflows", "components", "frontend/assets"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "frontend/index.html").write_text("<html>Canvas</html>", encoding="utf-8")
    app = create_app(tmp_path / "agent.sqlite3", tmp_path / "workflows",
                     tmp_path / "components", tmp_path / "frontend")
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        session = client.post("/api/sessions", json={"title": "boundary"}).json()["id"]
        yield app, client, session


def test_upload_requires_real_session_and_cannot_escape(app_client, tmp_path):
    _, client, _ = app_client
    for session in ("", "missing-session", "../outside", str(tmp_path / "outside")):
        response = client.post("/api/upload", content=b"a,b\n1,2", headers={
            "X-Filename": "input.csv", "X-StudyUI-Session": quote(session),
        })
        assert response.status_code in {400, 403, 404}
    assert not (tmp_path / "outside").exists()


def test_upload_preserves_versions_and_respects_read_only(app_client):
    app, client, session = app_client
    headers = {"X-Filename": "input.csv", "X-StudyUI-Session": session}
    first = client.post("/api/upload", content=b"a\n1", headers=headers)
    second = client.post("/api/upload", content=b"a\n2", headers=headers)
    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    assert a["path"] != b["path"]
    assert Path(a["path"]).read_bytes() == b"a\n1"
    assert a["sha256"] != b["sha256"]
    app.state.harness.permissions.set_preset(None, "read_only")
    assert client.post("/api/upload", content=b"a\n3", headers=headers).status_code == 403


def test_generated_code_is_only_a_review_draft(app_client):
    app, client, session = app_client
    response = client.post("/api/canvas/insert-node", json={
        "name": "Example", "code": "print('must not run')", "session_id": session,
    })
    assert response.status_code == 202
    draft = response.json()
    assert draft["status"] == "draft"
    assert draft["executable"] is False
    assert not list((app.state.harness.project_root / ".demo-runtime/components").rglob("example.py"))
    app.state.harness.permissions.set_preset(None, "read_only")
    assert client.post("/api/canvas/insert-node", json={
        "name": "Example", "code": "pass", "session_id": session,
    }).status_code == 403


def test_ui_does_not_claim_unperformed_scientific_checks(app_client):
    _, client, _ = app_client
    page = client.get("/").text
    assert "✓ 物理量纲与标准合规性审计" not in page
    assert "✓ 权威文献依据溯源与顶刊区间基准比对" not in page


def test_message_endpoint_enforces_origin(app_client):
    _, client, session = app_client
    response = client.post(f"/api/sessions/{session}/messages", json={"message": "hello"},
                           headers={"Origin": "https://unrelated.example"})
    assert response.status_code == 403


def test_durable_task_api_result_recovery_and_origin(app_client):
    import time

    app, client, session = app_client

    class Model:
        def complete(self, messages, tools, **kwargs):
            return {"content": "task result"}

    app.state.harness.model = Model()
    app.state.harness._custom_model = True
    body = {"message": "hello", "request_key": "same-request"}
    response = client.post(f"/api/sessions/{session}/tasks", json=body)
    assert response.status_code == 202
    task_id = response.json()["id"]
    assert client.post(f"/api/sessions/{session}/tasks", json=body).json()["id"] == task_id
    for _ in range(100):
        task = client.get(f"/api/sessions/{session}/tasks/{task_id}").json()
        if task["terminal"]:
            break
        time.sleep(0.02)
    assert task["status"] == "completed"
    assert task["result"]["message"] == "task result"
    assert client.get(f"/api/sessions/{session}/tasks").json()["items"][0]["id"] == task_id
    assert client.post(f"/api/sessions/{session}/tasks", json=body,
                       headers={"Origin": "https://unrelated.example"}).status_code == 403
    other = client.post("/api/sessions", json={"title": "other"}).json()["id"]
    assert client.get(f"/api/sessions/{other}/tasks/{task_id}").status_code == 404
