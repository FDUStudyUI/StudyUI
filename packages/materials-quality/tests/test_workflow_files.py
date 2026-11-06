import json
import uuid

import pytest

from materials_quality.agent.workflow_files import WorkflowConflictError, WorkflowFileStore


def test_roundtrip_and_conflicting_update(tmp_path):
    store = WorkflowFileStore(tmp_path)
    flow = {"id": str(uuid.uuid4()), "name": "光谱", "data": {"nodes": [], "edges": []}}
    revision = store.save(flow, create_only=True)
    assert store.read(flow["id"]) == (flow, revision)
    updated = {**flow, "name": "更新"}
    store.save(updated, expected_revision=revision)
    with pytest.raises(WorkflowConflictError):
        store.save(flow, expected_revision=revision)
    assert store.list() == [updated]


def test_snapshot_import_does_not_overwrite(tmp_path):
    source = tmp_path / "snapshot"
    source.mkdir()
    flow = {"id": str(uuid.uuid4()), "name": "paper", "data": {"nodes": [], "edges": []}}
    (source / (flow["id"] + ".json")).write_text(json.dumps(flow), encoding="utf-8")
    (source / "manifest.json").write_text(json.dumps({"flows": [{"id": flow["id"]}]}), encoding="utf-8")
    store = WorkflowFileStore(tmp_path / "workflows")
    assert store.import_snapshot(source) == [flow["id"]]
    with pytest.raises(FileExistsError):
        store.import_snapshot(source)
    assert store.read(flow["id"])[0] == flow


def test_rejects_invalid_id_and_missing_data(tmp_path):
    store = WorkflowFileStore(tmp_path)
    with pytest.raises(ValueError):
        store.read("../outside")
    with pytest.raises(ValueError):
        store.save({"id": str(uuid.uuid4()), "name": "bad"})


def test_file_executor_passes_json_to_lfx_without_http(tmp_path, monkeypatch):
    import lfx.load

    from materials_quality.agent.workflow_executor import FileWorkflowExecutor

    store = WorkflowFileStore(tmp_path)
    flow = {"id": str(uuid.uuid4()), "name": "local", "data": {"nodes": [], "edges": []}}
    revision = store.save(flow)
    calls = []

    def run(payload, **kwargs):
        calls.append((payload, kwargs))
        return [{"result": "ok"}]

    monkeypatch.setattr(lfx.load, "run_flow_from_json", run)
    result = FileWorkflowExecutor(store).run(flow["id"], tweaks={"node": {"value": 1}})
    assert calls[0][0] == flow
    assert calls[0][1]["tweaks"] == {"node": {"value": 1}}
    assert result == {"flow_id": flow["id"], "revision": revision, "outputs": [{"result": "ok"}]}


