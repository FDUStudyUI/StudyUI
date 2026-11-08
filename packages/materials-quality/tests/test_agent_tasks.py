import threading
import time

import pytest

from materials_quality.agent.tasks import TaskManager, checkpoint


def wait(manager, task_id):
    for _ in range(200):
        result = manager.get(task_id)
        if result["status"] in {"completed", "cancelled", "failed", "interrupted", "waiting_approval"}:
            return result
        time.sleep(0.01)
    pytest.fail("task did not settle")


def test_cancellation_waits_for_running_operation_and_blocks_next(tmp_path):
    manager = TaskManager(tmp_path / "tasks.sqlite3")
    entered, release = threading.Event(), threading.Event()
    effects = []

    def work(progress):
        entered.set()
        release.wait(3)
        checkpoint()
        effects.append("next tool")
        return {"message": "done"}

    task = manager.submit("session", "request-one", work)
    assert entered.wait(2)
    assert manager.cancel(task["id"])["status"] == "cancelling"
    assert manager.get(task["id"])["status"] == "cancelling"
    release.set()
    assert wait(manager, task["id"])["status"] == "cancelled"
    assert effects == []


def test_idempotent_submit_session_exclusion_and_persistent_result(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    manager = TaskManager(path)
    release = threading.Event()

    def work(progress):
        release.wait(3)
        return {"message": "saved"}

    first = manager.submit("session", "request-one", work)
    assert manager.submit("session", "request-one", work)["id"] == first["id"]
    with pytest.raises(ValueError, match="运行"):
        manager.submit("session", "request-two", work)
    release.set()
    assert wait(manager, first["id"])["result"]["message"] == "saved"
    assert TaskManager(path).get(first["id"])["result"]["message"] == "saved"


def test_task_error_and_waiting_approval_are_not_success(tmp_path):
    manager = TaskManager(tmp_path / "tasks.sqlite3")

    def fail(progress):
        raise ValueError("bad input")

    task = manager.submit("session", "bad", fail)
    assert wait(manager, task["id"])["status"] == "failed"
    task = manager.submit("session", "approval", lambda progress: {"pending_approvals": [{"id": "a"}]})
    assert wait(manager, task["id"])["status"] == "waiting_approval"


def test_task_waits_for_every_approval_and_closes_after_the_last_decision(tmp_path):
    manager = TaskManager(tmp_path / "tasks.sqlite3")
    approvals = [{"id": "a"}, {"id": "b"}]
    task = manager.submit(
        "session",
        "two-approvals",
        lambda progress: {
            "message": "等待审批",
            "pending_approvals": approvals,
            "task_pending_approvals": approvals,
        },
    )
    assert wait(manager, task["id"])["status"] == "waiting_approval"

    first = manager.resolve_approval("session", "a", "approved")
    assert first == [{"id": task["id"], "status": "waiting_approval", "terminal": True}]
    assert manager.get(task["id"])["result"]["task_pending_approvals"] == [{"id": "b"}]

    second = manager.resolve_approval("session", "b", "rejected")
    assert second == [{"id": task["id"], "status": "cancelled", "terminal": True}]
    assert manager.get(task["id"])["result"]["pending_approvals"] == []
