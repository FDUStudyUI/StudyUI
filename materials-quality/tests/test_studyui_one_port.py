import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from materials_quality.agent.server import create_app

REPO = Path(__file__).resolve().parents[2]


def _sidecar_app(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text(
        '<!doctype html><html><head><base href="/canvas/" />'
        "<title>StudyUI Workbench</title></head><body>Canvas</body></html>",
        encoding="utf-8",
    )
    return create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)


def test_sidecar_has_no_legacy_workbench_page(tmp_path):
    app = _sidecar_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["canvas_url"] == "/canvas"
        # The legacy workbench page was removed; only API/canvas remain on the sidecar.
        assert client.get("/").status_code == 404
        canvas = client.get("/canvas/")
        assert canvas.status_code == 200
        assert "StudyUI Workbench" in canvas.text
        assert client.get("/canvas/health_check").json() == {"status": "ok"}
        assert client.get("/canvas/api/v1/version").json()["package"] == "StudyUI"


def test_governance_apis_available_without_legacy_ui(tmp_path):
    app = _sidecar_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        scope = client.get("/api/governance/scope")
        assert scope.status_code == 200
        scope_data = scope.json()
        assert scope_data["summary"]["error_count"] == 0
        assert "StudyUI" in scope_data["markdown"]
        assert len(scope_data["workflows"]) >= 5
        assert len(scope_data["roles"]) >= 3

        evo = client.get("/api/governance/evolution")
        assert evo.status_code == 200
        evo_data = evo.json()
        assert evo_data["mode"] == "manual"
        assert evo_data["pending"] == []
        assert evo_data["applied"] == []

        collect = client.post("/api/governance/evolution/collect", json={})
        assert collect.status_code == 200
        collect_data = collect.json()
        assert "collected_items" in collect_data
        assert "proposed_patches" in collect_data

        missing_rb = client.post("/api/governance/evolution/nonexistent-patch/rollback", json={})
        assert missing_rb.status_code == 404

        from materials_quality.evolution.editor import KnowledgePatch

        harness = app.state.harness
        session_id = harness.new_session("治理回滚测试")
        k_node = sorted(harness.asset_graph.by_type("K"), key=lambda item: item.id)[0]
        patch = KnowledgePatch(
            patch_id="patch_test_rollback_1",
            target_asset_id=k_node.id,
            target_asset_type="K",
            field="known_limitations",
            operation="append_unique",
            values=("Test limitation from governance endpoint",),
            evidence_ids=("ev_test_1",),
            rationale="test rollback",
        )
        submitted = harness.evolution.submit_patch(
            patch, harness._mutable_asset_graph(), session_id=session_id
        )
        assert submitted["status"] == "pending_approval"
        harness.store.decide_approval(submitted["approval_id"], "approved")
        applied = harness.evolution.apply_approved_patch(patch.patch_id, harness._mutable_asset_graph())
        assert applied["status"] == "applied"

        evo_after_apply = client.get("/api/governance/evolution").json()
        assert [p["patch_id"] for p in evo_after_apply["applied"]] == [patch.patch_id]

        rb = client.post(f"/api/governance/evolution/{patch.patch_id}/rollback", json={})
        assert rb.status_code == 200
        assert rb.json()["status"] == "rolled_back"


def test_launcher_keeps_one_public_port_and_an_internal_sidecar():
    spec = importlib.util.spec_from_file_location("studyui_start_demo", REPO / "scripts" / "start_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.valid_backend_port("0") == 0
    assert module.valid_backend_port("7881") == 7881
    port = module.free_loopback_port()
    assert 0 < port < 65536
    assert module.port_available(port)


def test_legacy_workbench_removed_from_plugin():
    plugin = REPO / "dsh-plugins" / "studyui-dsh"
    host = (plugin / "lib" / "index.js").read_text(encoding="utf-8")
    client = (plugin / "lib" / "client.js").read_text(encoding="utf-8")
    assert "/studyui/workbench" not in host
    assert "/studyui/workbench" not in client
    assert "研究工作台" not in client
    assert "studyui-workbench" not in client
    for token in (
        "材料参数表单",
        "适用边界",
        "导出简报",
        "运行记录",
        "MaterialTaskDialog",
        "GovernanceDialog",
    ):
        assert token in client
