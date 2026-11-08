"""Regression test: a rejected restore must not replace the current workflow."""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from materials_quality.agent.workflow_api import create_workflow_router
from materials_quality.agent.workflow_files import WorkflowFileStore

CATALOG = {
    "materials_analysis": {
        "InstalledNode": {
            "template": {"code": {"value": "trusted-code"}, "ui_mode": {"value": "form", "show": True}},
            "outputs": [],
        }
    }
}


def _flow(flow_id, name, nodes):
    return {"id": flow_id, "name": name, "data": {"nodes": nodes, "edges": []}}


def test_rejected_restore_keeps_the_current_workflow(tmp_path):
    store = WorkflowFileStore(tmp_path)
    flow_id = str(uuid.uuid4())
    old_flow = _flow(
        flow_id,
        "old",
        [{"id": "n1", "data": {"type": "InstalledNode", "node": {"template": {"code": {"value": "old"}}}}}],
    )
    current_flow = _flow(flow_id, "current", [])
    store.save(old_flow, create_only=True)
    store.save(current_flow)
    revision = next(row["revision"] for row in store.history(flow_id) if row["name"] == "old")

    # The component used by the historical revision is no longer installed, so
    # the restore must be refused without touching the saved workflow.
    app = FastAPI()
    app.include_router(create_workflow_router(store, component_catalog=lambda: {}))
    client = TestClient(app)
    response = client.post(f"/api/v1/flows/{flow_id}/restore", json={"revision": revision})

    assert response.status_code == 422, response.text
    saved = store.read(flow_id)[0]
    assert saved == current_flow
