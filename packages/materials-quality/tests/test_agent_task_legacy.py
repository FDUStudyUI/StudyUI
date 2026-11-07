import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from materials_quality.agent.data_inspection import authorized_file
from materials_quality.agent.server import create_app
from materials_quality.agent.tasks import TaskManager


@pytest.fixture
def app_client(tmp_path):
    for name in ("workflows", "components", "frontend/assets"):
        (tmp_path / name).mkdir(parents=True)
    app = create_app(
        tmp_path / "agent.sqlite3", tmp_path / "workflows", tmp_path / "components", tmp_path / "frontend"
    )
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        session = client.post("/api/sessions", json={"title": "legacy"}).json()["id"]
        yield app, client, session


def test_cancellation_cannot_overwrite_a_terminal_worker_update(tmp_path):
    manager = TaskManager(tmp_path / "tasks.sqlite3")
    started, fail_work, terminal_written = threading.Event(), threading.Event(), threading.Event()
    original_get, original_update = manager.get, manager._update

    def work(progress):
        started.set()
        assert fail_work.wait(2)
        raise ValueError("failed work")

    def update(task_id, **values):
        original_update(task_id, **values)
        if values.get("status") in {"failed", "cancelled"}:
            terminal_written.set()

    task = manager.submit("session", "request", work)
    assert started.wait(2)

    def get(task_id):
        row = original_get(task_id)
        if row["status"] == "running":
            fail_work.set()
            terminal_written.wait(0.3)
        return row

    manager.get = get
    manager._update = update
    manager.cancel(task["id"])
    assert terminal_written.wait(2)
    assert original_get(task["id"])["status"] == "cancelled"


@pytest.mark.parametrize("endpoint", ["message", "canvas", "sse"])
def test_legacy_routes_cannot_enter_session_with_running_task(app_client, monkeypatch, endpoint):
    app, client, session = app_client
    entered, release = threading.Event(), threading.Event()
    called = []

    def run_turn(session_id, message, **kwargs):
        if message == "durable":
            entered.set()
            assert release.wait(3)
        else:
            called.append(message)
        return {"session_id": session_id, "message": message}

    def canvas_run(flow_id, **kwargs):
        called.append(flow_id)
        return {"session_id": session}

    monkeypatch.setattr(app.state.harness, "run_turn", run_turn)
    monkeypatch.setattr(app.state.harness, "run_canvas_workflow", canvas_run)
    task_path = f"/api/sessions/{session}/tasks"
    task = client.post(task_path, json={"message": "durable", "request_key": "request"}).json()
    assert entered.wait(2)
    try:
        if endpoint == "canvas":
            response = client.post(f"/canvas/api/v1/run/{uuid.uuid4()}", json={"studyui_session_id": session})
        else:
            stream = "?stream=true" if endpoint == "sse" else ""
            response = client.post(f"/api/sessions/{session}/messages{stream}", json={"message": "legacy"})
        if endpoint == "sse":
            assert response.status_code == 200
            assert "event: error" in response.text and "event: done" not in response.text
        else:
            assert response.status_code == 409
        assert not called
    finally:
        release.set()
        for _ in range(100):
            if client.get(f"{task_path}/{task['id']}").json()["terminal"]:
                break
            time.sleep(0.01)


def test_upload_prompt_quotes_identity_and_rejects_other_loopback_origin(app_client):
    _, client, session = app_client
    headers = {"X-Filename": "measurements.csv", "X-StudyUI-Session": session}
    rejected = client.post(
        "/api/upload",
        content=b"a,b\n1,2",
        headers={
            **headers,
            "Origin": "http://localhost:7880",
        },
    )
    assert rejected.status_code == 403
    data = client.post("/api/upload", content=b"a,b\n1,2", headers=headers).json()
    assert str(authorized_file(data["path"], data["prompt"])) == data["path"]


def test_durable_submission_cannot_enter_legacy_sse_session(app_client, monkeypatch):
    app, client, session = app_client
    entered, release = threading.Event(), threading.Event()

    def run_turn(session_id, message, *, on_progress):
        assert message == "legacy"
        entered.set()
        assert release.wait(3)
        on_progress({"type": "step_end", "step": "verified"})
        return {"session_id": session_id, "message": message}

    monkeypatch.setattr(app.state.harness, "run_turn", run_turn)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            client.post,
            f"/api/sessions/{session}/messages?stream=true",
            json={"message": "legacy"},
        )
        try:
            assert entered.wait(2)
            response = client.post(
                f"/api/sessions/{session}/tasks",
                json={"message": "durable", "request_key": "request"},
            )
            assert response.status_code == 409
        finally:
            release.set()
        response = pending.result(timeout=3)
    assert response.status_code == 200
    assert "event: step_end" in response.text
    assert "event: done" in response.text

