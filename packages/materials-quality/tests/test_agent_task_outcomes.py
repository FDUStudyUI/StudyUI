import threading
import time

import pytest
from test_agent_boundary_reliability import app_client as app_client

from materials_quality.agent.harness import StudyUIAgent
from materials_quality.agent.tasks import TaskManager


def settle(manager, task_id):
    for _ in range(300):
        value = manager.get(task_id)
        if value["terminal"]:
            return value
        time.sleep(0.01)
    pytest.fail("task did not settle")


def test_partial_output_is_persisted_without_reasoning(tmp_path):
    manager = TaskManager(tmp_path / "tasks.db")
    ready, release = threading.Event(), threading.Event()

    def work(progress):
        progress({"type": "reasoning", "delta": "private reasoning"})
        progress({"type": "content_chunk", "delta": "## Result\n$E="})
        ready.set()
        assert release.wait(3)
        progress({"type": "content_chunk", "delta": "1$"})
        return {"message": "## Result\n$E=1$"}

    task = manager.submit("s", "r", work)
    try:
        assert ready.wait(2)
        snapshot = manager.get(task["id"])
        assert snapshot["partial_content"] == "## Result\n$E="
        assert "private reasoning" not in str(snapshot)
    finally:
        release.set()
    final = settle(manager, task["id"])
    assert final["partial_content"] == final["result"]["message"]


def test_old_approval_does_not_mark_new_turn_waiting(app_client):
    app, _, session = app_client
    harness = app.state.harness
    harness.request_approval(session, "workflow.run", "old", {"tool": "run_workflow", "args": {}})

    class Model:
        def complete(self, messages, tools, **kwargs):
            return {"content": "answer"}

    harness.model, harness._custom_model = Model(), True
    task = app.state.tasks.submit(session, "new", lambda progress: harness.run_turn(session, "hello"))
    result = settle(app.state.tasks, task["id"])
    assert result["status"] == "completed"
    assert result["result"]["pending_approvals"]
    assert result["result"]["task_pending_approvals"] == []


def test_model_failure_with_saved_response_has_failed_task(app_client):
    app, _, session = app_client
    harness = app.state.harness

    class Model:
        def complete(self, messages, tools, **kwargs):
            raise ValueError("Model request failed: connection closed")

    harness.model, harness._custom_model = Model(), True
    task = app.state.tasks.submit(session, "new", lambda progress: harness.run_turn(session, "hello"))
    result = settle(app.state.tasks, task["id"])
    assert result["status"] == "failed"
    assert "模型服务请求失败" in result["result"]["message"]


def test_internal_type_error_never_replays_model_request(tmp_path):
    class Model:
        calls = 0

        def complete(self, messages, tools, **kwargs):
            self.calls += 1
            raise TypeError("provider decoded an invalid value")

    model = Model()
    harness = StudyUIAgent(tmp_path / "agent.db", model=model, langflow=object())
    session = harness.new_session()
    with pytest.raises(TypeError):
        harness.run_turn(session, "hello")
    assert model.calls == 1


@pytest.mark.parametrize(
    "origin", ["http://localhost:7880", "http://127.0.0.1:9999", "https://127.0.0.1:7880"]
)
def test_canvas_rejects_other_local_origins(app_client, origin):
    _, client, _ = app_client
    response = client.get("/canvas/api/v1/all", headers={"Origin": origin})
    assert response.status_code == 403
