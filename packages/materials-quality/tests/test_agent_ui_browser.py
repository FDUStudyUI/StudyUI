"""Browser regression for the durable task lifecycle in StudyUI."""

import os
import socket
import threading
import time

import pytest
import uvicorn

from materials_quality.agent import server as agent_server
from materials_quality.agent.harness import StudyUIAgent

playwright = pytest.importorskip("playwright.sync_api", reason="requires the ui-test extra and a browser")


class BlockingModel:
    model = "offline-browser-model"

    def __init__(self):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(self, messages, tools, *, max_tokens=3000):
        self.calls += 1
        self.started.set()
        assert self.release.wait(30)
        return {"content": "This result should be discarded after cancellation."}


@pytest.fixture
def browser_task_app(tmp_path, monkeypatch):
    for name in ("workflows", "components", "frontend/assets"):
        (tmp_path / name).mkdir(parents=True)
    model = BlockingModel()

    def harness_with_model(database, *, langflow):
        return StudyUIAgent(database, langflow=langflow, model=model)

    monkeypatch.setattr(agent_server, "StudyUIAgent", harness_with_model)
    app = agent_server.create_app(
        tmp_path / "agent.sqlite3", tmp_path / "workflows", tmp_path / "components", tmp_path / "frontend"
    )
    harness = app.state.harness
    session = harness.new_session(project_id=harness.store.create_project("Browser regression"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while thread.is_alive() and not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            yield f"http://127.0.0.1:{port}", session, model
        finally:
            model.release.set()
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()


@pytest.fixture
def page():
    with playwright.sync_playwright() as runtime:
        options = {"headless": True}
        if executable := os.environ.get("PLAYWRIGHT_CHROME_EXECUTABLE"):
            options["executable_path"] = executable
        browser = runtime.chromium.launch(**options)
        page = browser.new_page()
        page.set_default_timeout(10_000)
        try:
            yield page
        finally:
            browser.close()


def test_task_cancel_and_refresh_does_not_replay(page, browser_task_app):
    base, session, model = browser_task_app
    page_errors = []
    task_submissions = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def local_only(route):
        if route.request.url.startswith(base + "/"):
            route.continue_()
        else:
            route.abort()

    page.route("**/*", local_only)
    tasks_url = f"{base}/api/sessions/{session}/tasks"

    def record_submission(request):
        if request.url == tasks_url and request.method == "POST":
            task_submissions.append(request.post_data_json)

    page.on("request", record_submission)

    def task_list_response(response):
        return response.url == tasks_url and response.request.method == "GET"

    with page.expect_response(task_list_response):
        page.goto(f"{base}/?session_id={session}")
    page.locator("#input").fill("Summarize the supplied research context")
    page.locator("#send").click()
    card = page.locator("[data-task-id]")
    playwright.expect(card).to_contain_text("运行中")
    assert model.started.wait(5)
    task_id = card.get_attribute("data-task-id")
    assert task_id

    page.reload()
    card = page.locator(f'[data-task-id="{task_id}"]')
    playwright.expect(card).to_contain_text("运行中")
    playwright.expect(page.locator("#send")).to_be_disabled()
    card.get_by_role("button", name="取消").click()
    playwright.expect(card).to_contain_text("取消中：等待当前操作结束")

    page.reload()
    playwright.expect(card).to_contain_text("取消中：等待当前操作结束")
    playwright.expect(card.get_by_role("button", name="取消")).to_be_disabled()
    model.release.set()
    playwright.expect(card).to_contain_text("已取消；已完成产物保留")
    playwright.expect(page.locator("#send")).to_be_enabled()
    assert page.get_by_text("This result should be discarded after cancellation.").count() == 0
    task = page.request.get(f"{tasks_url}/{task_id}").json()
    assert task["status"] == "cancelled"
    assert len(task_submissions) == model.calls == 1
    assert page_errors == []
