import threading
import time

from materials_quality.agent.workflow_jobs import WorkflowJobQueue


def _wait_for(queue, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = queue.get(job_id)
        if job is not None and job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.02)
    return queue.get(job_id)


def test_job_completes_and_lists_in_recent_first_order():
    queue = WorkflowJobQueue(
        lambda flow_id, *, external_data_approved=False: {
            "flow_id": flow_id,
            "outputs": [{"component": "executor"}],
        }
    )

    job = queue.submit("flow-1", name="示例")

    done = _wait_for(queue, job["id"])
    assert done["status"] == "completed"
    assert done["result"]["outputs"] == [{"component": "executor"}]
    assert queue.list()[0]["id"] == job["id"]


def test_job_failure_is_reported():
    def runner(flow_id, *, external_data_approved=False):
        raise RuntimeError("boom")

    queue = WorkflowJobQueue(runner)
    job = queue.submit("flow-1")

    done = _wait_for(queue, job["id"])
    assert done["status"] == "failed"
    assert "boom" in done["error"]


def test_running_job_can_be_cancelled():
    gate = threading.Event()

    def runner(flow_id, *, external_data_approved=False):
        gate.wait(3)
        return {"outputs": []}

    queue = WorkflowJobQueue(runner)
    job = queue.submit("flow-1")
    deadline = time.time() + 3
    while time.time() < deadline and queue.get(job["id"])["status"] != "running":
        time.sleep(0.02)

    queue.cancel(job["id"])
    gate.set()

    done = _wait_for(queue, job["id"])
    assert done["status"] == "cancelled"
    assert "取消" in done["error"]


def test_missing_job_returns_none():
    queue = WorkflowJobQueue(lambda flow_id, *, external_data_approved=False: {})
    assert queue.get("missing") is None
    assert queue.cancel("missing") is None
