"""LFX v2 workflow host that reads every graph from the local JSON repository."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request
from lfx.load import aload_flow_from_json
from lfx.workflow.host import ResolvedFlow, WorkflowHostBase
from lfx.workflow.router import create_workflow_router

from .workflow_files import WorkflowFileStore


class FileWorkflowHost(WorkflowHostBase):
    """Single-workspace host with no Langflow user, database, or login dependency."""

    supports_request_overrides = True

    def __init__(self, store: WorkflowFileStore, permission_store=None, component_catalog=None):
        self.store = store
        self.permission_store = permission_store
        self.component_catalog = component_catalog

    async def authorize(self, caller, flow: ResolvedFlow, action):
        if self.permission_store is None:
            return
        flow_data, _ = self.store.read(flow.flow_id)
        decision = self.permission_store.authorize(
            project_id=flow_data.get("folder_id"), action="workflow.run", task_authorized=True
        )
        if not decision["allowed"]:
            raise HTTPException(
                status_code=403,
                detail=decision.get("reason") or "此权限档位要求通过 StudyUI 审批卡片批准本次操作。",
            )
        if any(
            node.get("data", {}).get("type") == "StudyUIAIAnalysis"
            for node in flow_data.get("data", {}).get("nodes", [])
            if isinstance(node, dict)
        ):
            raise HTTPException(
                status_code=403,
                detail="AI 分析会将上游数据发送给模型；请在 StudyUI 对话中申请并批准本次运行。",
            )

    async def resolve_caller(self, request: Request):
        payload = await request.json()
        unsupported = [field for field in ("files",) if payload.get(field)]
        if unsupported:
            raise HTTPException(
                status_code=422, detail={"error": "Unsupported request fields", "fields": unsupported}
            )
        start, stop = payload.get("start_component_id"), payload.get("stop_component_id")
        if start and stop:
            raise HTTPException(status_code=422, detail="Choose either a start or stop component")
        return {
            "data": payload.get("data"),
            "tweaks": payload.get("tweaks") or {},
            "start": start,
            "stop": stop,
        }

    async def get_flow(self, flow_id: str, caller) -> ResolvedFlow:
        try:
            canonical = str(uuid.UUID(flow_id))
        except ValueError:
            raise HTTPException(status_code=404, detail="Workflow not found") from None
        try:
            flow, _ = self.store.read(canonical)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Workflow not found") from None
        if self.component_catalog is not None:
            from .workflow import sanitize_installed_components

            try:
                flow = sanitize_installed_components(flow, self.component_catalog())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
        caller = caller or {}
        if caller.get("data") is not None:
            flow = {**flow, "data": caller["data"]}
        graph = await aload_flow_from_json(flow, tweaks=caller.get("tweaks") or None)
        start, stop = caller.get("start"), caller.get("stop")
        if start or stop:
            requested = start or stop
            if requested not in {vertex.id for vertex in graph.vertices}:
                raise HTTPException(status_code=422, detail="Component not found in workflow")
            original_prepare = graph.prepare

            def prepare_selected(*args, **kwargs):
                return original_prepare(start_component_id=start, stop_component_id=stop)

            graph.prepare = prepare_selected
        return ResolvedFlow(flow_id=canonical, graph=graph, session_id_default=canonical)


def create_file_execution_router(store: WorkflowFileStore, permission_store=None, component_catalog=None):
    return create_workflow_router(
        FileWorkflowHost(store, permission_store, component_catalog), developer_api_guard=False
    )