def test_file_api_reads_edits_and_runs_without_login(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from materials_quality.agent.workflow_api import create_workflow_router
    from materials_quality.agent.workflow_executor import FileWorkflowExecutor

    store = WorkflowFileStore(tmp_path)
    app = FastAPI()
    app.include_router(create_workflow_router(store))
    monkeypatch.setattr(
        FileWorkflowExecutor, "run", lambda self, flow_id, **kw: {"flow_id": flow_id, "outputs": ["ok"]}
    )
    client = TestClient(app)
    flow_id = str(uuid.uuid4())
    response = client.post(
        "/api/v1/flows/", json={"id": flow_id, "name": "initial", "data": {"nodes": [], "edges": []}}
    )
    assert response.status_code == 201
    read = client.get("/api/v1/flows/" + flow_id)
    assert read.status_code == 200
    revision = read.headers["etag"]
    changed = client.patch(
        "/api/v1/flows/" + flow_id, headers={"If-Match": revision}, json={"name": "edited"}
    )
    assert changed.status_code == 200
    assert store.read(flow_id)[0]["name"] == "edited"
    stale = client.patch("/api/v1/flows/" + flow_id, headers={"If-Match": revision}, json={"name": "stale"})
    assert stale.status_code == 409
    run = client.post("/api/v1/run/" + flow_id, json={"input_value": ""})
    assert run.status_code == 200 and run.json()["outputs"] == ["ok"]
    download = client.post("/api/v1/flows/download/", json=[flow_id])
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert json.loads(archive.read(flow_id + ".json"))["name"] == "edited"
    deleted = client.request("DELETE", "/api/v1/flows/", json=[flow_id])
    assert deleted.status_code == 200 and not (tmp_path / (flow_id + ".json")).exists()
    assert list((tmp_path / ".trash").glob(flow_id + "-*.json"))


def test_file_executor_serializes_lfx_table(tmp_path, monkeypatch):
    import lfx.load
    from lfx.schema.dataframe import Table
    from pydantic import BaseModel, ConfigDict

    from materials_quality.agent.workflow_executor import FileWorkflowExecutor

    class Result(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        table: Table

    store = WorkflowFileStore(tmp_path)
    flow = {"id": str(uuid.uuid4()), "name": "table", "data": {"nodes": [], "edges": []}}
    store.save(flow)
    monkeypatch.setattr(
        lfx.load, "run_flow_from_json", lambda *args, **kwargs: [Result(table=Table([{"x": 1}]))]
    )
    result = FileWorkflowExecutor(store).run(flow["id"])
    assert result["outputs"] == [{"table": [{"x": 1}]}]


def test_concurrent_editors_do_not_overwrite_each_other(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    first = WorkflowFileStore(tmp_path)
    second = WorkflowFileStore(tmp_path)
    flow = {"id": str(uuid.uuid4()), "name": "initial", "data": {"nodes": [], "edges": []}}
    revision = first.save(flow)
    barrier = Barrier(2)

    def write(store, name):
        barrier.wait()
        try:
            store.save({**flow, "name": name}, expected_revision=revision)
            return "saved"
        except WorkflowConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: write(*pair), [(first, "one"), (second, "two")]))
    assert sorted(results) == ["conflict", "saved"]
    assert first.read(flow["id"])[0]["name"] in {"one", "two"}


def test_v2_file_host_reloads_saved_graph_and_requires_no_user(tmp_path, monkeypatch):
    from materials_quality.agent import workflow_host
    from materials_quality.agent.workflow_host import FileWorkflowHost

    store = WorkflowFileStore(tmp_path)
    flow = {"id": str(uuid.uuid4()), "name": "initial", "data": {"nodes": [], "edges": []}}
    revision = store.save(flow)
    seen = []

    async def load(payload, **kwargs):
        seen.append(payload)
        return {"graph_name": payload["name"]}

    monkeypatch.setattr(workflow_host, "aload_flow_from_json", load)
    host = FileWorkflowHost(store)
    import asyncio

    class FakeRequest:
        async def json(self):
            return {}

    assert asyncio.run(host.resolve_caller(FakeRequest())) == {
        "data": None,
        "tweaks": {},
        "start": None,
        "stop": None,
    }
    first = asyncio.run(host.get_flow(flow["id"], None))
    assert first.graph == {"graph_name": "initial"}
    store.save({**flow, "name": "changed"}, expected_revision=revision)
    second = asyncio.run(host.get_flow(flow["id"], None))
    assert second.graph == {"graph_name": "changed"}
    assert len(seen) == 2


def test_file_client_uses_local_catalog_and_detects_stale_edit(tmp_path, monkeypatch):
    from materials_quality.agent.file_workflow_client import FileWorkflowClient

    client = FileWorkflowClient(
        tmp_path / "workflows", tmp_path, catalog_loader=lambda: {"Materials": {"A": {}}}
    )
    flow = {"id": str(uuid.uuid4()), "name": "local", "data": {"nodes": [], "edges": []}}
    client.store.save(flow)
    assert client.list_flows() == [flow]
    candidate = client.get_flow(flow["id"])
    assert client.component_catalog() == {"Materials": {"A": {}}}
    candidate["name"] = "changed"
    client.update_flow(flow["id"], candidate)
    assert client.get_flow(flow["id"])["name"] == "changed"
    client.store.save({**flow, "name": "external"})
    with pytest.raises(WorkflowConflictError):
        client.update_flow(flow["id"], candidate)
    assert client.store.read(flow["id"])[0]["name"] == "external"


def test_workspace_keeps_imported_project_after_legacy_owner_is_removed(tmp_path):
    from fastapi.testclient import TestClient

    from materials_quality.agent.workbench import create_app

    root = tmp_path / "workflows"
    frontend = tmp_path / "ui"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("StudyUI", encoding="utf-8")
    components = tmp_path / "components"
    components.mkdir()
    store = WorkflowFileStore(root)
    owned_id, example_id = str(uuid.uuid4()), str(uuid.uuid4())
    flow = {
        "id": str(uuid.uuid4()),
        "folder_id": owned_id,
        "user_id": str(uuid.uuid4()),
        "name": "research",
        "data": {"nodes": [], "edges": []},
    }
    example = {
        "id": str(uuid.uuid4()),
        "folder_id": example_id,
        "name": "example",
        "data": {"nodes": [], "edges": []},
    }
    store.save(flow)
    store.save(example)
    client = TestClient(create_app(root, components, frontend))
    assert [p["id"] for p in client.get("/api/v1/projects/").json()] == [owned_id]
    assert client.patch("/api/v1/flows/" + flow["id"], json={"name": "edited"}).status_code == 200
    restarted = TestClient(create_app(root, components, frontend))
    assert [p["id"] for p in restarted.get("/api/v1/projects/").json()] == [owned_id]
    assert restarted.get("/api/v1/projects/" + owned_id).json()["flows"]["items"][0]["name"] == "edited"
    assert (
        restarted.get("/api/v1/projects/" + owned_id, params={"search": "missing"}).json()["flows"]["total"]
        == 0
    )
    assert restarted.get("/api/v1/flows/" + flow["id"] + "/version-state").status_code == 200
    assert restarted.get("/api/v1/auto_login").status_code == 404
    assert restarted.delete("/api/v1/projects/" + owned_id).status_code == 403
    assert [p["id"] for p in restarted.get("/api/v1/projects/").json()] == [owned_id]
    assert restarted.get("/api/v1/flows/" + flow["id"]).status_code == 200


def test_canvas_refreshes_only_trusted_scientific_component_forms(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from materials_quality.agent.file_workflow_client import FileWorkflowClient
    from materials_quality.agent.workbench import create_app

    code = 'class ScienceIoTableImport:\n    ui_operation_key = "io.table_import"\n'
    template = {
        "code": {"value": code},
        "cfg_path": {"value": "", "show": True},
        "cfg_sheet": {"value": "", "show": True},
        "ui_mode": {"value": "form", "show": True},
    }
    monkeypatch.setattr(
        FileWorkflowClient,
        "component_catalog",
        lambda self: {"materials_sources": {"ScienceIoTableImport": {"template": template, "outputs": []}}},
    )
    frontend = tmp_path / "ui"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("StudyUI", encoding="utf-8")
    components = tmp_path / "components"
    components.mkdir()
    client = TestClient(create_app(tmp_path / "workflows", components, frontend))
    payload = {
        "code": code,
        "frontend_node": {"metadata": {"component_class_name": "ScienceIoTableImport"}},
        "template": template,
        "field": "cfg_path",
        "field_value": "data.csv",
    }
    result = client.post("/api/v1/custom_component/update", json=payload)
    assert result.status_code == 200
    assert result.json()["template"]["code"]["value"] == code
    payload["code"] = code + "print('untrusted')"
    assert client.post("/api/v1/custom_component/update", json=payload).status_code == 403


def test_canvas_shows_connected_advanced_input_without_changing_saved_graph():
    from materials_quality.agent.workflow_api import _canvas_visible_flow

    field = {"advanced": True, "show": False, "value": None}
    flow = {
        "data": {
            "nodes": [{"id": "target", "data": {"node": {"template": {"input_data": field}}}}],
            "edges": [{"target": "target", "targetHandle": '{"fieldName":"input_data"}'}],
        }
    }
    visible = _canvas_visible_flow(flow)
    projected = visible["data"]["nodes"][0]["data"]["node"]["template"]["input_data"]
    assert projected["advanced"] is False and projected["show"] is True
    assert field["advanced"] is True and field["show"] is False


def test_agent_and_canvas_share_projects_and_preserve_existing_sessions(tmp_path):
    from fastapi.testclient import TestClient

    from materials_quality.agent.store import SessionStore
    from materials_quality.agent.workbench import create_app

    root = tmp_path / "workflows"
    frontend = tmp_path / "ui"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("StudyUI", encoding="utf-8")
    components = tmp_path / "components"
    components.mkdir()
    database = tmp_path / "sessions.db"
    old = SessionStore(database)
    old_project = old.create_project("Existing discussion")
    session = old.create_session("Existing session", old_project)
    canvas = TestClient(create_app(root, components, frontend))
    shared = SessionStore(database, workspace_file=tmp_path / "workspace.json", workflow_root=root)
    assert old_project in {p["id"] for p in shared.list_projects()}
    assert old_project in {p["id"] for p in canvas.get("/api/v1/projects/").json()}
    new_project = shared.create_project("Shared project")
    assert new_project in {p["id"] for p in canvas.get("/api/v1/projects/").json()}
    assert canvas.patch("/api/v1/projects/" + new_project, json={"name": "Renamed"}).status_code == 200
    assert next(p for p in shared.list_projects() if p["id"] == new_project)["title"] == "Renamed"
    shared.delete_project(old_project)
    assert next(s for s in shared.list_sessions() if s["id"] == session)["project_id"] is None
    assert old_project not in {p["id"] for p in canvas.get("/api/v1/projects/").json()}


@pytest.mark.parametrize("changed_field", ["name", "folder_id"])
def test_external_run_rejects_a_replaced_snapshot(tmp_path, monkeypatch, changed_field):
    import lfx.load

    from materials_quality.agent.file_workflow_client import FileWorkflowClient
    from materials_quality.agent.workflow import flow_digest

    client = FileWorkflowClient(tmp_path / "flows", tmp_path / "components", catalog_loader=dict)
    first = client.create_flow("Approved graph", project_id=str(uuid.uuid4()))
    replacement = {**first, changed_field: str(uuid.uuid4())}
    client.store.save(replacement)

    def unexpected_run(*args, **kwargs):
        pytest.fail("The changed graph must not reach the runtime with an old approval.")

    monkeypatch.setattr(lfx.load, "run_flow_from_json", unexpected_run)
    with pytest.raises(ValueError, match="审批"):
        client.run_flow(
            first["id"],
            external_data_approved=True,
            expected_digest=flow_digest(first),
            expected_project_id=first["folder_id"],
        )


def test_external_run_uses_the_checked_snapshot(tmp_path, monkeypatch):
    import lfx.load

    from materials_quality.agent.execution_context import require_external_data_approval
    from materials_quality.agent.file_workflow_client import FileWorkflowClient
    from materials_quality.agent.workflow import flow_digest

    client = FileWorkflowClient(tmp_path / "flows", tmp_path / "components", catalog_loader=dict)
    original = client.create_flow("Approved graph", project_id=str(uuid.uuid4()))
    replacement = {**original, "name": "New unapproved graph"}

    def run(snapshot, **kwargs):
        client.store.save(replacement)
        assert snapshot == original
        require_external_data_approval()
        return ["ok"]

    monkeypatch.setattr(lfx.load, "run_flow_from_json", run)
    result = client.run_flow(
        original["id"],
        external_data_approved=True,
        expected_digest=flow_digest(original),
        expected_project_id=original["folder_id"],
    )
    assert result["outputs"] == ["ok"]
