"""Run all five demos through the actual StudyUI cards, canvas and artifact UI."""

import argparse
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import fitz  # noqa: F401 -- load native PDF bindings before graph worker threads
import uvicorn
from playwright.sync_api import expect, sync_playwright

from materials_quality.agent.server import create_app
from materials_quality.demos.catalog import list_datasets


class NoModel:
    model = "offline-reference-acceptance"
    calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Reference workflow unexpectedly called a model")


def build_frontend(runtime):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("demo_launcher", root / "scripts/start_demo.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    launcher.apply_studyui_langflow_theme(Path(sys.executable), runtime)
    return runtime / "workbench-ui"


def accept_ui(output, runtime, frontend=None):
    output, runtime = Path(output).resolve(), Path(runtime).resolve()
    output.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    frontend = Path(frontend) if frontend else build_frontend(runtime)
    package = Path(__file__).resolve().parents[1]
    app = create_app(
        runtime / ".demo-runtime/agent.sqlite3", runtime / "workflows", package / "components", frontend
    )
    model = NoModel()
    app.state.harness.model = model
    app.state.harness._custom_model = True
    app.state.harness.langflow.component_catalog()
    receipt = {
        "passed": False,
        "cases": {},
        "model_calls": 0,
        "json_typed": False,
        "page_errors": [],
        "api_errors": [],
    }
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 20
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROME_EXECUTABLE") or None
                )
                context = browser.new_context(viewport={"width": 1650, "height": 1100})
                page = context.new_page()
                page.set_default_timeout(120000)
                expect.set_options(timeout=120000)
                page.add_init_script(
                    "window.__demoMessages=[];addEventListener('message',e=>{"
                    "if(e.data?.type==='studyui-agent-run-complete')"
                    "window.__demoMessages.push({origin:e.origin,data:e.data})});"
                )
                page.on("pageerror", lambda error: receipt["page_errors"].append(str(error)))
                page.on(
                    "response",
                    lambda response: (
                        receipt["api_errors"].append(f"{response.status} {response.url}")
                        if response.status >= 400 and "/api/" in response.url
                        else None
                    ),
                )
                page.goto(base, wait_until="domcontentloaded")
                # Start from the actual empty application: no API-created project/session.
                expect(page.locator("#demo-quick-btn")).to_be_visible()
                page.screenshot(path=str(output / "welcome.png"), full_page=True)
                for item in list_datasets():
                    case = item["id"]
                    print("StudyUI reference:", case, flush=True)
                    page.locator("#demo-quick-btn").click()
                    dialog = page.get_by_role("dialog", name="选择演示案例")
                    card = dialog.locator(f'[data-demo-id="{case}"]')
                    expect(card).to_contain_text(item["title"])
                    with page.expect_response(
                        lambda r: r.url.endswith("/api/demo-datasets/reference")
                    ) as opened:
                        card.get_by_role("button", name="打开参考工作流", exact=True).click()
                    assert opened.value.ok, opened.value.text()
                    created = opened.value.json()
                    canvas = page.frame_locator("#flow-frame")
                    expect(canvas.locator(".react-flow__node").first).to_be_visible()
                    expect(canvas.locator("#studyui-run-workflow")).to_be_visible()
                    page.screenshot(path=str(output / f"{case}-canvas.png"))
                    with page.expect_response(
                        lambda r: "/tasks" in r.url and r.request.method == "POST"
                    ) as started:
                        canvas.locator("#studyui-run-workflow").click()
                    task = started.value.json()
                    assert started.value.ok, task
                    session_id = task["session_id"]
                    deadline = time.monotonic() + 180
                    while not task.get("terminal") and time.monotonic() < deadline:
                        page.wait_for_timeout(250)
                        response = page.request.get(f"{base}/api/sessions/{session_id}/tasks/{task['id']}")
                        assert response.ok
                        task = response.json()
                    assert task["status"] == "completed", task.get("error", task)
                    result = task["result"]
                    assert result["model"] == "本地参考工作流"
                    assert result["workflow_result"] and result["artifacts"]
                    try:
                        expect(page.locator("#feed")).to_contain_text(
                            "参考工作流已按画布中保存的参数完成本地计算", timeout=15000
                        )
                    except AssertionError:
                        receipt["notification_debug"] = page.evaluate("window.__demoMessages")
                        receipt["canvas_status"] = canvas.locator("body").inner_text()
                        page.screenshot(path=str(output / f"{case}-failed.png"))
                        raise
                    artifacts = result["artifacts"]
                    reports = [a for a in artifacts if a["name"].endswith(".html")]
                    plots = [a for a in artifacts if a["name"].endswith(".png")]
                    assert reports and plots
                    for artifact in [*reports, *plots]:
                        download = page.request.get(base + artifact["download_url"])
                        assert download.ok and download.body()
                    html = page.request.get(base + reports[0]["download_url"]).text()
                    assert item["sha256"] in html and "data:image/png;base64," in html
                    report_page = context.new_page()
                    report_page.set_content(html, wait_until="load")
                    assert report_page.locator("img").evaluate_all(
                        "items=>items.every(i=>i.complete&&i.naturalWidth>0)"
                    )
                    report_page.screenshot(path=str(output / f"{case}-report.png"))
                    report_page.close()
                    page.screenshot(path=str(output / f"{case}-results.png"))
                    receipt["cases"][case] = {
                        "passed": True,
                        "flow_id": created["flow_id"],
                        "session_id": session_id,
                        "artifacts": len(artifacts),
                        "plots": len(plots),
                        "reports": len(reports),
                        "source_sha256": item["sha256"],
                    }
                    if case == "ti64_tensile":
                        completed = page.locator("#feed .msg.assistant").filter(
                            has_text="参考工作流已按画布中保存的参数完成本地计算"
                        )
                        before = completed.count()
                        page.locator("#nav-flow").click()
                        canvas.locator("#studyui-run-workflow").click()
                        expect(completed).to_have_count(before + 1, timeout=30000)
                        expect(page.locator("#chat-view")).to_be_visible()
                        receipt["repeat_run_notified"] = True
                receipt["model_calls"] = model.calls
                assert model.calls == 0 and not receipt["page_errors"] and not receipt["api_errors"]
                receipt["passed"] = True
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            (output / "acceptance.json").write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2), "utf-8"
            )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-demo-references"))
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--frontend", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            accept_ui(args.output, args.runtime or tempfile.mkdtemp(prefix="studyui-demos-"), args.frontend),
            ensure_ascii=False,
            indent=2,
        )
    )
