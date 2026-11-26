"""Boundary regression: bulk workflow API operations must not mutate state on clean errors."""

import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from materials_quality.agent.workflow_api import create_workflow_router
from materials_quality.agent.workflow_files import WorkflowFileStore


def _client(tmp_path):
    store = WorkflowFileStore(tmp_path)
    app = FastAPI()
    app.include_router(create_workflow_router(store))
    return store, TestClient(app, raise_server_exceptions=False)


def test_upload_flows_validates_every_candidate_before_saving(tmp_path):
    store, client = _client(tmp_path)
    good = {"id": str(uuid.uuid4()), "name": "good", "data": {"nodes": [], "edges": []}}
    response = client.post(
        "/api/v1/flows/upload/",
        files={"f": ("flows.json", json.dumps([good, {"name": "bad"}]).encode(), "application/json")},
    )

    assert response.status_code == 422, response.text
    assert store.list() == []  # a rejected multi-flow upload must not keep the valid first entry


def test_upload_flows_rolls_back_when_a_later_save_fails(tmp_path, monkeypatch):
    store, client = _client(tmp_path)
    good = {"id": str(uuid.uuid4()), "name": "good", "data": {"nodes": [], "edges": []}}
    second = {"id": str(uuid.uuid4()), "name": "second", "data": {"nodes": [], "edges": []}}
    original_save = store.save
    calls = {"n": 0}

    def flaky_save(flow, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated disk failure")
        return original_save(flow, **kwargs)

    monkeypatch.setattr(store, "save", flaky_save)
    response = client.post(
        "/api/v1/flows/upload/",
        files={"f": ("flows.json", json.dumps([good, second]).encode(), "application/json")},
    )

    assert response.status_code == 500, response.text
    assert store.list() == []  # the first saved flow is rolled back
