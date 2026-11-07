"""Run evidence-guided scientific workflows through real native Langflow controls."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

import numpy as np
from playwright.sync_api import sync_playwright

from scripts.build_paper_examples import build_examples
from scripts.ui_acceptance import _write_json
from scripts.ui_forms_acceptance import (
    _assert_form_templates,
    _capture_ui_templates,
    _choose,
    _copy_report,
    _import,
    _node,
    _read_report_section,
    _run,
)


def _report_views(context, report, output, case):
    """Capture readable viewports as long JSON reports exceed image preview height."""
    page = context.new_page()
    try:
        page.goto(Path(report["data"]["file_path"]).as_uri(), wait_until="load")
        assert _read_report_section(page, "Data sources")
        images = page.locator("img").evaluate_all(
            "ims=>ims.map(im=>({complete:im.complete,width:im.naturalWidth,height:im.naturalHeight}))"
        )
        assert all(item["complete"] and item["width"] and item["height"] for item in images)
        page.screenshot(path=str(output / f"{case}-report.png"), animations="disabled", full_page=True)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(output / f"{case}-report-overview.png"), animations="disabled")
        evidence = page.get_by_role("heading", name="Evidence-linked claims", exact=True)
        if evidence.count():
            evidence.scroll_into_view_if_needed()
            page.screenshot(path=str(output / f"{case}-report-evidence.png"), animations="disabled")
    finally:
        page.close()


def _save_goal(page, expected):
    """Use native save, then read back the persisted field without an API mutation."""
    page.keyboard.press("Control+s")
    parsed = urlparse(page.url)
    endpoint = f"{parsed.scheme}://{parsed.netloc}/api/v1/flows/{parsed.path.rstrip('/').split('/')[-1]}"
    deadline = monotonic() + 30
    while monotonic() < deadline:
        response = page.request.get(endpoint)
        assert response.ok, f"Flow save readback returned HTTP {response.status}"
        nodes = response.json()["data"]["nodes"]
        node = next(item for item in nodes if item["data"].get("type") == "ScienceLitMethodRecommend")
        if node["data"]["node"]["template"]["cfg_goal"]["value"] == expected:
            return {"method": "native Control+s and read-only GET", "goal": expected, "http": response.status}
        page.wait_for_timeout(200)
    raise AssertionError("Edited method goal was not persisted")


def accept_ui(base_url, output, executable=None):
    if urlparse(base_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Use an isolated loopback Langflow instance")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipt = {
        "passed": False,
        "utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "json_typed": False,
        "cases": {},
        "page_errors": [],
        "http_errors": [],
        "native_edits": [],
    }
    templates = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
        context = browser.new_context(
            viewport={"width": 2000, "height": 1450}, permissions=["clipboard-read", "clipboard-write"]
        )
        page = context.new_page()
        page.set_default_timeout(60000)
        receipt["browser_version"] = browser.version
        page.on("request", lambda request: _capture_ui_templates(request, templates))
        page.on("pageerror", lambda error: receipt["page_errors"].append(str(error)))
        page.on(
            "response",
            lambda response: (
                receipt["http_errors"].append(f"{response.status} {response.url}")
                if response.status >= 400 and "/api/" in response.url
                else None
            ),
        )
        try:
            for case, payload in build_examples(output / "flows").items():
                print(f"Paper UI: {case}", flush=True)
                _import(page, base_url, payload, output / f"{case}.json")
                if case == "04_incompatible_method":
                    _choose(page, _node(page, "ScienceLitMethodRecommend"), "cfg_goal", "absolute_intensity")
                    receipt["native_edits"].append(
                        {"case": case, "field": "goal", "value": "absolute_intensity"}
                    )
                sink = _node(page, "ScienceExportReport")
                _run(sink)
                report = _copy_report(page, sink, "ScienceExportReport")
                assert report["artifacts"], report
                _write_json(output / f"{case}-report.json", report)
                _report_views(context, report, output, case)
                checks = {}
                if case == "01_spectrum_evidence":
                    methods = _copy_report(
                        page, _node(page, "ScienceLitMethodRecommend"), "ScienceLitMethodRecommend"
                    )
                    asls = next(row for row in methods["data"]["candidates"] if row["method_id"] == "asls")
                    assert asls["status"] == "eligible" and asls["execution"] is not None, asls
                    _write_json(output / f"{case}-methods.json", methods)
                    details = _copy_report(
                        page, _node(page, "ScienceMaterialsSpectra"), "ScienceMaterialsSpectra"
                    )
                    position = details["data"]["peaks"][0]["position"]
                    assert abs(position - 720) < 1e-8, position
                    evidence = _copy_report(
                        page, _node(page, "ScienceLitResultEvidence"), "ScienceLitResultEvidence"
                    )
                    bundle = evidence["data"]["evidence_bundle"]
                    peak = next(
                        c
                        for c in bundle["claims"]
                        if c.get("result_ref", {}).get("column") == "peak_position"
                    )
                    assert peak["result_ref"]["value"] == position
                    assert peak["result_ref"]["unit"] == "nm", peak
                    assert len(bundle["table_sha256"]) == 64
                    checks = {
                        "peak_nm": position,
                        "method_status": asls["status"],
                        "cell_status": peak["status"],
                        "table_sha256": bundle["table_sha256"],
                    }
                    _write_json(output / f"{case}-evidence.json", evidence)
                elif case == "02_pls_holdout":
                    details = _copy_report(
                        page, _node(page, "ScienceMaterialsChemometrics"), "ScienceMaterialsChemometrics"
                    )
                    model = details["data"]
                    assert model["metrics"]["test"]["n_samples"] == 10
                    assert model["metrics"]["test"]["rmse"] < 0.2, model["metrics"]
                    assert not set(model["train_sample_ids"]) & set(model["test_sample_ids"])
                    assert model["cv"]["enabled"] is True
                    checks = {
                        "test_metrics": model["metrics"]["test"],
                        "selected_components": model["model"]["n_components"],
                    }
                elif case == "03_local_repair":
                    details = _copy_report(
                        page, _node(page, "ScienceMaterialsAnalysisPlan"), "ScienceMaterialsAnalysisPlan"
                    )
                    rows = details["table_preview"]["records"]
                    means = {row["group"]: row["mean"] for row in rows}
                    np.testing.assert_allclose(
                        [means["A"], means["B"]], [-2.5 / np.sqrt(7.5), 2.5 / np.sqrt(7.5)]
                    )
                    assert all(row["count"] == 4 for row in rows)
                    assert details["data"]["execution_status"] == "completed"
                    checks = {"group_means": means, "execution_count": details["data"]["execution_count"]}
                else:
                    details = _copy_report(
                        page, _node(page, "ScienceLitMethodRecommend"), "ScienceLitMethodRecommend"
                    )
                    snv = next(row for row in details["data"]["candidates"] if row["method_id"] == "snv")
                    assert snv["status"] == "blocked" and snv["execution"] is None, snv
                    assert "goal_requires_original_intensity" in snv["blocked"], snv
                    checks = {"method_id": "snv", "status": snv["status"], "blocked": snv["blocked"]}
                    checks["saved_edit"] = _save_goal(page, "absolute_intensity")
                _write_json(output / f"{case}-result.json", details)
                page.screenshot(path=str(output / f"{case}-canvas.png"), animations="disabled")
                receipt["cases"][case] = {"url": page.url, "passed": True, "checks": checks}
            receipt["observed_forms"] = _assert_form_templates(
                templates,
                {
                    "ScienceLitMethodRecommend",
                    "ScienceMaterialsChemometrics",
                    "ScienceMaterialsAnalysisPlan",
                    "ScienceLitResultEvidence",
                },
            )
            assert not receipt["page_errors"] and not receipt["http_errors"], receipt
            receipt["passed"] = True
        except Exception as error:
            receipt["error"] = f"{type(error).__name__}: {error}"
            page.screenshot(path=str(output / "failure.png"), animations="disabled")
            raise
        finally:
            _write_json(output / "acceptance.json", receipt)
            browser.close()
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7867")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-paper-acceptance"))
    parser.add_argument("--executable")
    args = parser.parse_args()
    accept_ui(args.base_url, args.output, args.executable)
