"""Real-browser checks for offline Markdown, LaTeX and untrusted model output."""

import functools
import hashlib
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="requires the ui-test extra and a browser")
ASSETS = Path(__file__).resolve().parents[1] / "src/materials_quality/agent/ui/assets"


@pytest.fixture(scope="module")
def assets_url():
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path.startswith("/ui-assets/"):
                self.path = self.path.removeprefix("/ui-assets")
            super().do_GET()

    handler = functools.partial(QuietHandler, directory=str(ASSETS))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(3)


@pytest.fixture
def page(assets_url):
    with playwright.sync_playwright() as runtime:
        options = {"headless": True}
        if executable := os.environ.get("PLAYWRIGHT_CHROME_EXECUTABLE"):
            options["executable_path"] = executable
        browser = runtime.chromium.launch(**options)
        page = browser.new_page(viewport={"width": 420, "height": 800})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(assets_url)
        page.set_content(
            '<html><head></head><body style="margin:12px"><main id="output"></main></body></html>'
        )
        page.add_style_tag(url=assets_url + "/vendor/katex/katex.min.css")
        page.add_style_tag(url=assets_url + "/rich-renderer.css")
        for script in (
            "vendor/markdown-it/markdown-it.min.js",
            "vendor/katex/katex.min.js",
            "vendor/dompurify/purify.min.js",
            "rich-renderer.js",
        ):
            page.add_script_tag(url=assets_url + "/" + script)
        page.evaluate("""() => {
            window.render = (source, options={}) => {
                document.querySelector('#output').replaceChildren(StudyUIRich.render(source, options));
            };
            Object.defineProperty(navigator, 'clipboard', {value: {
                writeText: async text => {window.copied=text;}
            }});
        }""")
        yield page
        assert errors == []
        browser.close()


def test_vendor_assets_match_pinned_registry_hashes():
    manifest = json.loads((ASSETS / "vendor/manifest.json").read_text(encoding="utf-8"))
    assert {row["package"] for row in manifest} == {"markdown-it", "katex", "dompurify"}
    for package in manifest:
        assert package["source"].startswith("https://registry.npmjs.org/")
        assert package["integrity"].startswith("sha512-")
        assert any("LICENSE" in item["path"] for item in package["files"])
        for item in package["files"]:
            assert (
                hashlib.sha256((ASSETS / "vendor" / item["path"]).read_bytes()).hexdigest() == item["sha256"]
            )


def test_markdown_structure_and_all_math_delimiters(page):
    source = r"""# 拉伸实验

说明 **弹性模量** 与 *屈服强度*，行内 $E=\frac{\sigma}{\varepsilon}$ 与 \(x^2\)。

1. 标定
   - 检查单位
   - 保留原始数据
2. 拟合

> 这只是检查记录。

| 样品 | 强度 |
| --- | ---: |
| A | 200 |

$$
\begin{bmatrix}1 & 2 \\ 3 & 4\end{bmatrix}
$$

\[
\int_0^1 x\,dx=\frac12
\]
"""
    page.evaluate("source => render(source)", source)
    assert page.locator("h1").inner_text() == "拉伸实验"
    assert page.locator("ol > li").count() == 2
    assert page.locator("ol ul > li").count() == 2
    assert page.locator("blockquote").count() == 1
    assert page.locator(".rich-table tbody tr").count() == 1
    assert page.locator(".katex").count() == 4
    assert page.locator(".katex-mathml math").count() == 4
    assert page.locator(".math-error").count() == 0
    assert page.evaluate("StudyUIRich.source(document.querySelector('.rich-content'))") == source


def test_untrusted_content_does_not_execute_or_load_remote_images(page):
    external = []
    page.route(
        "https://untrusted.example/**", lambda route: (external.append(route.request.url), route.abort())
    )
    source = r"""<img src=x onerror="window.exploited=1"><script>window.exploited=2</script>

[bad](javascript:alert(1)) [bad2](data:text/html;base64,PHNjcmlwdD4=)

![private](https://untrusted.example/pixel)

$\href{javascript:alert(1)}{unsafe}$

```python
print("$x^2$")
<script>alert(3)</script>
```
"""
    page.evaluate("source => render(source)", source)
    assert page.evaluate("window.exploited") is None
    assert page.locator("#output img, #output script, #output iframe").count() == 0
    assert page.locator('#output a[href^="javascript:"], #output a[href^="data:"]').count() == 0
    assert page.locator("pre .katex").count() == 0
    assert "$x^2$" in page.locator("pre code").inner_text()
    assert external == []
    page.get_by_role("button", name="复制代码").click()
    assert page.evaluate("window.copied") == 'print("$x^2$")\n<script>alert(3)</script>\n'


