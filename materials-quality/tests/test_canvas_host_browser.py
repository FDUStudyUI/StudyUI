"""Canvas runs reach the correct host without dropping legacy workbench clicks."""

import json
import os
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.mark.parametrize("host", ["workbench", "dsh"])
def test_embedded_run_routes_to_its_host(host):
    bridge = (Path(__file__).resolve().parents[2] / "scripts/assets/canvas_bridge.html").read_text("utf-8")
    query = "studyui_host=dsh" if host == "dsh" else "studyui_session_id=session1"
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, executable_path=os.environ.get("PLAYWRIGHT_CHROME_EXECUTABLE") or None
        )
        page = browser.new_page()
        posts = []

        def route(request):
            url = request.request.url
            if "/api/sessions/" in url:
                if request.request.method == "POST":
                    posts.append(request.request.post_data_json)
                    data = {"id": "task1", "status": "completed", "terminal": True, "result": {}}
                else:
                    data = {"items": []}
                request.fulfill(content_type="application/json", body=json.dumps(data))
            elif "/canvas/flow/" in url:
                request.fulfill(content_type="text/html", body="<html><body>" + bridge + "</body></html>")
            else:
                request.fulfill(
                    content_type="text/html",
                    body=(
                        "<script>window.messages=[];addEventListener('message',e=>messages.push(e.data))</script>"
                        f'<iframe src="/canvas/flow/flow1?{query}"></iframe>'
                    ),
                )

        page.route("http://localhost/**", route)
        page.goto("http://localhost/")
        page.frame_locator("iframe").locator("#studyui-run-workflow").click()
        if host == "dsh":
            page.wait_for_function("messages.some(m=>m.type==='studyui-run-workflow'&&m.flowId==='flow1')")
            assert not posts
        else:
            playwright.expect(page.frame_locator("iframe").locator("#studyui-run-workflow")).to_be_enabled()
            assert len(posts) == 1 and posts[0]["flow_id"] == "flow1"
            assert not page.evaluate("messages.some(m=>m.type==='studyui-run-workflow')")
        browser.close()