def test_review_draft_download_preserves_the_submitted_bytes(app_client):
    _, client, session = app_client
    code = "\n# 审核草稿\nprint('example')  \n\n"
    response = client.post(
        "/api/canvas/insert-node", json={"name": "Review", "code": code, "session_id": session}
    )
    assert response.status_code == 202
    draft = response.json()
    artifact_id = draft["artifact"]["id"]
    download = client.get(f"/api/sessions/{session}/artifacts/{artifact_id}")
    assert download.status_code == 200
    assert download.content == code.encode("utf-8")

def test_approval_execution_preserves_pending_request_while_session_is_busy(app_client, monkeypatch):
    app, client, session = app_client
    harness = app.state.harness
    entered, release = threading.Event(), threading.Event()

    def active_task(progress):
        entered.set()
        assert release.wait(3)
        return {}

    task = app.state.tasks.submit(session, "active", active_task)
    assert entered.wait(2)
    dispatched = []

    def dispatch(session_id, name, args, user_text):
        dispatched.append((session_id, name))
        return {"status": "completed"}

    monkeypatch.setattr(harness, "_dispatch", dispatch)
    monkeypatch.setattr(harness.langflow, "get_flow", lambda flow_id: {"id": flow_id})
    approval = harness.request_approval(
        session, "workflow.run", "reviewed", {"tool": "run_workflow", "args": {"flow_id": "flow"}}
    )
    approval_id = approval["approval_id"]
    try:
        response = client.post(f"/api/approvals/{approval_id}/approve", json={})
        assert response.status_code == 409
        assert harness.store.get_approval(approval_id)["status"] == "pending"
        assert dispatched == []
    finally:
        release.set()
        for _ in range(100):
            if app.state.tasks.get(task["id"])["terminal"]:
                break
            time.sleep(0.01)
    result = client.post(f"/api/approvals/{approval_id}/approve", json={})
    assert result.status_code == 200, result.text
    assert dispatched == [(session, "run_workflow")]


@pytest.mark.parametrize("method", ["DELETE", "PATCH"])
def test_running_task_keeps_its_session_and_project(app_client, method):
    app, client, session = app_client
    entered, release = threading.Event(), threading.Event()
    harness = app.state.harness
    other = harness.store.create_project("Other project")
    original_project = harness.store.session_context(session)["project_id"]

    def active_task(progress):
        entered.set()
        assert release.wait(5)
        return {}

    task = app.state.tasks.submit(session, "active", active_task)
    task_url = f"/api/sessions/{session}/tasks/{task['id']}"
    try:
        assert entered.wait(2)
        payload = {"json": {"project_id": other}} if method == "PATCH" else {}
        response = client.request(method, f"/api/sessions/{session}", **payload)
        assert response.status_code == 409
        assert harness.store.session_context(session)["project_id"] == original_project
        assert client.get(task_url).json()["status"] == "running"
        assert client.post(task_url + "/cancel", json={}).json()["status"] == "cancelling"
    finally:
        release.set()
        for _ in range(100):
            if app.state.tasks.get(task["id"])["terminal"]:
                break
            time.sleep(0.01)


def test_task_submission_rechecks_session_after_workflow_lookup(app_client, monkeypatch):
    app, client, session = app_client
    entered, release = threading.Event(), threading.Event()

    def get_flow(flow_id):
        entered.set()
        assert release.wait(5)
        return {"id": flow_id, "folder_id": None}

    monkeypatch.setattr(app.state.harness.langflow, "get_flow", get_flow)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            client.post,
            f"/api/sessions/{session}/tasks",
            json={"flow_id": "flow", "request_key": "new"},
        )
        try:
            assert entered.wait(2)
            assert client.delete(f"/api/sessions/{session}").status_code == 200
        finally:
            release.set()
        assert pending.result(timeout=3).status_code == 404
    assert app.state.tasks.list(session) == []
