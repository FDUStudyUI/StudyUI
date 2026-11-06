from pathlib import Path

from fastapi.testclient import TestClient

from materials_quality.agent.server import create_app


def test_ui_phase3_html_elements_present(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        page = client.get("/")
        assert page.status_code == 200
        html = page.text

        # 1. Drag & drop overlay
        assert "drop-overlay" in html
        assert "dropzone-overlay" in html
        assert "释放文件以导入 StudyUI" in html
        assert "/api/upload" in html

        # 2. View mode buttons (Split view, Chat, Flow)
        assert "btn-mode-chat" in html
        assert "btn-mode-split" in html
        assert "btn-mode-flow" in html
        assert "split-mode" in html
        assert "view-mode-toggle" in html

        # 3. Demo datasets cards & quick button
        assert "demo-grid" in html
        assert "demo-quick-btn" in html
        assert "/api/demo-datasets" in html


def test_demo_datasets_api_and_load(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        # GET /api/demo-datasets
        resp = client.get("/api/demo-datasets")
        assert resp.status_code == 200
        datasets = resp.json().get("datasets", [])
        assert len(datasets) == 5
        ids = [d["id"] for d in datasets]
        assert "ti64_tensile" in ids
        assert "raman_spectra" in ids
        assert "material_contrast" in ids
        assert "zirconia_xrd" in ids
        assert "battery_cycle" in ids

        # Create session
        session_res = client.post("/api/sessions", json={"title": "Demo Test"})
        assert session_res.status_code == 201
        session_id = session_res.json()["id"]

        # POST /api/demo-datasets/load
        load_res = client.post(
            "/api/demo-datasets/load",
            json={"id": "ti64_tensile", "session_id": session_id},
        )
        assert load_res.status_code == 200
        data = load_res.json()
        assert data["status"] == "ok"
        assert data["id"] == "ti64_tensile"
        assert "01_钛合金拉伸力学性能_Ti64.csv" in data["filename"]
        assert Path(data["path"]).exists()
        assert "钛合金" in data["prompt"]


def test_file_upload_endpoint(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        session_res = client.post("/api/sessions", json={"title": "Upload Test"})
        assert session_res.status_code == 201
        session_id = session_res.json()["id"]

        csv_content = b"Strain,Stress_MPa\n0.001,85.2\n0.002,170.5\n0.005,420.0\n"
        upload_res = client.post(
            "/api/upload",
            content=csv_content,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Filename": "sample_tensile_test.csv",
                "X-StudyUI-Session": session_id,
            },
        )
        assert upload_res.status_code == 200
        data = upload_res.json()
        assert data["status"] == "ok"
        assert data["filename"] == "sample_tensile_test.csv"
        assert Path(data["path"]).exists()
        assert Path(data["path"]).read_bytes() == csv_content
        assert "sample_tensile_test.csv" in data["prompt"]
