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
        '<title>StudyUI Workbench</title></head><body>Canvas</body></html>',
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
        assert 'data-src="/canvas/"' in page.text
        assert 'href="/canvas/"' in page.text

        canvas = client.get("/canvas/")
        assert canvas.status_code == 200
        assert "StudyUI Workbench" in canvas.text
        assert client.get("/canvas/health_check").json() == {"status": "ok"}
        assert client.get("/canvas/api/v1/version").json()["package"] == "StudyUI"
