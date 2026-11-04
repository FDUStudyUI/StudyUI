"""Import and run the four expansion workflows in the actual Langflow UI."""

import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from scripts.build_expansion_examples import build_examples
from scripts.ui_acceptance import _write_json
from scripts.ui_forms_acceptance import _copy_report, _import, _node, _run
from scripts.ui_skill_acceptance import _set_number


def accept_ui(base_url, output, executable=None):
    if urlparse(base_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Use an isolated loopback Langflow instance")
    output.mkdir(parents=True, exist_ok=True)
    receipt = {"passed": False, "json_typed": False, "cases": {}, "page_errors": [], "http_errors": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
        page = browser.new_page(
            viewport={"width": 2000, "height": 1450}, permissions=["clipboard-read", "clipboard-write"]
        )
        page.set_default_timeout(60000)
        page.on("pageerror", lambda error: receipt["page_errors"].append(str(error)))
        page.on(
            "response",
            lambda r: (
                receipt["http_errors"].append(f"{r.status} {r.url}")
                if r.status >= 400 and "/api/" in r.url
                else None
            ),
        )
        try:
            for case, payload in build_examples(output / "flows").items():
                print(f"Expansion UI: {case}", flush=True)
                _import(page, base_url, payload, output / f"{case}.json")
                if case == "specimen":
                    _set_number(_node(page, "SciencePreprocessNormalize"), "cfg_calibration_blank", 0.25)
                sink = _node(page, "ScienceExportReport")
                _run(sink)
                report = _copy_report(page, sink, "ScienceExportReport")
                assert report["artifacts"]
                if case == "specimen":
                    merge = _node(page, "SciencePreprocessMerge")
                    details = _copy_report(page, merge, "SciencePreprocessMerge")
                    rows = details["table_preview"]["records"]
                    assert len(rows) == 6 and rows[0]["sample_id"] == "001"
                    assert abs(rows[0]["resistance_ohm"] - 200) < 1e-8
                    calibration = _copy_report(
                        page, _node(page, "SciencePreprocessNormalize"), "SciencePreprocessNormalize"
                    )
                    assert calibration["data"]["calibration"]["blank"]["value"] == 0.25
                elif case == "mechanics":
                    details = _copy_report(
                        page, _node(page, "ResearchSkillExecutor"), "ResearchSkillExecutor", "分析报告与追溯"
                    )
                    modulus = details["tables"]["table"]["preview"][0]["elastic_modulus_MPa"]
                    assert abs(modulus - 200000) < 1e-6
                elif case == "photoresponse":
                    details = _copy_report(page, _node(page, "ScienceExportTable"), "ScienceExportTable")
                    first = details["table_preview"]["records"][0]
                    assert abs(first["rise_time_s"] - 3.2) < 1e-8
                    assert abs(first["recovery_time_s"] - 3.2) < 1e-8
                else:
                    details = _copy_report(page, _node(page, "BatteryCycles"), "BatteryCycles")
                    assert details["data"]["counts"]["valid"] == 6
                    assert abs(details["data"]["cycles"][-1]["retention_pct"] - 90) < 1e-8
                _write_json(output / f"{case}-result.json", details)
                page.screenshot(path=str(output / f"{case}-canvas.png"), animations="disabled")
                receipt["cases"][case] = {"url": page.url, "passed": True}
            assert not receipt["page_errors"] and not receipt["http_errors"], receipt
            receipt["passed"] = True
        except Exception:
            page.screenshot(path=str(output / "failure.png"), animations="disabled")
            raise
        finally:
            _write_json(output / "acceptance.json", receipt)
            browser.close()
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7867")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-expansion-acceptance"))
    parser.add_argument("--executable")
    args = parser.parse_args()
    accept_ui(args.base_url, args.output.resolve(), args.executable)
