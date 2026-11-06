"""Browser checks for the demo picker, separate actions and recovery; canvas runs have separate E2E checks."""

import os
import re
import socket
import threading
import time

import pytest
import test_demo_reference_api as api_tests
import uvicorn

demo_app = api_tests.demo_app

playwright = pytest.importorskip("playwright.sync_api", reason="requires ui-test extra")


@pytest.fixture
def demo_browser(demo_app):
    app, _, session, _ = demo_app
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
            with playwright.sync_playwright() as runtime:
                options = {"headless": True}
                if executable := os.environ.get("PLAYWRIGHT_CHROME_EXECUTABLE"):
                    options["executable_path"] = executable
                browser = runtime.chromium.launch(**options)
                page = browser.new_page()
                page.set_default_timeout(5000)
                base = f"http://127.0.0.1:{port}"
                page.route(
                    "**/*",
                    lambda route: (
                        route.continue_() if route.request.url.startswith(base + "/") else route.abort()
                    ),
                )
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"{base}/?session_id={session}")
                yield page, app, session
                assert errors == []
                browser.close()
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive()


def test_all_five_cards_have_distinct_actions_and_accessible_picker(demo_browser):
    page, _, _ = demo_browser
    cards = page.locator("#feed .demo-card")
    playwright.expect(cards).to_have_count(5)
    for card in cards.all():
        playwright.expect(card.get_by_role("button", name="载入数据，交给 Agent")).to_be_visible()
        playwright.expect(card.get_by_role("button", name="打开参考工作流")).to_be_visible()
        playwright.expect(card.locator(".demo-provenance")).to_contain_text("演示")
    page.locator("#demo-quick-btn").click()
    picker = page.get_by_role("dialog", name="选择演示案例")
    playwright.expect(picker).to_be_visible()
    playwright.expect(picker.locator(".demo-card")).to_have_count(5)
    page.keyboard.press("Escape")
    playwright.expect(picker).not_to_be_visible()
    playwright.expect(page.locator("#demo-quick-btn")).to_be_focused()


def test_picker_preserves_agent_prompt_without_submitting(demo_browser):
    page, app, session = demo_browser
    page.locator("#demo-quick-btn").click()
    card = page.get_by_role("dialog", name="选择演示案例").locator('[data-demo-id="ti64_tensile"]')
    card.get_by_role("button", name="载入数据，交给 Agent").click()
    playwright.expect(page.locator("#input")).to_have_value(re.compile(".*钛合金.*"))
    playwright.expect(page.locator("#demo-guidance")).to_contain_text("发送")
    assert app.state.harness.langflow.list_flows() == []
    assert not any(e["kind"] == "tool_call" for e in app.state.harness.store.events(session))


@pytest.mark.parametrize(
    "dataset_id", ["ti64_tensile", "raman_spectra", "material_contrast", "zirconia_xrd", "battery_cycle"]
)
def test_open_reference_navigates_canvas_with_run_guidance(demo_browser, dataset_id):
    page, app, session = demo_browser
    # This fixture checks navigation; the real bundled canvas is tested independently.
    page.route(
        "**/canvas/flow/**",
        lambda route: route.fulfill(
            status=200, content_type="text/html", body="<html><body>Canvas fixture</body></html>"
        ),
    )
    card = page.locator(f'#feed [data-demo-id="{dataset_id}"]')
    with page.expect_response(
        lambda response: response.url.endswith("/api/demo-datasets/reference")
    ) as pending:
        card.get_by_role("button", name="打开参考工作流").click()
    assert pending.value.status == 201, pending.value.text()
    result = pending.value.json()
    playwright.expect(page.locator("#flow-frame")).to_have_attribute(
        "src", re.compile("/canvas/flow/" + result["flow_id"])
    )
    playwright.expect(page.locator("#demo-run-guidance")).to_contain_text("运行工作流")
    assert len(app.state.harness.langflow.list_flows()) == 1
    assert not any(e["kind"] == "canvas_run_authorized" for e in app.state.harness.store.events(session))


def test_reference_error_keeps_picker_and_allows_retry(demo_browser):
    page, _, _ = demo_browser
    page.locator("#demo-quick-btn").click()
    picker = page.get_by_role("dialog", name="选择演示案例")
    button = picker.locator('[data-demo-id="ti64_tensile"]').get_by_role("button", name="打开参考工作流")
    page.route(
        "**/api/demo-datasets/reference",
        lambda route: route.fulfill(status=409, json={"error": "会话正在运行，请稍后重试"}),
        times=1,
    )
    button.click()
    playwright.expect(picker.locator('[role="status"]')).to_contain_text("会话正在运行")
    playwright.expect(button).to_be_enabled()
    playwright.expect(picker).to_be_visible()


def test_fresh_start_reference_creates_project_and_preserves_ungrouped_chat(demo_browser):
    page, app, _ = demo_browser
    store = app.state.harness.store
    for session in store.list_sessions():
        store.delete_session(session["id"])
    for project in store.list_projects():
        store.delete_project(project["id"])
    page.goto(page.url.split("?")[0])
    playwright.expect(page.locator("#feed .demo-card")).to_have_count(5)
    original = store.list_sessions()[0]
    assert not original["project_id"]
    page.route(
        "**/canvas/flow/**",
        lambda route: route.fulfill(status=200, content_type="text/html", body="Canvas fixture"),
    )
    with page.expect_response(
        lambda response: response.url.endswith("/api/demo-datasets/reference")
    ) as pending:
        page.locator('#feed [data-demo-id="ti64_tensile"]').get_by_role(
            "button", name="打开参考工作流"
        ).click()
    assert pending.value.status == 201, pending.value.text()
    flow = app.state.harness.langflow.get_flow(pending.value.json()["flow_id"])
    assert flow["folder_id"]
    assert store.has_session(original["id"])
    assert not store.session_context(original["id"])["project_id"]
    assert len(store.list_sessions()) == 2
    playwright.expect(page.locator("#demo-run-guidance")).to_contain_text("新建演示项目及会话")
    playwright.expect(page.locator("#demo-run-guidance")).to_contain_text("右下角")
