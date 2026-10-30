"""Exercise the real Langflow UI through upload, canvas run and output copying.

Requires a running loopback Langflow 1.13.0 and Playwright. No API is used to
import/run/read results: those actions go through visible browser controls.
"""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8", newline="\n"
    )


def _home(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    ready = page.locator('[data-testid="upload-project-button"], [data-testid="new_project_btn_empty_page"]')
    ready.first.wait_for(state="visible", timeout=45000)
    if not page.get_by_test_id("upload-project-button").count():
        page.get_by_test_id("new_project_btn_empty_page").click()
        page.wait_for_url("**/flow/**")
        page.get_by_role("button", name="Go to home", exact=True).click()
    page.get_by_test_id("upload-project-button").wait_for(state="visible")


def _upload(page, base_url, path, name):
    _home(page, base_url)
    with page.expect_file_chooser() as chooser:
        page.get_by_test_id("upload-project-button").click()
    chooser.value.set_files(str(path))
    card = page.get_by_role("button", name=f"Open flow {name}", exact=True)
    card.wait_for(state="visible")
    card.click()
    page.wait_for_url("**/flow/**")
    expect(page.locator(".react-flow__node")).to_have_count(9)
    expect(page.locator(".react-flow__edge")).to_have_count(19)


def _run(page):
    summary = page.locator('.react-flow__node[data-id^="MaterialQualitySummary-"]')
    summary.get_by_role("button", name="Run component", exact=True).click()
    inspect = page.get_by_test_id("output-inspection-汇总报告-materialqualitysummary")
    expect(inspect).to_have_attribute("aria-label", "Inspect output", timeout=60000)


def _output_dialog(page):
    # Langflow's assistant onboarding also has role=dialog. Bind the locator
    # to the output viewer's own close control rather than every page dialog.
    return page.get_by_role("dialog").filter(has=page.get_by_test_id("btn-close-modal"))


def _report(page):
    page.get_by_test_id("output-inspection-汇总报告-materialqualitysummary").click()
    page.get_by_test_id("copy-output-button").wait_for(state="visible")
    # Wait for the actual JSON editor, then use the UI's copy action.
    expect(_output_dialog(page)).to_contain_text('"schema_version"')
    page.get_by_test_id("copy-output-button").click()
    text = page.evaluate("navigator.clipboard.readText()")
    return json.loads(text)


def _edit_rules(page, value):
    node = page.locator('.react-flow__node[data-id^="MaterialQualityContext-"]')
    node.get_by_role("button", name="Expand text editor", exact=True).click()
    editor = page.get_by_role("dialog").filter(has=page.get_by_test_id("genericModalBtnSave"))
    textarea = editor.locator("textarea")
    previous = textarea.input_value()
    textarea.fill(value)
    editor.get_by_test_id("genericModalBtnSave").click()
    editor.wait_for(state="hidden")
    return previous


def accept_ui(base_url, output, executable=None):
    if urlparse(base_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Run this acceptance script against an isolated loopback Langflow server")
    output.mkdir(parents=True, exist_ok=True)
    inputs = ROOT / "artifacts/ui-inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    expected = json.loads((ROOT / "examples/mechanics/expected_findings.json").read_text(encoding="utf-8"))
    results = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "base_url": base_url,
               "application": "real Langflow 1.13.0 UI", "cases": {}, "page_errors": [], "http_errors": []}
    with sync_playwright() as playwright:
        launch = {"headless": True}
        if executable:
            launch["executable_path"] = executable
        browser = playwright.chromium.launch(**launch)
        context = browser.new_context(viewport={"width": 1600, "height": 1000},
                                      permissions=["clipboard-read", "clipboard-write"])
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on("pageerror", lambda error: results["page_errors"].append(str(error)))
        page.on("response", lambda response: results["http_errors"].append(
            {"url": response.url, "status": response.status}
        ) if response.status >= 400 and "/api/" in response.url else None)
        results["browser_version"] = browser.version
        try:
            for case in ("clean", "dirty", "corrected"):
                flow_path = ROOT / "examples/mechanics" / f"{case}_flow.json"
                payload = json.loads(flow_path.read_text(encoding="utf-8"))
                name = f"UI验收-{case}-{uuid4().hex[:8]}"
                payload["name"] = name
                path = inputs / f"{case}.json"
                _write_json(path, payload)
                _upload(page, base_url, path, name)
                if case == "clean":
                    page.get_by_text("Materials Quality", exact=True).click()
                    for label in ("单位检查", "共享规则与追溯", "检查报告汇总", "结构检查",
                                  "类型格式检查", "缺失检查", "异常值标记", "重复记录检查"):
                        expect(page.get_by_text(f"材料数据·{label}", exact=True)).to_have_count(2)
                    page.screenshot(animations="disabled", path=str(output / "01-component-menu.png"))
                _run(page)
                report = _report(page)
                wanted = expected[case]
                actual = sorted((f["check_id"], f["code"], f["column"], f["row_position"])
                                for f in report["findings"])
                assert actual == sorted(tuple(f) for f in wanted["findings"]), (case, actual)
                assert report["passed"] == wanted["passed"]
                assert report["metrics"]["completed_checks"] == 6
                assert report["provenance_status"] == "verified"
                source = report["provenance"]["source"]
                csv_path = ROOT / "examples/mechanics" / f"{case}.csv"
                assert source["source_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
                _write_json(output / f"{case}-report.json", report)
                page.screenshot(animations="disabled", path=str(output / f"{case}-provenance.png"))
                page.get_by_test_id("btn-close-modal").click()
                page.get_by_test_id("output-inspection-汇总问题明细-materialqualitysummary").click()
                dialog = _output_dialog(page)
                if case == "dirty":
                    expect(dialog).to_contain_text("OUTLIER_IQR")
                    expect(dialog).to_contain_text("MISSING_VALUE")
                    expect(dialog).to_contain_text("1 to 8 of 8")
                page.screenshot(animations="disabled", path=str(output / f"{case}-findings.png"))
                page.get_by_test_id("btn-close-modal").click()
                page.get_by_test_id("output-inspection-摘要-materialqualitysummary").click()
                summary = _output_dialog(page).locator("textarea")
                expect(summary).to_have_value(re.compile(
                    f"已完成 6 项.*共 {len(wanted['findings'])} 条发现", re.DOTALL
                ))
                summary_text = summary.input_value()
                page.screenshot(animations="disabled", path=str(output / f"{case}-summary.png"))
                page.get_by_test_id("btn-close-modal").click()
                results["cases"][case] = {
                    "passed": report["passed"], "total_findings": report["total_findings"],
                    "completed_checks": 6, "nodes": 9, "edges": 19,
                    "provenance_status": report["provenance_status"], "source": source,
                    "dataset_fingerprint": report["dataset"]["fingerprint"],
                    "flow_sha256": hashlib.sha256(flow_path.read_bytes()).hexdigest(),
                    "summary_text": summary_text,
                }
                if case == "dirty":
                    original = _edit_rules(page, '{"checks":{"unknown_check":{}}}')
                    page.locator('.react-flow__node[data-id^="MaterialQualitySummary-"]').get_by_role(
                        "button", name="Run component", exact=True
                    ).click()
                    expect(page.get_by_text("checks must configure at least one supported check", exact=True)
                           .first).to_be_visible(timeout=60000)
                    # The upstream toast animates in from outside the viewport.
                    page.wait_for_timeout(500)
                    page.screenshot(animations="disabled", path=str(output / "invalid-rules.png"))
                    # The upstream failure toast auto-dismisses; do not race its
                    # transition. Editing the actual node also works while shown.
                    _edit_rules(page, original)
                    _run(page)
                    restored = _report(page)
                    assert restored["total_findings"] == 8 and not restored["passed"]
                    page.get_by_test_id("btn-close-modal").click()
                    results["invalid_rules_rejected_and_restored"] = True
            assert not results["page_errors"], results["page_errors"]
            assert not results["http_errors"], results["http_errors"]
            results["passed"] = True
        except Exception as error:
            results["passed"] = False
            results["error"] = str(error)
            page.screenshot(animations="disabled", path=str(output / "acceptance-failure.png"))
            raise
        finally:
            _write_json(output / "acceptance.json", results)
            browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7867")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/ui-acceptance")
    parser.add_argument("--chrome-executable")
    args = parser.parse_args()
    result = accept_ui(args.base_url, args.output, args.chrome_executable)
    print(json.dumps({"passed": result["passed"], "cases": result["cases"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
