"""Polling API shared by chat and canvas; reconnecting never replays execution."""

import hashlib
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .tasks import TaskManager


def require_local_request(request):
    host = urlsplit("http://" + request.headers.get("host", ""))
    origin = request.headers.get("origin")
    source = urlsplit(origin) if origin else None
    if host.hostname not in {"localhost", "127.0.0.1", "::1"} or (
        source and (source.scheme != "http" or source.hostname != host.hostname or source.port != host.port)
    ):
        raise HTTPException(403, "Cross-origin requests are not accepted")


def task_router(harness):
    router = APIRouter()
    manager = TaskManager(harness.store.path.parent / "tasks.sqlite3")

    def session_check(session_id):
        if not harness.store.has_session(session_id):
            raise HTTPException(404, "研究会话不存在。")

    def owned_task(session_id, task_id):
        session_check(session_id)
        try:
            task = manager.get(task_id)
        except KeyError:
            raise HTTPException(404, "任务不存在。") from None
        if task["session_id"] != session_id:
            raise HTTPException(404, "任务不存在。")
        return task

    @router.get("/api/sessions/{session_id}/tasks")
    async def task_list(session_id: str, request: Request):
        require_local_request(request)
        session_check(session_id)
        return {"items": await run_in_threadpool(manager.list, session_id)}

    @router.get("/api/sessions/{session_id}/tasks/{task_id}")
    async def task_get(session_id: str, task_id: str, request: Request):
        require_local_request(request)
        return await run_in_threadpool(owned_task, session_id, task_id)

    @router.post("/api/sessions/{session_id}/tasks/{task_id}/cancel")
    async def task_cancel(session_id: str, task_id: str, request: Request):
        require_local_request(request)
        await run_in_threadpool(owned_task, session_id, task_id)
        return await run_in_threadpool(manager.cancel, task_id)

    @router.post("/api/sessions/{session_id}/tasks", status_code=202)
    async def task_submit(session_id: str, request: Request):
        require_local_request(request)
        session_check(session_id)
        raw = await request.body()
        if len(raw) > 64_000:
            raise HTTPException(413, "请求超过 64 KB。")
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("请求必须为对象。")
            message = data.get("message")
            flow_id = data.get("flow_id")
            if flow_id:
                if not isinstance(flow_id, str) or len(flow_id) > 80:
                    raise ValueError("流程标识无效。")
                flow = await run_in_threadpool(harness.langflow.get_flow, flow_id)
                harness._require_project_flow(session_id, flow)

                def work(progress):
                    return harness.run_canvas_workflow(flow_id, session_id=session_id, on_progress=progress)
            else:
                if not isinstance(message, str) or not 1 <= len(message.strip()) <= 12_000:
                    raise ValueError("消息必须包含 1 至 12000 个字符。")

                def work(progress):
                    return harness.run_turn(session_id, message, on_progress=progress)

            fingerprint = hashlib.sha256(
                json.dumps(
                    {"message": message, "flow_id": flow_id},
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()

            def submit_for_existing_session():
                with manager.lock:
                    session_check(session_id)
                    return manager.submit(session_id, data.get("request_key"), work, fingerprint=fingerprint)

            return await run_in_threadpool(submit_for_existing_session)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(409 if "运行任务" in str(exc) else 400, str(exc)) from exc

    return router, manager
