"""Boundary regression: project file upload must validate filenames instead of crashing."""

import uuid

import pytest
from fastapi.testclient import TestClient

from materials_quality.agent.server import create_app


@pytest.fixture
def upload_client(tmp_path):
    for name in ("workflows", "components", "frontend/assets"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "frontend" / "index.html").write_text("StudyUI", encoding="utf-8")
    app = create_app(
        tmp_path / "agent.sqlite3", tmp_path / "workflows", tmp_path / "components", tmp_path / "frontend"
    )
    harness = app.state.harness
    project = harness.store.create_project("P")
    flow = {"id": str(uuid.uuid4()), "name": "f", "folder_id": project, "data": {"nodes": [], "edges": []}}
    harness.langflow.store.save(flow, create_only=True)
    with TestClient(app, base_url="http://127.0.0.1:7880", raise_server_exceptions=False) as client:
        yield client, flow["id"]


@pytest.mark.parametrize("filename", ["a" * 400, "a" * 181, "相" * 200 + ".csv"])
def test_workbench_upload_rejects_overlong_or_control_filenames(upload_client, filename):
    client, flow_id = upload_client
    response = client.post(
        f"/canvas/api/v1/files/upload/{flow_id}",
        files={"file": (filename, b"a,b\n1,2\n", "text/csv")},
    )
    assert response.status_code == 422, (filename, response.status_code, response.text)


def test_workbench_upload_accepts_a_normal_filename(upload_client):
    client, flow_id = upload_client
    response = client.post(
        f"/canvas/api/v1/files/upload/{flow_id}",
        files={"file": ("measurements.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["file_path"].endswith("_measurements.csv")
