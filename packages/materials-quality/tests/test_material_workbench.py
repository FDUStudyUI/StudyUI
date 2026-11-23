import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from materials_quality.agent.server import create_app
from materials_quality.science.catalog import component_class


@pytest.fixture
def workbench(tmp_path):
    (tmp_path / "front" / "assets").mkdir(parents=True)
    (tmp_path / "components").mkdir()
    app = create_app(tmp_path / "agent.db", tmp_path / "flows", tmp_path / "components", tmp_path / "front")
    harness = app.state.harness
    keys = [
        "io.table_import",
        "io.instrument_import",
        "preprocess.filter",
        "materials.mechanics",
        "materials.spectra",
        "materials.xrd",
        "viz.spectra",
        "export.table",
        "export.report",
    ]
    harness.langflow._catalog_loader = lambda: {
        "materials_protocols": {
            component_class(k)().name: component_class(k)().to_frontend_node()["data"]["node"] for k in keys
        }
    }
    harness.langflow._catalog = None
    project = harness.store.create_project("Materials")
    session = harness.new_session(project_id=project)
    harness.permissions.set_preset(project, "project_collaboration")
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        x = np.linspace(0, 0.02, 401)
        raw = (
            pd.DataFrame({"strain": x, "stress": np.where(x <= 0.001, 200000 * x, 199 + 1000 * x)})
            .to_csv(index=False)
            .encode()
        )
        uploaded = client.post(
            "/api/upload", content=raw, headers={"X-Filename": "curve.csv", "X-StudyUI-Session": session}
        ).json()
        yield app, client, session, project, uploaded["path"]


def test_upload_preview_check_and_build_work_without_model(workbench, monkeypatch):
    app, client, session, _, path = workbench
    monkeypatch.setattr(
        app.state.harness.model, "complete", lambda *a, **k: pytest.fail("Wizard invoked a model")
    )
    catalog = client.get("/api/material-tasks").json()
    assert len(catalog["tasks"]) == 3
    preview = client.post("/api/material-tasks/preview", json={"session_id": session, "path": path})
    assert preview.status_code == 200, preview.text
    assert preview.json()["row_count"] == 401
    assert len(preview.json()["preview"]) == 20
    assert [c["name"] for c in preview.json()["columns"]] == ["strain", "stress"]
    spec = {
        "task": "mechanics",
        "path": path,
        "x": "strain",
        "y": "stress",
        "x_unit": "fraction",
        "y_unit": "MPa",
        "fit_range": [0, 0.0008],
        "yield_offset": 0.002,
    }
    checked = client.post("/api/material-tasks/check", json={"session_id": session, "protocol": spec})
    assert checked.json()["status"] == "ready", checked.text
    created = client.post("/api/material-tasks/build", json={"session_id": session, "protocol": spec})
    assert created.status_code == 201, created.text
    flow = app.state.harness.langflow.get_flow(created.json()["flow_id"])
    assert flow["studyui_protocol"]["assessment"]["status"] == "ready"
    assert created.json()["url"].startswith("/canvas/flow/")


def test_method_information_is_collected_before_build(workbench):
    _, client, session, _, path = workbench
    checked = client.post(
        "/api/material-tasks/check",
        json={
            "session_id": session,
            "protocol": {
                "task": "mechanics",
                "path": path,
                "x": "strain",
                "y": "stress",
                "x_unit": "fraction",
                "y_unit": "MPa",
            },
        },
    )
    assert checked.status_code == 200
    assert checked.json()["status"] == "need_info"
    assert checked.json()["next_actions"]


def test_wizard_preserves_project_permission(workbench):
    app, client, session, project, path = workbench
    app.state.harness.permissions.set_preset(project, "read_only")
    result = client.post(
        "/api/material-tasks/build",
        json={"session_id": session, "protocol": {"task": "mechanics", "path": path}},
    )
    assert result.status_code == 403, result.text
    assert app.state.harness.langflow.list_flows() == []


