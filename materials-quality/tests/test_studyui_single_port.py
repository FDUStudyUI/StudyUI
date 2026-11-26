from fastapi.testclient import TestClient

from materials_quality.agent.server import create_app


def test_agent_and_workbench_share_one_host_and_port(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    (workflows).mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text(
        '<!doctype html><html><head><base href="/canvas/" />'
        "<title>StudyUI Workbench</title></head><body>Canvas</body></html>",
        encoding="utf-8",
    )
    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)

    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["canvas_url"] == "/canvas"
        assert health.json()["workflow_storage"] == "json"

        page = client.get("/")
        assert page.status_code == 200
        assert 'data-src="/canvas"' in page.text
        assert "__CANVAS_BASE_PATH__" not in page.text

        canvas = client.get("/canvas/")
        assert canvas.status_code == 200
        assert "StudyUI Workbench" in canvas.text
        assert client.get("/canvas/health_check").json() == {"status": "ok"}
        assert client.get("/canvas/api/v1/version").json()["package"] == "StudyUI"


def test_governance_endpoints_and_ui_hooks(tmp_path):
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
    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)

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

        page = client.get("/")
        assert page.status_code == 200
        for hook in (
            "role_selection",
            "interrupted_resumable",
            "/resume",
            "/api/governance/scope",
            "guard_report",
        ):
            assert hook in page.text
