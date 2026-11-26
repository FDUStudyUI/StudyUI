"""Loopback REST surface for the MatOS tool catalog and CLI adapter."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from materials_quality.matos import (
    MatOSInputError,
    MatOSToolNotFound,
    describe_matos_tool,
    list_matos_tools,
    run_matos_tool,
    runtime_status,
)

from .task_api import require_local_request


def create_matos_router() -> APIRouter:
    """Create the MatOS REST router.

    The POST body is the MatOS tool's input object itself, matching
    ``matos assets run-tool --input-file -``. Pass ``?timeout_seconds=`` to
    override the catalog timeout.
    """
    router = APIRouter(prefix="/api/matos", tags=["matos"])

    @router.get("/status")
    async def matos_status(request: Request):
        require_local_request(request)
        return runtime_status()

    @router.get("/tools")
    async def matos_tools(
        request: Request,
        family: str | None = None,
        kind: str | None = None,
        tool_id: str | None = None,
        available_only: bool = False,
    ):
        require_local_request(request)
        return await run_in_threadpool(
            list_matos_tools,
            family=family,
            kind=kind,
            tool_id=tool_id,
            available_only=available_only,
        )

    @router.get("/tools/{tool}")
    async def matos_tool_detail(tool: str, request: Request):
        require_local_request(request)
        try:
            return await run_in_threadpool(describe_matos_tool, tool)
        except MatOSToolNotFound as exc:
            raise HTTPException(404, str(exc)) from None

    @router.post("/tools/{tool}/run")
    async def matos_tool_run(tool: str, request: Request, timeout_seconds: float | None = None):
        require_local_request(request)
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(422, "Request body must be a JSON object") from None
        if not isinstance(payload, dict):
            raise HTTPException(422, "Request body must be a JSON object")
        try:
            return await run_in_threadpool(run_matos_tool, tool, payload, timeout_seconds=timeout_seconds)
        except MatOSToolNotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except MatOSInputError as exc:
            raise HTTPException(422, str(exc)) from None

    return router
