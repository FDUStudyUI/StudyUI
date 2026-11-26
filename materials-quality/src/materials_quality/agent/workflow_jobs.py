"""Agent-free workflow run queue used by the canvas UI.

A single worker runs one workflow at a time (a ComfyUI-style queue) and keeps a
bounded history of recent jobs. The runner is supplied by the sidecar; this
module owns scheduling, status, cancellation and result truncation only.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid

MAX_RESULT_CHARS = 1_500_000


def _bounded_result(result):
    try:
        from materials_quality.science_tools import _jsonable

        value = _jsonable(result)
    except Exception:
        value = result
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return {"note": "运行结果无法序列化", "type": type(result).__name__}
    if len(text) <= MAX_RESULT_CHARS:
        return value
    return {
        "truncated": True,
        "chars": len(text),
        "note": "运行结果过大，已截断；完整产物请查看工作区文件。",
    }


class WorkflowJobQueue:
    """FIFO queue with one worker and a bounded recent-job history."""

    def __init__(self, runner, *, history: int = 30):
        self.runner = runner
        self.history = max(1, int(history))
        self._jobs: dict[str, dict] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker = threading.Thread(target=self._loop, name="studyui-workflow-jobs", daemon=True)
        self._worker.start()

    def submit(self, flow_id, *, name: str = "", external_data_approved: bool = False) -> dict:
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "flow_id": str(flow_id),
            "name": str(name or flow_id),
            "status": "queued",
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": "",
            "external_data_approved": bool(external_data_approved),
        }
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            while len(self._order) > self.history:
                oldest = self._order[0]
                if self._jobs.get(oldest, {}).get("status") in {"queued", "running"}:
                    break
                self._order.pop(0)
                self._jobs.pop(oldest, None)
            public = dict(job)
        self._queue.put(job_id)
        return public

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                with self._lock:
                    job = self._jobs.get(job_id)
                    if job is None or job.get("status") != "queued":
                        continue
                    job["status"] = "running"
                    job["started_at"] = time.time()
                    flow_id = job["flow_id"]
                    approved = bool(job.get("external_data_approved"))
                try:
                    result = self.runner(flow_id, external_data_approved=approved)
                except Exception as exc:
                    with self._lock:
                        if job.get("status") != "cancelled":
                            job["status"] = "failed"
                            job["error"] = f"{type(exc).__name__}: {exc}"
                else:
                    with self._lock:
                        if job.get("status") != "cancelled":
                            job["result"] = _bounded_result(result)
                            job["status"] = "completed"
                finally:
                    with self._lock:
                        job["finished_at"] = time.time()
            finally:
                self._queue.task_done()

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            return dict(job) if job is not None else None

    def list(self) -> list[dict]:
        with self._lock:
            jobs = [dict(self._jobs[job_id]) for job_id in reversed(self._order) if job_id in self._jobs]
        return jobs

    def cancel(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                return None
            if job.get("status") in {"queued", "running"}:
                job["status"] = "cancelled"
                job["error"] = "已请求取消；正在执行的步骤可能仍会完成。"
                if job.get("started_at") is None:
                    job["finished_at"] = time.time()
            return dict(job)
