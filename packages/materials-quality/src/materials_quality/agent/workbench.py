"""StudyUI's local file-backed canvas service. No Langflow backend is imported."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock

from .file_workflow_client import FileWorkflowClient
from .permissions import PermissionStore
from .workflow_api import create_workflow_router
from .workflow_files import WorkflowFileStore
from .workflow_host import create_file_execution_router


def create_app(root: Path, components: Path, frontend: Path) -> FastAPI:
    root, components, frontend = root.resolve(), components.resolve(), frontend.resolve()
    store = WorkflowFileStore(root)
    client = FileWorkflowClient(root, components)
    permissions = PermissionStore(root.parent / ".demo-runtime" / "studyui-settings.json")
    workspace_file = root.parent / "workspace.json"
    lock = FileLock(str(workspace_file) + ".lock")

    def read_workspace():
        if workspace_file.exists():
            return json.loads(workspace_file.read_text(encoding="utf-8"))
        flows = store.list()
        groups = sorted({flow.get("folder_id") for flow in flows if flow.get("folder_id")})
        owned = [
            group
            for group in groups
            if any(flow.get("folder_id") == group and flow.get("user_id") for flow in flows)
        ]
        groups = owned or groups or [str(uuid.uuid4())]
        return {
            "projects": [
                {
                    "id": group,
                    "name": "Research Project" if i == 0 else "Project " + str(i + 1),
                    "description": "",
                    "parent_id": None,
                }
                for i, group in enumerate(groups)
            ],
            "variables": [],
        }

    def write_workspace(data):
        workspace_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=workspace_file.parent, suffix=".tmp", delete=False) as out:
            temp = out.name
            out.write((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, workspace_file)

    # The legacy owner field is used only once to identify the imported project.
    # Persist its identity before editing workflows removes that field.
    with lock:
        if not workspace_file.exists():
            write_workspace(read_workspace())

    app = FastAPI(title="StudyUI Workbench")
    app.state.store = store
    app.state.permissions = permissions

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = urlsplit("http://" + request.headers.get("host", "")).hostname
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"detail": "Local workbench only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"detail": "Cross-origin requests are not accepted"}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    @app.get("/health_check")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/version")
    async def version():
        return {"version": "1.13.0", "main_version": "1.13.0", "package": "StudyUI"}

    @app.get("/api/v1/config")
    async def config():
        return {
            "type": "full",
            "feature_flags": {},
            "event_delivery": "streaming",
            "max_file_size_upload": 100,
            "serialization_max_items_length": 1000,
            "serialization_max_text_length": 6000,
            "auto_saving": True,
            "auto_saving_interval": 1000,
            "health_check_max_retries": 5,
            "authz_enabled": False,
            "allow_custom_components": False,
            "catalog_governance_enabled": True,
            "substitute_outdated_component_code": False,
            "blocked_component_types": [],
            "default_folder_name": "Research Project",
            "hide_starter_projects": True,
            "embedded_mode": True,
            "hide_logout_button": True,
            "hide_new_project_button": True,
            "hide_getting_started_progress": True,
            "a2a_enabled": False,
            "agentic_experience": False,
            "enable_extension_reload": False,
            "frontend_timeout": 120,
        }

    @app.get("/api/v1/all")
    async def catalog():
        # The canvas catalog contains only explicitly installed StudyUI components.
        # LFX remains the graph/runtime engine; its stock node library is not exposed.
        return client.component_catalog()

    @app.get("/api/v1/projects/")
    async def projects():
        return [{**p, "is_owner": True} for p in read_workspace()["projects"]]

    @app.get("/api/v1/projects/{project_id}")
    async def project(
        project_id: str,
        page: int = 1,
        size: int = 10,
        components_only: bool = False,
        is_component: bool | None = None,
        is_flow: bool | None = None,
        search: str = "",
    ):
        p = next((p for p in read_workspace()["projects"] if p["id"] == project_id), None)
        if p is None:
            raise HTTPException(404, "Project not found")
        want_components = is_component if is_component is not None else components_only
        rows = [
            {**f, "user_id": None}
            for f in store.list()
            if f.get("folder_id") == project_id
            and bool(f.get("is_component")) == want_components
            and (not search or search.casefold() in str(f.get("name", "")).casefold())
        ]
        rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
        page, size = max(1, page), max(1, min(size, 100))
        return {
            **p,
            "flows": {
                "items": rows[(page - 1) * size : page * size],
                "total": len(rows),
                "page": page,
                "size": size,
                "pages": math.ceil(len(rows) / size),
            },
            "components": [],
        }

    @app.post("/api/v1/projects/", status_code=201)
    async def add_project(request: Request):
        data = await request.json()
        p = {
            "id": str(uuid.uuid4()),
            "name": str(data.get("name", "Research Project")),
            "description": str(data.get("description", "")),
            "parent_id": None,
        }
        with lock:
            workspace = read_workspace()
            workspace["projects"].append(p)
            write_workspace(workspace)
        return p

    @app.patch("/api/v1/projects/{project_id}")
    async def edit_project(project_id: str, request: Request):
        data = await request.json()
        with lock:
            workspace = read_workspace()
            p = next((p for p in workspace["projects"] if p["id"] == project_id), None)
            if p is None:
                raise HTTPException(404, "Project not found")
            for key in ("name", "description"):
                if key in data:
                    p[key] = str(data[key])
            write_workspace(workspace)
        return p

    @app.delete("/api/v1/projects/{project_id}")
    async def delete_project(project_id: str):
        raise HTTPException(403, "Project deletion requires a one-shot approval in the StudyUI conversation.")

    @app.get("/api/v1/variables/")
    async def variables():
        return read_workspace()["variables"]

    @app.get("/api/v1/builds")
    async def builds():
        return []

    @app.get("/api/v1/flows/{flow_id}/note_translations")
    async def note_translations(flow_id: str):
        return {}

    @app.get("/api/v1/store/check/")
    async def store_check():
        return {"enabled": False}

    @app.get("/api/v1/models")
    async def models():
        return []

    @app.get("/api/v1/models/enabled_models")
    async def enabled_models():
        return {"enabled_models": {}}

    @app.get("/api/v1/monitor/messages/sessions")
    @app.get("/api/v2/mcp/servers")
    @app.get("/api/v2/workflows/pending")
    @app.get("/api/v2/files")
    async def empty_collection():
        return []

    @app.get("/api/v1/flows/{flow_id}/events")
    async def flow_events(flow_id: str):
        return {"events": [], "settled": True}

    @app.get("/api/v1/monitor/builds")
    async def monitor_builds():
        return {"vertex_builds": {}}

    @app.post("/api/v1/custom_component/update")
    async def update_component(request: Request):
        raise HTTPException(
            403,
            "StudyUI only loads signed-in-repository scientific components; custom runtime code is disabled.",
        )

    @app.post("/api/v1/files/upload/{flow_id}", status_code=201)
    async def upload_flow_file(flow_id: uuid.UUID, request: Request):
        try:
            flow, _ = store.read(str(flow_id))
        except FileNotFoundError:
            raise HTTPException(404, "Workflow not found") from None
        decision = permissions.authorize(
            project_id=flow.get("folder_id"), action="workflow.edit", task_authorized=True
        )
        if not decision["allowed"]:
            raise HTTPException(403, decision.get("reason") or "当前权限档位不允许上传项目文件。")
        form = await request.form()
        uploaded = form.get("file")
        if uploaded is None or not getattr(uploaded, "filename", None):
            raise HTTPException(422, "File required")
        name = Path(uploaded.filename).name
        if name in {"", ".", ".."}:
            raise HTTPException(422, "Invalid file name")
        directory = root.parent / "data" / str(flow_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (str(uuid.uuid4()) + "_" + name)
        if not target.resolve().is_relative_to(directory.resolve()):
            raise HTTPException(422, "Invalid file path")
        total = 0
        try:
            with target.open("xb") as out:
                while chunk := await uploaded.read(1024 * 1024):
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise HTTPException(413, "File exceeds 100 MB")
                    out.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {"flowId": str(flow_id), "file_path": str(target.resolve())}

    app.include_router(
        create_workflow_router(
            store, permission_store=permissions, component_catalog=client.component_catalog
        )
    )
    app.include_router(
        create_file_execution_router(
            store, permission_store=permissions, component_catalog=client.component_catalog
        ),
        prefix="/api/v2",
    )
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/{path:path}")
    async def static(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        target = (frontend / path).resolve()
        if target.is_relative_to(frontend) and target.is_file():
            return FileResponse(target)
        return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7880)
    parser.add_argument("--workflows", type=Path, required=True)
    parser.add_argument("--components", type=Path, required=True)
    parser.add_argument("--frontend", type=Path, required=True)
    args = parser.parse_args()
    uvicorn.run(create_app(args.workflows, args.components, args.frontend), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
