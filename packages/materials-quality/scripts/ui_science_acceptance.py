"""Import and run all nine complete science workflows through the real browser UI."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from scripts.ui_acceptance import _home, _output_dialog, _write_json

ROOT = Path(__file__).resolve().parents[1]


def accept_ui(base_url, output, executable=None):
    if urlparse(base_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Use an isolated loopback Langflow acceptance server")
    output.mkdir(parents=True, exist_ok=True)
    inputs = output / "inputs"
    inputs.mkdir(exist_ok=True)
    results = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "cases": {},
        "page_errors": [],
        "http_errors": [],
        "application": "Real Langflow 1.13.0 browser UI",
    }
    with sync_playwright() as runtime:
        launch = {"headless": True}
        if executable:
            launch["executable_path"] = executable
        browser = runtime.chromium.launch(**launch)
        context = browser.new_context(
            viewport={"width": 1800, "height": 1100}, permissions=["clipboard-read", "clipboard-write"]
        )
        page = context.new_page()
        page.set_default_timeout(45000)
        page.on("pageerror", lambda error: results["page_errors"].append(str(error)))
        page.on(
            "response",
            lambda response: (
                results["http_errors"].append({"url": response.url, "status": response.status})
                if response.status >= 400 and "/api/" in response.url
                else None
            ),
        )
        try:
            paths = sorted((ROOT / "examples/science_flows").glob("[0-9][0-9]-*.json"))
            assert len(paths) == 9
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                name = f"UI-{path.stem}-{uuid4().hex[:8]}"
                payload["name"] = name
                imported = inputs / path.name
                _write_json(imported, payload)
                _home(page, base_url)
                with page.expect_file_chooser() as chooser:
                    page.get_by_test_id("upload-project-button").click()
                chooser.value.set_files(str(imported))
                page.get_by_role("button", name=f"Open flow {name}", exact=True).click()
                page.wait_for_url("**/flow/**")
                expect(page.locator(".react-flow__node")).to_have_count(len(payload["data"]["nodes"]))
                page.get_by_test_id("canvas_controls_dropdown").click()
                page.get_by_test_id("fit_view").click()
                page.keyboard.press("Escape")
                expect(page.locator(".react-flow__edge")).to_have_count(len(payload["data"]["edges"]))
                # Langflow assigns fresh node suffixes during browser import.
                sink = page.locator('.react-flow__node[data-id^="ScienceExportReport-"]')
                sink.get_by_role("button", name="Run component", exact=True).click()
                inspect = sink.get_by_test_id("output-inspection-结果与追溯-scienceexportreport")
                expect(inspect).to_have_attribute("aria-label", "Inspect output", timeout=180000)
                page.screenshot(path=str(output / (path.stem + "-canvas.png")), animations="disabled")
                inspect.click()
                expect(_output_dialog(page)).to_contain_text("science-result/1")
                page.get_by_test_id("copy-output-button").click()
                envelope = json.loads(page.evaluate("navigator.clipboard.readText()"))
                assert envelope["operation"] == "export.report"
                assert envelope["execution_status"] == "completed"
                assert envelope["data"]["verified"]
                operations = sorted({r["operation"] for r in envelope["provenance"]["lineage"]})
                assert len(operations) >= 4
                _write_json(output / (path.stem + "-report.json"), envelope)
                page.get_by_test_id("btn-close-modal").click()
                report_path = Path(envelope["data"]["file_path"])
                assert report_path.is_file()
                report_page = context.new_page()
                report_page.goto(report_path.as_uri(), wait_until="load")
                image_check = report_page.locator("img").evaluate_all(
                    "(images)=>images.map(im=>({complete:im.complete,width:im.naturalWidth}))"
                )
                assert all(im["complete"] and im["width"] > 0 for im in image_check)
                expect(report_page.get_by_role("heading", name="Data sources", exact=True)).to_be_visible()
                report_page.screenshot(path=str(output / (path.stem + "-html.png")), animations="disabled")
                report_page.close()
                results["cases"][path.stem] = {
                    "nodes": len(payload["data"]["nodes"]),
                    "edges": len(payload["data"]["edges"]),
                    "operations": operations,
                    "embedded_images_decoded": len(image_check),
                    "report_verified": True,
                }
                print(f"UI verified {path.stem}", flush=True)
            assert not results["page_errors"], results["page_errors"]
            assert not results["http_errors"], results["http_errors"]
            results["passed"] = True
        except Exception as exc:
            results["passed"] = False
            results["error"] = str(exc)
            page.screenshot(path=str(output / "failure.png"), animations="disabled")
            raise
        finally:
            _write_json(output / "acceptance.json", results)
            browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7867")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/ui-science-acceptance")
    parser.add_argument("--chrome-executable")
    args = parser.parse_args()
    result = accept_ui(args.base_url, args.output, args.chrome_executable)
    print(json.dumps({"passed": result["passed"], "flows": len(result["cases"])}))


if __name__ == "__main__":
    main()