def test_partial_output_is_readable_until_complete_and_copy_is_lossless(page):
    for source in ("## 结果\n\n公式 $E=", "## 结果\n\n公式 $E=x^2$\n\n```python\nprint("):
        page.evaluate("source => render(source,{streaming:true})", source)
        assert page.locator(".rich-content").get_attribute("aria-busy") == "true"
        assert page.get_by_role("button", name="保存代码审核草稿").count() == 0
    final = "## 结果\n\n公式 $E=x^2$\n\n```python\nprint('done')\n```\n"
    page.evaluate("source => render(source)", final)
    assert page.locator(".katex").count() == 1
    assert page.get_by_role("button", name="保存代码审核草稿").count() == 1
    page.evaluate("StudyUIRich.copyText(StudyUIRich.source(document.querySelector('.rich-content')))")
    assert page.evaluate("window.copied") == final
    page.evaluate(r"render('$\\unknownUnsupportedCommand{x}$')")
    assert page.locator(".math-error").count() == 1
    assert r"\unknownUnsupportedCommand" in page.locator(".math-error").inner_text()


def test_wide_table_formula_and_code_scroll_inside_mobile_message(page):
    source = "| " + " | ".join(f"column{i}" for i in range(15)) + " |\n"
    source += "| " + " | ".join("---" for _ in range(15)) + " |\n"
    source += "| " + " | ".join("123456789" for _ in range(15)) + " |\n\n"
    source += "$$" + "+".join("x_{12345}" for _ in range(30)) + "$$\n\n"
    source += "```text\n" + "long_code_" * 60 + "\n```"
    page.evaluate("source => render(source)", source)
    widths = page.evaluate("""() => ({
        page:document.documentElement.scrollWidth, viewport:innerWidth,
        local:[...document.querySelectorAll('.rich-table-wrap,.math-block,pre')]
            .map(e => ({client:e.clientWidth, scroll:e.scrollWidth}))
    })""")
    assert widths["page"] <= widths["viewport"] + 1
    assert len(widths["local"]) == 3
    assert all(row["scroll"] > row["client"] for row in widths["local"])


def test_chat_partial_math_and_failed_answer_survive_refresh(page, assets_url):
    task = {
        "id": "t1",
        "status": "running",
        "terminal": False,
        "partial_content": r"## 分析中" + "\n\n" + r"弹性模量 $E=\frac{\sigma}{\varepsilon}$。",
    }

    def api_response(route):
        path = route.request.url.split(assets_url)[-1]
        responses = {
            "/api/health": {"model_configured": True, "model_name": "Offline test"},
            "/api/projects": [],
            "/api/workspaces": [],
            "/api/sessions": [{"id": "s1", "title": "Render test", "project_id": None}],
            "/api/sessions/s1": {"messages": [{"role": "user", "content": "分析数据"}]},
            "/api/sessions/s1/tasks": {"items": [task]},
            "/api/sessions/s1/tasks/t1": task,
        }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(responses.get(path, {})))

    page.route(assets_url + "/api/**", api_response)
    page.route(
        assets_url + "/chat*",
        lambda route: route.fulfill(
            content_type="text/html", body=(ASSETS.parent / "index.html").read_text(encoding="utf-8")
        ),
    )
    page.goto(assets_url + "/chat")
    live = page.locator('[data-partial-task="t1"]')
    playwright.expect(live.locator(".katex")).to_have_count(1)
    playwright.expect(live.locator(".rich-content.dsh-stream-tail")).to_have_attribute("aria-busy", "true")
    task.update(status="failed", terminal=True, error="模拟断线")
    playwright.expect(live).to_contain_text("未完成的回答 · 失败")
    page.reload()
    playwright.expect(live).to_contain_text("未完成的回答 · 失败")
    playwright.expect(live.locator(".katex")).to_have_count(1)
    assert live.evaluate("element => element.markdownSource") == task["partial_content"]
    # A late response from the previous session must not appear in a new chat.
    page.evaluate("""() => {
        const realApi = api;
        api = (path, options) => {
            if (path === '/api/sessions/s1/tasks/delayed') {
                return new Promise((resolve) => {window.releaseOldTask = resolve;});
            }
            return realApi(path, options);
        };
        active = 's1';
        window.oldTaskPoll = watchTask('s1', 'delayed');
    }""")
    page.wait_for_function("() => window.releaseOldTask !== undefined")
    page.evaluate("""() => {
        active = 's2';
        feed.textContent = 'Different session';
        releaseOldTask({status:'completed',terminal:true,result:{message:'old private answer'}});
    }""")
    page.evaluate("window.oldTaskPoll")
    assert page.locator("#feed").inner_text() == "Different session"


