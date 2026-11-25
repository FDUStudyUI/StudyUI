"""Exercise real instrument examples through the StudyUI form, canvas and downloads."""

import argparse
import json
import os
import socket
import threading
import time
from pathlib import Path

import fitz  # noqa: F401 -- initialize native PDF libraries before graph workers
import uvicorn
from playwright.sync_api import expect, sync_playwright

from materials_quality.agent.server import create_app
from scripts.ui_demo_reference_acceptance import NoModel, build_frontend


def accept_ui(output, runtime, frontend=None):
    output, runtime = Path(output).resolve(), Path(runtime).resolve()
    output.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    frontend = Path(frontend) if frontend else build_frontend(runtime)
    package = Path(__file__).resolve().parents[1]
    app = create_app(runtime / "agent.db", runtime / "flows", package / "components", frontend)
    harness = app.state.harness
    harness.model = NoModel()
    harness._custom_model = True
    project = harness.store.create_project("材料任务界面验收")
    session = harness.new_session(project_id=project)
    harness.permissions.set_preset(project, "project_collaboration")
    receipt = {"passed": False, "cases": [], "page_errors": []}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROME_EXECUTABLE") or None
                )
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                page.set_default_timeout(60000)
                expect.set_options(timeout=60000)
                page.on("pageerror", lambda error: receipt["page_errors"].append(str(error)))
                for example_id in ("tensile_aluminum_2", "raman_pet_1", "xrd_graphite"):
                    page.goto(f"{base}/?session_id={session}")
                    page.locator("#material-task-btn").click()
                    page.locator("#material-task-dialog > details > summary").click()
                    page.locator("#mt-example").select_option(example_id)
                    page.screenshot(path=str(output / f"{example_id}-form.png"))
                    with page.expect_response(
                        lambda r: r.url.endswith("/api/material-tasks/example")
                    ) as opened:
                        page.locator("#mt-example-open").click()
                    assert opened.value.ok, opened.value.text()
                    flow_id = opened.value.json()["flow_id"]
                    canvas = page.frame_locator("#flow-frame")
                    expect(canvas.locator(".react-flow__node").first).to_be_visible()
                    expect(canvas.locator("#studyui-run-workflow")).to_be_visible()
                    page.screenshot(path=str(output / f"{example_id}-canvas.png"))
                    with page.expect_response(
                        lambda r: "/tasks" in r.url and r.request.method == "POST"
                    ) as run:
                        canvas.locator("#studyui-run-workflow").click()
                    task = run.value.json()
                    assert run.value.ok, task
                    deadline = time.monotonic() + 150
                    while not task.get("terminal") and time.monotonic() < deadline:
                        page.wait_for_timeout(250)
                        response = page.request.get(f"{base}/api/sessions/{session}/tasks/{task['id']}")
                        assert response.ok
                        task = response.json()
                    assert task["status"] == "completed", task.get("error", task)
                    result = task["result"]
                    assert result["model"] == "本地材料分析"
                    expect(page.locator("#feed")).to_contain_text("材料分析已完成")
                    expect(page.locator("#chat-view")).to_be_visible()
                    artifacts = result["artifacts"]
                    for suffix in (".png", ".html", ".zip"):
                        artifact = next(a for a in artifacts if a["name"].endswith(suffix))
                        download = page.request.get(base + artifact["download_url"])
                        assert download.ok and download.body()
                    page.screenshot(path=str(output / f"{example_id}-results.png"))
                    receipt["cases"].append(
                        {"id": example_id, "flow_id": flow_id, "artifacts": len(artifacts), "passed": True}
                    )
                assert harness.model.calls == 0 and not receipt["page_errors"]
                receipt.update(passed=True, model_calls=0)
                browser.close()
        finally:
            server.should_exit = True
            thread.join(15)
            (output / "acceptance.json").write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2), "utf-8"
            )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/ui-material-tasks")
    parser.add_argument("--runtime", default="artifacts/ui-material-runtime")
    parser.add_argument("--frontend")
    args = parser.parse_args()
    print(json.dumps(accept_ui(args.output, args.runtime, args.frontend), ensure_ascii=False))