def test_public_instrument_flow_reuses_completed_science_after_client_restart(workbench):
    import zipfile
    from pathlib import Path

    from materials_quality.agent.file_workflow_client import FileWorkflowClient
    from materials_quality.agent.run_bundle import replay_bundle

    app, client, session, _, _ = workbench
    result = client.post("/api/material-tasks/example", json={"session_id": session, "id": "xrd_graphite"})
    assert result.status_code == 201, result.text
    flow_id = result.json()["flow_id"]
    original = app.state.harness.langflow
    first = original.executor.run(flow_id)
    assert any(
        r["operation"] == "materials.xrd" and r["status"] == "computed" for r in first["checkpoints"]
    ), first["checkpoints"]
    restarted = FileWorkflowClient(
        original.store.root, original.components, catalog_loader=original._catalog_loader
    )
    second = restarted.executor.run(flow_id)
    assert any(
        r["operation"] == "materials.xrd" and r["status"] == "reused" for r in second["checkpoints"]
    ), second["checkpoints"]
    flow = restarted.get_flow(flow_id)
    assert flow["studyui_protocol"]["source"]["doi"] == "10.5281/zenodo.20032690"
    archive = Path(second["artifacts"][0]["path"])
    assert archive.is_file()
    bundle = archive.with_suffix("")
    with zipfile.ZipFile(archive) as zipped:
        assert "workflow.json" in zipped.namelist()
        assert "results/analysis_features.csv" in zipped.namelist()
        assert len(pd.read_csv(zipped.open("results/raw_table.csv"))) == flow["studyui_protocol"]["row_count"]
    replayed = replay_bundle(bundle)
    assert replayed["outputs"]
    (bundle / "inputs" / "raw.dat").write_text("10 1\n20 5\n30 1\n")
    with pytest.raises(ValueError, match="复现包文件不匹配"):
        replay_bundle(bundle)


def test_instrument_example_requires_project_write_permission(workbench):
    app, client, session, project, _ = workbench
    app.state.harness.permissions.set_preset(project, "read_only")
    result = client.post("/api/material-tasks/example", json={"session_id": session, "id": "xrd_graphite"})
    assert result.status_code == 403
    assert app.state.harness.langflow.list_flows() == []


def test_material_canvas_run_does_not_call_a_model(workbench, monkeypatch):
    app, client, session, _, _ = workbench
    result = client.post("/api/material-tasks/example", json={"session_id": session, "id": "xrd_calcite"})
    assert result.status_code == 201, result.text
    monkeypatch.setattr(
        app.state.harness.model, "complete", lambda *a, **k: pytest.fail("Canvas invoked a model")
    )
    # Exercise the same harness entry used by the canvas task API.
    run = app.state.harness.run_canvas_workflow(result.json()["flow_id"], session_id=session)
    assert run["task_status"] == "completed"
    assert any(a["name"].endswith(".zip") for a in run["artifacts"])


def test_chat_material_tool_compiles_same_native_protocol(workbench):
    app, _, session, _, path = workbench
    harness = app.state.harness

    class Model:
        calls = 0

        def complete(self, messages, tools, **kwargs):
            self.calls += 1
            if self.calls > 1:
                return {"content": "材料流程已保存，尚未运行。"}
            tool = next(t["function"] for t in tools if t["function"]["name"] == "build_material_workflow")
            assert "protocol" in tool["parameters"]["required"]
            assert "actions" not in tool["parameters"]["properties"]
            return {
                "tool_calls": [
                    {
                        "id": "material",
                        "function": {
                            "name": "build_material_workflow",
                            "arguments": json.dumps(
                                {
                                    "name": "拉伸",
                                    "rationale": "采用已确认参数",
                                    "protocol": {
                                        "task": "mechanics",
                                        "path": path,
                                        "x": "strain",
                                        "y": "stress",
                                        "x_unit": "fraction",
                                        "y_unit": "MPa",
                                        "fit_range": [0, 0.0008],
                                        "yield_offset": 0.002,
                                    },
                                }
                            ),
                        },
                    }
                ]
            }

    harness.model = Model()
    harness._custom_model = True
    result = harness.run_turn(session, "请创建拉伸分析工作流，先保存。")
    assert result["task_status"] == "completed"
    flows = harness.langflow.list_flows()
    assert len(flows) == 1
    assert harness.langflow.get_flow(flows[0]["id"])["studyui_protocol"]["id"] == "materials.mechanics"
    harness.permissions.set_preset(harness.store.session_context(session)["project_id"], "read_only")
    harness._turn_state.value = {"skill_preflight_complete": True}
    assert not harness._authorize_tool(session, "build_material_workflow", {}, "请创建流程")["allowed"]
