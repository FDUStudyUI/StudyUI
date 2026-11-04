"""Import, multi-upload and run batch flows through a fresh Langflow browser UI."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from scripts.build_batch_examples import build_examples
from scripts.ui_forms_acceptance import _copy_report, _import, _node, _run

ROOT = Path(__file__).resolve().parents[1]


def _file_fields(payload):
    """Record file shapes and component hashes, never file contents or paths."""
    fields = []
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        return fields
    for node in data["nodes"]:
        template = node.get("data", {}).get("node", {}).get("template", {})
        code = template.get("code", {}).get("value", "")
        for name, field in template.items():
            if not isinstance(field, dict) or field.get("type") != "file":
                continue
            path = field.get("file_path")
            fields.append(
                {
                    "class": node["data"].get("type"),
                    "field": name,
                    "list": field.get("list"),
                    "file_path_type": type(path).__name__,
                    "file_path_count": len(path) if isinstance(path, list) else int(bool(path)),
                    "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                }
            )
    return fields


def _upload_files(page, node, paths):
    token = uuid4().hex[:8]
    unique_paths = []
    for original in paths:
        unique = original.with_name(token + "-" + original.name)
        unique.write_bytes(original.read_bytes())
        unique_paths.append(unique)
    paths = unique_paths
    node.get_by_test_id("button_open_file_management").click()
    dialog = page.get_by_role("dialog").filter(has=page.get_by_test_id("select-files-modal-button"))
    with page.expect_file_chooser() as chooser:
        dialog.get_by_test_id("drag-files-component").click()
    chooser.value.set_files([str(path.resolve()) for path in paths])
    for path in paths:
        item = dialog.locator(f'[data-testid="file-item-{path.name}"], [data-testid="file-item-{path.stem}"]')
        item.locator('[data-testid^="context-menu-button-"]').wait_for(timeout=60000)
    for path in paths:
        item = dialog.locator(f'[data-testid="file-item-{path.name}"], [data-testid="file-item-{path.stem}"]')
        item.locator('[data-testid^="context-menu-button-"]').wait_for(timeout=60000)
        checkbox = item.get_by_role("checkbox")
        for attempt in range(3):
            try:
                checkbox.check(timeout=10000)
                break
            except Exception as error:
                if attempt == 2 or "Clicking the checkbox did not change its state" not in str(error):
                    raise
        expect(checkbox).to_be_checked()
    dialog.get_by_test_id("select-files-modal-button").click()
    expect(dialog).not_to_be_visible()


def accept_ui(base_url, output, executable=None):
    if urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use an isolated loopback Langflow server")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    payloads = build_examples(output / "inputs")
    results = {
        "cases": {},
        "page_errors": [],
        "http_errors": [],
        "json_typed": False,
        "file_field_snapshots": [],
        "discovery": {},
        "passed": False,
    }
    with sync_playwright() as runtime:
        options = {"headless": True}
        if executable:
            options["executable_path"] = executable
        browser = runtime.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1900, "height": 1450}, permissions=["clipboard-read", "clipboard-write"]
        )
        page = context.new_page()
        page.set_default_timeout(60000)
        page.on("pageerror", lambda e: results["page_errors"].append(str(e)))

        def record_response(response):
            if response.status >= 400 and "/api/" in response.url:
                results["http_errors"].append({"url": response.url, "status": response.status})
            if urlparse(response.url).path.rstrip("/") != "/api/v1/all" or response.status != 200:
                return
            catalog = response.json()
            counts = {
                category: len(items)
                for category, items in catalog.items()
                if category.lower().replace("_", " ").startswith("materials ") and isinstance(items, dict)
            }
            if counts:
                results["discovery"] = {"categories": counts, "component_count": sum(counts.values())}

        def record_request(request):
            if request.method not in {"POST", "PATCH"} or "/api/" not in request.url:
                return
            try:
                payload = request.post_data_json
            except Exception:
                return
            if not isinstance(payload, dict):
                return
            fields = _file_fields(payload)
            if fields:
                results["file_field_snapshots"].append(
                    {"endpoint": urlparse(request.url).path, "fields": fields}
                )

        page.on("response", record_response)
        page.on("request", record_request)
        try:
            for case, payload in payloads.items():
                print(f"Import {case}", flush=True)
                _import(page, base_url, payload, output / (case + ".json"))
                print(f"Canvas ready {case}", flush=True)
                if case == "01_twenty_specimens":
                    expect(
                        _node(page, "MaterialBatchInput").get_by_test_id("dropdown_str_sample_column")
                    ).to_contain_text("specimen")
                if case == "02_twenty_files_upload":
                    originals = sorted((output / "inputs/twenty_csv").glob("specimen-[0-9][0-9].csv"))
                    assert len(originals) == 20, originals
                    _upload_files(
                        page,
                        _node(page, "MaterialBatchInput"),
                        originals,
                    )
                sink = _node(page, "MaterialBatchSummary")
                page.screenshot(path=str(output / (case + "-before.png")), animations="disabled")
                print(f"Run {case}", flush=True)
                _run(sink)
                print(f"Copy report {case}", flush=True)
                report = _copy_report(page, sink, "MaterialBatchSummary")
                assert report["counts"] == {"total": 20, "completed": 20, "failed": 0, "skipped": 0}, report
                assert all(row["quality_findings"] == 0 for row in report["items"])
                for row in report["items"]:
                    i = int(re.findall(r"\d+", row["batch_label"])[-1]) - 1
                    assert abs(row["elastic_modulus_MPa"] - 200000 * (1 + i / 10)) < 1e-6
                page.screenshot(path=str(output / (case + ".png")), animations="disabled")
                results["cases"][case] = {
                    "counts": report["counts"],
                    "nodes": len(payload["data"]["nodes"]),
                    "edges": len(payload["data"]["edges"]),
                    "verified_moduli": 20,
                }
            assert not results["page_errors"] and not results["http_errors"], results
            assert results["discovery"].get("component_count") == 64, results["discovery"]
            results["passed"] = True
        except Exception as error:
            results["error"] = str(error)
            page.screenshot(path=str(output / "failure.png"), animations="disabled")
            (output / "failure.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
            raise
        finally:
            (output / "acceptance.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            browser.close()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7867")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/ui-batch-acceptance")
    parser.add_argument("--executable")
    args = parser.parse_args()
    print(json.dumps(accept_ui(args.base_url, args.output, args.executable), ensure_ascii=False))