def test_completed_stream_keeps_thinking_separate_before_and_after_refresh(page, assets_url):
    thought = "先检查边界条件和单位。"
    answer = "最终回答只包含经过整理的结论。"
    message = f"<think>{thought}</think>\n\n{answer}"
    history = [{"role": "user", "content": "请分析这个问题"}]
    task = {"id": "t2", "status": "running", "terminal": False, "partial_content": ""}

    def api_response(route):
        path = route.request.url.split(assets_url)[-1].split("?", 1)[0]
        if path == "/api/sessions/s1/tasks/t2/events":
            task.update(
                status="completed",
                terminal=True,
                result={"message": message, "reasoning_content": ""},
            )
            history.append({"role": "assistant", "content": message})
            events = [
                ("snapshot", {"id": "t2", "status": "running", "terminal": False, "partial_content": ""}),
                ("content_chunk", {"delta": message}),
                ("terminal", {"task": task}),
            ]
            body = (
                "\n\n".join(
                    f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}"
                    for kind, payload in events
                )
                + "\n\n"
            )
            route.fulfill(content_type="text/event-stream", body=body)
            return

        responses = {
            "/api/health": {"model_configured": True, "model_name": "Offline test"},
            "/api/projects": [],
            "/api/workspaces": [],
            "/api/sessions": [{"id": "s1", "title": "Reasoning test", "project_id": None}],
            "/api/sessions/s1": {"messages": history},
            "/api/sessions/s1/tasks": {"items": [task]},
            "/api/sessions/s1/tasks/t2": task,
        }
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(responses.get(path, {}), ensure_ascii=False),
        )

    page.route(assets_url + "/api/**", api_response)
    page.route(
        assets_url + "/chat*",
        lambda route: route.fulfill(
            content_type="text/html", body=(ASSETS.parent / "index.html").read_text(encoding="utf-8")
        ),
    )
    page.goto(assets_url + "/chat?session_id=s1")

    assistant = page.locator("#feed .msg.assistant").last
    playwright.expect(assistant.locator(".dsh-reasoning")).to_have_count(1)
    playwright.expect(assistant.locator(".dsh-reasoning-body .rich-content")).to_contain_text(thought)
    playwright.expect(assistant.locator(".rich-content").last).to_have_text(answer)
    assert assistant.locator(".dsh-reasoning-row").get_attribute("aria-expanded") == "false"
    assert assistant.locator(".dsh-reasoning-body").evaluate("element => element.hidden") is True
    live_state = assistant.evaluate("""message => ({
        reasoning: message.querySelector('.dsh-reasoning-body .rich-content').innerText,
        answer: message.querySelector(':scope > .rich-content').innerText,
        collapsed: message.querySelector('.dsh-reasoning-body').hidden
    })""")

    page.reload()
    assistant = page.locator("#feed .msg.assistant").last
    playwright.expect(assistant.locator(".dsh-reasoning")).to_have_count(1)
    playwright.expect(assistant.locator(".dsh-reasoning-body .rich-content")).to_contain_text(thought)
    playwright.expect(assistant.locator(".rich-content").last).to_have_text(answer)
    assert assistant.locator(".dsh-reasoning-row").get_attribute("aria-expanded") == "false"
    assert assistant.locator(".dsh-reasoning-body").evaluate("element => element.hidden") is True
    history_state = assistant.evaluate("""message => ({
        reasoning: message.querySelector('.dsh-reasoning-body .rich-content').innerText,
        answer: message.querySelector(':scope > .rich-content').innerText,
        collapsed: message.querySelector('.dsh-reasoning-body').hidden
    })""")
    assert live_state == history_state
