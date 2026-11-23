import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from test_material_workbench import workbench  # noqa: F401

playwright = pytest.importorskip("playwright.sync_api")


def test_material_task_forms_create_graph_without_json(workbench, tmp_path):  # noqa: F811
    app, _, session, _, path = workbench
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            end = time.monotonic() + 5
            while not server.started and time.monotonic() < end:
                time.sleep(0.01)
            assert server.started
            with playwright.sync_playwright() as runtime:
                options = {"headless": True}
                if executable := os.environ.get("PLAYWRIGHT_CHROME_EXECUTABLE"):
                    options["executable_path"] = executable
                browser = runtime.chromium.launch(**options)
                page = browser.new_page()
                page.set_default_timeout(8000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"{base}/?session_id={session}")
                page.locator("#material-task-btn").click()
                page.locator("#mt-file").set_input_files(path)
                playwright.expect(page.locator("#mt-preview")).to_contain_text("401")
                page.locator("#mt-x").select_option("strain")
                page.locator("#mt-y").select_option("stress")
                page.locator("#mt-x-unit").fill("fraction")
                page.locator("#mt-y-unit").fill("MPa")
                page.locator("#mt-fit-min").fill("0")
                page.locator("#mt-fit-max").fill("0.0008")
                page.locator("#mt-offset").fill("0.002")
                page.locator("#mt-check").click()
                playwright.expect(page.locator("#mt-status")).to_contain_text("可以生成")
                assert page.locator("#material-task-dialog textarea").count() == 0
                if evidence := os.environ.get("STUDYUI_UI_EVIDENCE"):
                    target = Path(evidence)
                    target.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(target / "material-task-form.png"), full_page=True)
                page.locator("#mt-build").click()
                playwright.expect(page.locator("#material-task-dialog")).not_to_be_visible()
                playwright.expect(page.locator("#flow-frame")).to_have_attribute(
                    "src", __import__("re").compile("/canvas/flow/")
                )
                assert len(app.state.harness.langflow.list_flows()) == 1
                assert errors == []
                browser.close()
        finally:
            server.should_exit = True
            thread.join(10)
