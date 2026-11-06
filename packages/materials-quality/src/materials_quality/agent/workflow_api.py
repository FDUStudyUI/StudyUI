"""StudyUI file-backed workflow endpoints for integration with the canvas."""

from __future__ import annotations

import copy
import io
import json
import math
import uuid
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from .workflow_executor import FileWorkflowExecutor
from .workflow_files import WorkflowConflictError, WorkflowFileStore


def _canvas_visible_flow(flow):
    """Expose connected input handles in the canvas without editing the saved flow."""
    result = copy.deepcopy(flow)
    graph = result.get("data", {})
    nodes = {node.get("id"): node for node in graph.get("nodes", []) if isinstance(node, dict)}
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        handle = edge.get("data", {}).get("targetHandle")
        if not isinstance(handle, dict):
            try:
                handle = json.loads(edge.get("targetHandle", "{}"))
            except (TypeError, ValueError):
                continue
        target = nodes.get(edge.get("target"), {})
        fields = target.get("data", {}).get("node", {}).get("template", {})
        field = fields.get(handle.get("fieldName")) if isinstance(fields, dict) else None
        if isinstance(field, dict):
            field["advanced"] = False
            field["show"] = True
    return result


def create_workflow_router(
    store: WorkflowFileStore, permission_store=None, component_catalog=None, run_handler=None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def validate(flow):
        if component_catalog is not None:
            from .workflow import sanitize_installed_components

            try:
                normalized = sanitize_installed_components(flow, component_catalog())
                flow.clear()
                flow.update(normalized)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None

    executor = FileWorkflowExecutor(store, validator=validate)

    def authorize(project_id, action, *, task_authorized=True):
        if permission_store is None:
            return
        decision = permission_store.authorize(
            project_id=project_id, action=action, task_authorized=task_authorized
        )
        if not decision["allowed"]:
            detail = decision.get("reason") or (
                "此权限档位要求通过 StudyUI 审批卡片批准本次操作。"
                if decision.get("requires_approval")
                else "当前权限档位不允许此操作。"
            )
            raise HTTPException(status_code=403, detail=detail)

    async def existing_flow(flow_id):
        try:
            return (await run_in_threadpool(store.read, str(flow_id)))[0]
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Workflow not found") from None

    def public(flow, revision):
        return {**_canvas_visible_flow(flow), "version_token": revision, "user_id": None}

    @router.get("/flows/basic_examples/")
    async def basic_examples():
        return []

    @router.get("/flows/")
    async def list_flows(
        components_only: bool = False,
        get_all: bool = True,
        folder_id: str | None = None,
        page: int = 1,
        size: int = 10,
        header_flows: bool = False,
    ):
        rows = await run_in_threadpool(store.list)
        rows = [
            public(row, store.read(row["id"])[1])
            for row in rows
            if bool(row.get("is_component")) == components_only
            and (not folder_id or row.get("folder_id") == folder_id)
        ]
        if header_flows:
            rows = [{key: value for key, value in row.items() if key != "data"} for row in rows]
        if get_all:
            return rows
        page, size = max(1, page), max(1, min(100, size))
        return {
            "items": rows[(page - 1) * size : page * size],
            "total": len(rows),
            "page": page,
            "size": size,
            "pages": math.ceil(len(rows) / size),
        }

    @router.post("/flows/upload/", status_code=201)
    async def upload_flows(request: Request, folder_id: str | None = None):
        form = await request.form()
        folder_id = folder_id or form.get("folder_id")
        authorize(folder_id, "workflow.create")
        uploaded = []
        for item in form.values():
            if not hasattr(item, "read"):
                continue
            raw = await item.read(50_000_001)
            if len(raw) > 50_000_000:
                raise HTTPException(413, "Workflow file is too large")
            try:
                flow = json.loads(raw.decode("utf-8-sig"))
            except (ValueError, UnicodeError):
                raise HTTPException(422, "Invalid workflow JSON") from None
            candidates = flow if isinstance(flow, list) else [flow]
            for candidate in candidates:
                if not isinstance(candidate, dict) or not isinstance(candidate.get("data"), dict):
                    raise HTTPException(422, "Invalid workflow data")
                candidate = dict(candidate)
                candidate["id"] = str(uuid.uuid4())
                if folder_id:
                    candidate["folder_id"] = folder_id
                candidate.pop("user_id", None)
                candidate.pop("version_token", None)
                validate(candidate)
                revision = await run_in_threadpool(store.save, candidate, create_only=True)
                uploaded.append(public(candidate, revision))
        if not uploaded:
            raise HTTPException(422, "No workflow file supplied")
        return uploaded

    @router.delete("/flows/")
    async def delete_flows(request: Request):
        ids = await request.json()
        if not isinstance(ids, list) or not ids:
            raise HTTPException(422, "Workflow IDs are required")
        try:
            ids = list(dict.fromkeys(str(uuid.UUID(str(value))) for value in ids))
            for flow_id in ids:
                flow = await existing_flow(flow_id)
                authorize(flow.get("folder_id"), "workflow.delete")
            for flow_id in ids:
                await run_in_threadpool(store.delete, flow_id)
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid workflow ID") from None
        except FileNotFoundError:
            raise HTTPException(404, "Workflow not found") from None
        return {"message": "Workflows moved to recovery folder"}

    @router.post("/flows/download/")
    async def download_flows(request: Request):
        ids = await request.json()
        if not isinstance(ids, list) or not ids:
            raise HTTPException(422, "Workflow IDs are required")
        output = io.BytesIO()
        try:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for value in dict.fromkeys(ids):
                    flow_id = str(uuid.UUID(str(value)))
                    flow, _ = await run_in_threadpool(store.read, flow_id)
                    flow.pop("user_id", None)
                    archive.writestr(flow_id + ".json", json.dumps(flow, ensure_ascii=False, indent=2))
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid workflow ID") from None
        except FileNotFoundError:
            raise HTTPException(404, "Workflow not found") from None
        return Response(
            output.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="workflows.zip"'},
        )

    @router.get("/flows/{flow_id}")
    async def get_flow(flow_id: uuid.UUID, response: Response):
        try:
            flow, revision = await run_in_threadpool(store.read, str(flow_id))
            response.headers["ETag"] = '"' + revision + '"'
            return public(flow, revision)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Workflow not found") from None

    @router.get("/flows/{flow_id}/version-state")
    async def flow_version(flow_id: uuid.UUID):
        try:
            flow, revision = await run_in_threadpool(store.read, str(flow_id))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Workflow not found") from None
        return {
            "version_token": revision,
            "updated_at": flow.get("updated_at"),
            "last_modified_by": None,
            "last_modified_by_username": None,
        }

    @router.get("/flows/{flow_id}/history")
    async def flow_history(flow_id: uuid.UUID):
        try:
            await run_in_threadpool(store.read, str(flow_id))
            return {"items": await run_in_threadpool(store.history, str(flow_id))}
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Workflow not found") from None

    @router.post("/flows/{flow_id}/restore")
    async def restore_flow(flow_id: uuid.UUID, request: Request):
        body = await request.json()
        revision = body.get("revision") if isinstance(body, dict) else None
        try:
            flow, _ = await run_in_threadpool(store.read, str(flow_id))
            authorize(flow.get("folder_id"), "workflow.edit")
            flow = await run_in_threadpool(store.restore, str(flow_id), revision)
            validate(flow)
            return {**flow, "version_token": (await run_in_threadpool(store.read, str(flow_id)))[1]}
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Workflow revision not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @router.post("/flows/", status_code=201)
    async def create_flow(request: Request):
        flow = await request.json()
        if not isinstance(flow, dict):
            raise HTTPException(status_code=422, detail="Workflow must be an object")
        flow = dict(flow)
        flow.pop("user_id", None)
        flow.pop("version_token", None)
        flow.setdefault("id", str(uuid.uuid4()))
        flow.setdefault("data", {"nodes": [], "edges": []})
        flow.setdefault("name", "New workflow")
        flow.setdefault("is_component", False)
        flow.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        flow.setdefault("updated_at", flow["created_at"])
        authorize(flow.get("folder_id"), "workflow.create")
        validate(flow)
        try:
            revision = await run_in_threadpool(store.save, flow, create_only=True)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except FileExistsError:
            raise HTTPException(status_code=409, detail="Workflow already exists") from None
        return public(flow, revision)

    @router.patch("/flows/{flow_id}")
    async def update_flow(flow_id: uuid.UUID, request: Request, if_match: str | None = Header(default=None)):
        patch = await request.json()
        if not isinstance(patch, dict) or "id" in patch and str(patch["id"]) != str(flow_id):
            raise HTTPException(status_code=422, detail="Invalid workflow update")
        try:
            flow, current_revision = await run_in_threadpool(store.read, str(flow_id))
            authorize(flow.get("folder_id"), "workflow.edit")
            requested_revision = patch.pop("version_token", None)
            patch.pop("user_id", None)
            flow.update(patch)
            flow.pop("user_id", None)
            flow.pop("version_token", None)
            flow["updated_at"] = datetime.now(timezone.utc).isoformat()
            validate(flow)
            expected = if_match.strip('"') if if_match else requested_revision or current_revision
            revision = await run_in_threadpool(store.save, flow, expected_revision=expected)
            return public(flow, revision)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Workflow not found") from None
        except WorkflowConflictError:
            raise HTTPException(status_code=409, detail="Workflow was changed by another editor") from None
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @router.delete("/flows/{flow_id}")
    async def delete_flow(flow_id: uuid.UUID):
        try:
            flow = await existing_flow(str(flow_id))
            authorize(flow.get("folder_id"), "workflow.delete")
            await run_in_threadpool(store.delete, str(flow_id))
            return {"message": "Workflow moved to recovery folder"}
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Workflow not found") from None

    @router.post("/run/{flow_id}")
    async def run_flow(flow_id: uuid.UUID, request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="Run request must be an object")
        try:
            if run_handler is not None:
                result = await run_in_threadpool(run_handler, str(flow_id), payload)
                if not isinstance(result, dict):
                    raise HTTPException(
                        status_code=502, detail="StudyUI Agent returned an invalid run result"
                    )
                return result
            flow = await existing_flow(str(flow_id))
            authorize(flow.get("folder_id"), "workflow.run")
            if any(
                node.get("data", {}).get("type") == "StudyUIAIAnalysis"
                for node in flow.get("data", {}).get("nodes", [])
                if isinstance(node, dict)
            ):
                raise HTTPException(
                    status_code=403,
                    detail="AI 分析会将上游数据发送给模型；请在 StudyUI 对话中申请并批准本次运行。",
                )
            return await run_in_threadpool(
                executor.run,
                str(flow_id),
                input_value=payload.get("input_value", ""),
                tweaks=payload.get("tweaks"),
                output_type=payload.get("output_type", "any"),
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Workflow not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    return router
