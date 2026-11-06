"""Exercise native scientific forms through isolated, headless Langflow UI.

Imports, source uploads, parameter edits, runs and result copying all use visible
browser controls. Never connects to an existing browser or user profile.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

from scripts.ui_acceptance import _home, _output_dialog, _write_json

ROOT = Path(__file__).resolve().parents[1]


def _node(page, class_name):
    return page.locator(f'.react-flow__node[data-id^="{class_name}-"]')


def _field(node, name):
    """Bind by stable SDK input name, independent of imported node suffix."""
    return node.locator(
        f'[data-testid="popover-anchor-input-{name}"], '
        f'[data-testid="float_float_{name}"], [data-testid="int_int_{name}"]'
    )


def _choose(page, node, name, value):
    control = node.get_by_test_id("dropdown_str_" + name)
    control.click()
    page.get_by_role("option", name=value, exact=True).click()
    expect(control).to_contain_text(value)


def _import(page, base_url, payload, path):
    payload["name"] = f"UI-FORM-{path.stem}-{uuid4().hex[:8]}"
    _write_json(path, payload)
    _home(page, base_url)
    with page.expect_file_chooser() as chooser:
        page.get_by_test_id("upload-project-button").click()
    chooser.value.set_files(str(path.resolve()))
    page.get_by_role("button", name="Open flow " + payload["name"], exact=True).click()
    page.wait_for_url("**/flow/**")
    expect(page.locator(".react-flow__node")).to_have_count(len(payload["data"]["nodes"]))
    page.get_by_test_id("canvas_controls_dropdown").click()
    page.get_by_test_id("fit_view").click()
    page.keyboard.press("Escape")
    expect(page.locator(".react-flow__edge")).to_have_count(len(payload["data"]["edges"]))


def _source_upload(page, node, path):
    # Fresh filenames avoid selecting an earlier acceptance run's uploaded file.
    original = path
    path = path.with_name(path.stem + "-" + uuid4().hex[:8] + path.suffix)
    path.write_bytes(original.read_bytes())
    node.get_by_test_id("button_open_file_management").click()
    dialog = page.get_by_role("dialog").filter(has=page.get_by_test_id("select-files-modal-button"))
    with page.expect_file_chooser() as chooser:
        dialog.get_by_test_id("drag-files-component").click()
    chooser.value.set_files(str(path.resolve()))
    item = dialog.locator(f'[data-testid="file-item-{path.name}"], [data-testid="file-item-{path.stem}"]')
    item.wait_for()
    # Upload placeholders already render a checkbox, but the upstream click
    # handler ignores them until progress disappears and file actions appear.
    item.locator('[data-testid^="context-menu-button-"]').wait_for(state="visible", timeout=60000)
    checkbox = item.get_by_role("checkbox")
    # The upload Promise auto-selects separately from the saved-row refresh.
    # If that continuation lands between check()'s state read and its click,
    # the click toggles the new selection off and Playwright reports it. Set
    # the desired state again through the checkbox, with a strict retry bound.
    for attempt in range(3):
        try:
            checkbox.check(timeout=10000)
            break
        except PlaywrightError as error:
            if attempt == 2 or "Clicking the checkbox did not change its state" not in str(error):
                raise
            print("Upload auto-selection raced the click; rechecking the visible file checkbox", flush=True)
    expect(checkbox).to_be_checked()
    dialog.get_by_test_id("select-files-modal-button").click()
    expect(dialog).not_to_be_visible(timeout=30000)


def _copy_report(page, node, class_name, label="结果与追溯"):
    inspect = node.get_by_test_id(f"output-inspection-{label}-{class_name.lower()}")
    expect(inspect).to_have_attribute("aria-label", "Inspect output", timeout=180000)
    inspect.click()
    expect(_output_dialog(page)).to_contain_text('"schema_version"')
    page.get_by_test_id("copy-output-button").click()
    result = json.loads(page.evaluate("navigator.clipboard.readText()"))
    page.get_by_test_id("btn-close-modal").click()
    return result


def _run(node):
    node.get_by_role("button", name="Run component", exact=True).click()


def _rule_table_dialog(page):
    return page.get_by_role("dialog").filter(has=page.get_by_test_id("add-row-button"))


def _edit_rule_table(page, node, name, row, screenshot=None):
    node.get_by_test_id("div-table_" + name).get_by_role("button").click()
    dialog = _rule_table_dialog(page)
    dialog.get_by_test_id("add-row-button").click()
    for column, value in row.items():
        cell = dialog.locator(f'.ag-row[row-index="0"] .ag-cell[col-id="{column}"]')
        cell.dblclick()
        editor = cell.locator("input")
        editor.fill(str(value))
        editor.press("Enter")
        expect(cell).to_contain_text(str(value))
    if screenshot:
        page.screenshot(path=str(screenshot), animations="disabled")
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog).not_to_be_visible()


def _capture_ui_templates(request, templates):
    """Observe UI-initiated save/build payloads; never makes an API request."""
    if request.method not in {"PATCH", "POST"} or "/api/" not in request.url:
        return
    try:
        body = request.post_data_json
    except Exception:
        return

    def visit(value, depth=0):
        if depth > 8:
            return
        if isinstance(value, dict):
            data = value.get("data", {})
            if isinstance(data, dict) and isinstance(data.get("node"), dict):
                template = data["node"].get("template", {})
                if "ui_mode" in template:
                    templates[value.get("id", data.get("id", "unknown"))] = {
                        "class": data.get("type"),
                        "endpoint": urlparse(request.url).path,
                        "fields": {
                            k: v.get("value")
                            for k, v in template.items()
                            if isinstance(v, dict)
                            and (k in {"ui_mode", "config_json"} or k.startswith("cfg_"))
                        },
                    }
            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    visit(nested, depth + 1)
        elif isinstance(value, list):
            for nested in value:
                visit(nested, depth + 1)

    visit(body)


def _assert_form_templates(templates, classes):
    seen = {}
    for item in templates.values():
        if item["class"] in classes:
            assert item["fields"]["ui_mode"] == "form", item
            assert item["fields"].get("config_json", "{}") == "{}", item
            seen[item["class"]] = item
    assert set(seen) == set(classes), (classes, list(seen))
    return seen


def _read_report_section(page, title):
    """Exercise a report disclosure and read the preserved structured payload."""
    section = page.locator("details").filter(has=page.get_by_text(title, exact=True))
    toggle = section.locator("summary")
    expect(toggle).to_be_visible()
    toggle.click()
    expect(section.locator("pre")).to_be_visible()
    value = json.loads(section.locator("pre").inner_text())
    toggle.click()
    return value


def _html(context, envelope, output, image_size=None):
    path = Path(envelope["data"]["file_path"])
    assert path.is_file()
    page = context.new_page()
    page.goto(path.as_uri(), wait_until="load")
    assert _read_report_section(page, "Data sources")
    images = page.locator("img").evaluate_all(
        "ims=>ims.map(im=>({complete:im.complete,width:im.naturalWidth,height:im.naturalHeight}))"
    )
    assert all(im["complete"] and im["width"] and im["height"] for im in images)
    if image_size:
        results = _read_report_section(page, "Complete results")
        assert any(
            item.get("operation") == "io.image_import"
            and (item["data"]["width"], item["data"]["height"]) == image_size
            for item in results
        )
    page.screenshot(path=str(output), animations="disabled", full_page=True)
    page.close()
    return images


def accept_ui(base_url, output, executable=None):
    from scripts.build_form_examples import build_examples

    if urlparse(base_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Use an isolated loopback Langflow server")
    output = Path(output).resolve()
    inputs = output / "inputs"
    payloads = build_examples(inputs)
    results = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "application": "Real Langflow native forms, fresh headless browser context",
        "cases": {},
        "page_errors": [],
        "http_errors": [],
        "json_typed": False,
    }
    with sync_playwright() as runtime:
        options = {"headless": True}
        if executable:
            options["executable_path"] = executable
        browser = runtime.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1800, "height": 1400}, permissions=["clipboard-read", "clipboard-write"]
        )
        page = context.new_page()
        templates = {}
        page.on("request", lambda request: _capture_ui_templates(request, templates))
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
        results["browser_version"] = browser.version
        try:
            _import(page, base_url, payloads["mechanics"], inputs / "mechanics.json")
            source = _node(page, "ScienceIoTableImport")
            _source_upload(page, source, inputs / "synthetic-tensile.csv")
            mechanics = _node(page, "ScienceMaterialsMechanics")
            for name, value in [
                ("cfg_x", "x"),
                ("cfg_y", "y"),
                ("cfg_strain_unit", "%"),
                ("cfg_stress_unit", "kPa"),
            ]:
                _choose(page, mechanics, name, value)
            for name, value in [
                ("cfg_x", "strain"),
                ("cfg_y", "stress"),
                ("cfg_strain_unit", "fraction"),
                ("cfg_stress_unit", "MPa"),
            ]:
                _choose(page, mechanics, name, value)
            _field(mechanics, "cfg_fit_range_min").fill("0")
            _field(mechanics, "cfg_fit_range_max").fill("0.0008")
            _field(mechanics, "cfg_fit_range_max").press("Tab")
            page.screenshot(path=str(output / "01-mechanics-form.png"), animations="disabled")
            sink = _node(page, "ScienceExportReport")
            _run(sink)
            final = _copy_report(page, sink, "ScienceExportReport")
            report = _copy_report(page, mechanics, "ScienceMaterialsMechanics")
            imported = _copy_report(page, source, "ScienceIoTableImport")
            assert imported["table_summary"]["rows"] == 401
            assert "specimen" in imported["table_summary"]["columns"]
            csv_hash = hashlib.sha256((inputs / "synthetic-tensile.csv").read_bytes()).hexdigest()
            assert csv_hash in imported["provenance"]["source_files"].values()
            assert abs(report["data"]["elastic_modulus_MPa"] - 200000) < 1e-5
            assert abs(report["data"]["yield_stress_MPa"] - 202.01005025125627) < 1e-5
            images = _html(context, final, output / "02-mechanics-html.png")
            assert images
            _write_json(output / "mechanics-report.json", report)
            _write_json(output / "mechanics-html-report.json", final)
            saved = _assert_form_templates(
                templates,
                [
                    "ScienceIoTableImport",
                    "ScienceMaterialsMechanics",
                    "ScienceVizMechanics",
                    "ScienceExportReport",
                ],
            )
            _write_json(output / "mechanics-ui-template-evidence.json", saved)
            results["cases"]["mechanics"] = {
                "source_rows": 401,
                "source_sha256": csv_hash,
                "elastic_modulus_MPa": report["data"]["elastic_modulus_MPa"],
                "yield_stress_MPa": report["data"]["yield_stress_MPa"],
                "embedded_images_decoded": len(images),
                "ui_mode": "form",
                "config_json": "{}",
                "edges_retained": len(payloads["mechanics"]["data"]["edges"]),
                "controls": [
                    "source_file upload",
                    "cfg_x",
                    "cfg_y",
                    "cfg_strain_unit",
                    "cfg_stress_unit",
                    "cfg_fit_range_min",
                    "cfg_fit_range_max",
                ],
            }
            print("UI FORM verified mechanics upload, fit, figure and HTML", flush=True)

            _import(page, base_url, payloads["image"], inputs / "image.json")
            image = _node(page, "ScienceIoImageImport")
            assert image.get_by_test_id("output-inspection-结果表格-scienceioimageimport").count() == 0
            _source_upload(page, image, inputs / "tiny.png")
            sink = _node(page, "ScienceExportReport")
            _run(sink)
            final = _copy_report(page, sink, "ScienceExportReport")
            report = _copy_report(page, image, "ScienceIoImageImport")
            assert report["data"]["width"] == 13 and report["data"]["height"] == 7
            assert report["table_summary"] is None and report["table_available"] is False
            _html(context, final, output / "03-image-html.png", image_size=(13, 7))
            _write_json(output / "image-report.json", report)
            page.screenshot(path=str(output / "04-image-ports.png"), animations="disabled")
            results["cases"]["image"] = {
                "width": 13,
                "height": 7,
                "table_socket_absent": True,
                "false_empty_table_absent": True,
                "controls": ["source_file upload"],
            }
            print("UI FORM verified image upload and metadata-only ports", flush=True)

            _import(page, base_url, payloads["quality"], inputs / "quality.json")
            _source_upload(page, _node(page, "ScienceIoTableImport"), inputs / "synthetic-tensile.csv")
            shared = _node(page, "MaterialQualityContext")
            shared.get_by_test_id("inputlist_str_required_columns_0").fill("not_present")
            shared.get_by_test_id("inputlist_str_required_columns_0").press("Tab")
            _edit_rule_table(
                page,
                shared,
                "constraint_rules",
                {"column": "stress", "max": 0},
                screenshot=output / "05a-shared-quality-table.png",
            )
            page.screenshot(path=str(output / "05-shared-quality-form.png"), animations="disabled")
            check = _node(page, "MaterialSchemaCheck")
            _run(check)
            quality = _copy_report(page, check, "MaterialSchemaCheck", "检查报告")
            assert quality["total_findings"] == 401, quality
            assert sum(f["code"] == "MISSING_COLUMN" for f in quality["findings"]) == 1
            assert sum(f["code"] == "SCHEMA_TEMPLATE" for f in quality["findings"]) == 400
            _write_json(output / "quality-report.json", quality)
            _write_json(
                output / "quality-ui-template-evidence.json",
                _assert_form_templates(templates, ["MaterialQualityContext", "MaterialSchemaCheck"]),
            )
            results["cases"]["quality"] = {
                "total_findings": 401,
                "missing_column_findings": 1,
                "constraint_findings": 400,
                "zero_bound_retained": True,
                "edges_retained": len(payloads["quality"]["data"]["edges"]),
                "controls": [
                    "source_file upload",
                    "required_columns list",
                    "constraint_rules table column/max",
                ],
            }
            print("UI FORM verified native shared rules, list and table", flush=True)

            _import(page, base_url, payloads["dynamic"], inputs / "dynamic.json")
            missing = _node(page, "SciencePreprocessMissing")
            expect(missing.get_by_test_id("dropdown_str_cfg_order_by")).to_have_count(0)
            _choose(page, missing, "cfg_method", "linear")
            expect(missing.get_by_test_id("dropdown_str_cfg_order_by")).to_be_visible()
            expect(missing.get_by_test_id("toggle_bool_cfg_continuous")).to_be_visible()
            page.screenshot(path=str(output / "06-dynamic-linear.png"), animations="disabled")
            results["cases"]["dynamic"] = {
                "method": "linear",
                "order_by_revealed": True,
                "continuous_revealed": True,
                "runtime_covered": False,
                "controls": ["cfg_method"],
            }
            print("UI FORM verified method-dependent preprocessing controls", flush=True)
            assert not results["page_errors"], results["page_errors"]
            assert not results["http_errors"], results["http_errors"]
            results["passed"] = True
        except Exception as error:
            results["passed"] = False
            results["error"] = str(error)
            page.screenshot(path=str(output / "failure.png"), animations="disabled")
            raise
        finally:
            _write_json(output / "ui-template-evidence.json", templates)
            _write_json(output / "acceptance.json", results)
            browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7871")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/ui-forms-acceptance")
    parser.add_argument("--chrome-executable")
    args = parser.parse_args()
    result = accept_ui(args.base_url, args.output, args.chrome_executable)
    print(json.dumps({"passed": result["passed"], "cases": result["cases"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
