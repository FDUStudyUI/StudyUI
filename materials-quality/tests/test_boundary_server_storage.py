"""Boundary regression: persistence writes are atomic-clean; corrupt catalogs raise actionable errors."""

import json
import os

import pytest
from fastapi.testclient import TestClient

import materials_quality.agent.store as store_module
import materials_quality.agent.workbench as workbench_module
from materials_quality.agent.store import SessionStore


class _FakeHarnessStore:
    def __init__(self):
        self.events = []

    def has_session(self, session_id):
        return True

    def session_context(self, session_id):
        return {"project_id": "p"}

    def append_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


class _FakePermissions:
    def get_preset(self, project_id):
        return "project_collaboration"


def _workspace_file(tmp_path):
    path = tmp_path / "workspace.json"
    path.write_text('{"projects": [], "workspaces": [], "variables": []}', encoding="utf-8")
    return path


def test_store_workspace_write_failure_leaves_no_temp_file(tmp_path, monkeypatch):
    workspace_file = _workspace_file(tmp_path)
    store = SessionStore(tmp_path / "db.sqlite3", workspace_file=workspace_file)

    def boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(store_module.os, "replace", boom)
    with pytest.raises(OSError):
        store.create_project("New project")

    assert list(tmp_path.glob("*.tmp")) == []
    assert json.loads(workspace_file.read_text(encoding="utf-8"))["projects"] == []


def test_workbench_workspace_write_failure_leaves_no_temp_file(tmp_path, monkeypatch):
    for name in ("workflows", "components", "frontend/assets"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "frontend" / "index.html").write_text("StudyUI", encoding="utf-8")
    app = workbench_module.create_app(tmp_path / "workflows", tmp_path / "components", tmp_path / "frontend")
    workspace_file = tmp_path / "workspace.json"
    before = workspace_file.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/projects/", json={"name": "New project"}
    )

    assert response.status_code == 500, response.text
    assert list(tmp_path.glob("*.tmp")) == []
    assert workspace_file.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "broken",
    [
        "{not json",
        '{"projects": null, "workspaces": [], "variables": []}',
        '{"projects": [{"id": "p"}], "workspaces": [], "variables": []}',
        '{"projects": [], "workspaces": "nope", "variables": []}',
    ],
)
def test_corrupt_workspace_catalog_raises_actionable_error(tmp_path, broken):
    workspace_file = tmp_path / "workspace.json"
    workspace_file.write_text(broken, encoding="utf-8")
    store = SessionStore(tmp_path / "db.sqlite3", workspace_file=workspace_file)

    with pytest.raises(ValueError, match="workspace|工作区|目录"):
        store.list_projects()


def test_workbench_reports_corrupt_workspace_catalog_as_clear_error(tmp_path):
    for name in ("workflows", "components", "frontend/assets"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "frontend" / "index.html").write_text("StudyUI", encoding="utf-8")
    app = workbench_module.create_app(tmp_path / "workflows", tmp_path / "components", tmp_path / "frontend")
    (tmp_path / "workspace.json").write_text("{broken", encoding="utf-8")

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/projects/")

    assert response.status_code == 500
    assert "工作区" in response.text or "workspace" in response.text.casefold()
