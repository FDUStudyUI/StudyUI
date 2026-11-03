"""Use real native controls to verify eight-curve features, statistics and bands.

Import, edit, run, inspect and copy all happen through a fresh headless browser.
Synthetic examples establish integration behavior, not experimental mode identity.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

from scripts.ui_acceptance import _output_dialog, _write_json
from scripts.ui_forms_acceptance import _choose, _copy_report, _field, _html, _import, _node, _run

ROOT = Path(__file__).resolve().parents[1]


def _switch(node, name, enabled):
    control = node.get_by_test_id("toggle_bool_" + name)
    if (control.get_attribute("aria-checked") == "true") != enabled:
        control.click()
    expect(control).to_have_attribute("aria-checked", str(enabled).lower())


def _edit_spectrum_form(page, node):
    for name, temporary, final in [
        ("x_column", "x", "wavelength_nm"),
        ("y_column", "y", "intensity_counts"),
        ("x_unit", "um", "nm"),
        ("baseline_method", "none", "constant"),
    ]:
        _choose(page, node, name, temporary)
        _choose(page, node, name, final)
    _field(node, "intensity_unit").fill("instrument_counts")
    _field(node, "intensity_unit").fill("counts")
    _field(node, "intensity_unit").press("Tab")
    _switch(node, "lambda10_enabled", False)
    _switch(node, "lambda10_enabled", True)
    for name, temporary, final in [("lambda10_min_nm", "660", "650"), ("lambda10_max_nm", "840", "850")]:
        _field(node, name).fill(temporary)
        _field(node, name).fill(final)
        _field(node, name).press("Tab")


def _inspect_table(page, node, class_name, label, count, screenshot):
    inspect = node.get_by_test_id(f"output-inspection-{label}-{class_name.lower()}")
    expect(inspect).to_have_attribute("aria-label", "Inspect output", timeout=180000)
    inspect.click()
    dialog = _output_dialog(page)
    expect(dialog).to_contain_text(f"1 to {count} of {count}")
    page.screenshot(path=str(screenshot), animations="disabled")
    page.get_by_test_id("btn-close-modal").click()


def _check_spectrum(report):
    data = report["data"]
    assert data["counts"] == {"total": 8, "completed": 8, "failed": 0, "skipped": 0}
    assert data["lambda10_definition"] == "coupled_mode_candidate"
    assert data["lambda10_window_nm"] == [650, 850]
    curves = data["curve_summary"]
    assert [row["peak_position"] for row in curves] == [530] * 8
    assert [row["lambda10_nm"] for row in curves] == [700, 710, 720, 730, 740, 750, 760, 770]
    assert all(row["lambda10_candidate_count"] == 1 and not row["lambda10_ambiguous"] for row in curves)
    assert len(data["features"]) == 16
    assert sum(row["is_lambda10_candidate"] for row in data["features"]) == 8
    assert [row["n_curves"] for row in data["group_summary"]] == [4, 4]
    assert [row["lambda10_nm_mean"] for row in data["group_summary"]] == [715, 755]
    parameters = report["provenance"]["parameters"]
    assert parameters["x"] == "wavelength_nm" and parameters["y"] == "intensity_counts"
    assert parameters["x_unit"] == "nm" and parameters["intensity_unit"] == "counts"
    return data


def accept_ui(base_url, output, executable=None):
    from scripts.build_research_examples import build_examples

    if urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use an isolated loopback Langflow server")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    payloads = build_examples(output / "inputs")
    results = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "application": "Real Langflow UI in a fresh headless browser context",
        "json_typed": False,
        "cases": {},
        "page_errors": [],
        "http_errors": [],
        "limits": [
            "UI uses eight synthetic curves; 1360-curve stress is separate unit coverage.",
            "Lambda10 is a window-selected candidate, not an experimentally confirmed mode.",
        ],
    }
    with sync_playwright() as runtime:
        options = {"headless": True}
        if executable:
            options["executable_path"] = executable
        browser = runtime.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1900, "height": 1550}, permissions=["clipboard-read", "clipboard-write"]
        )
        page = context.new_page()
        page.set_default_timeout(60000)
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
            payload = payloads["01_eight_curve_features"]
            print("Import eight-curve feature pipeline", flush=True)
            _import(page, base_url, payload, output / "eight-curve-features.json")
            analyzer = _node(page, "BatchSpectrumAnalyzer")
            print("Edit native spectrum columns, units and candidate window", flush=True)
            _edit_spectrum_form(page, analyzer)
            page.screenshot(path=str(output / "01-spectrum-native-form.png"), animations="disabled")
            print("Run feature pipeline through the UI", flush=True)
            _run(_node(page, "ScienceExportReport"))
            spectrum = _copy_report(page, analyzer, "BatchSpectrumAnalyzer")
            data = _check_spectrum(spectrum)
            grouped_node = _node(page, "ScienceStatsGrouped")
            grouped = _copy_report(page, grouped_node, "ScienceStatsGrouped")
            records = grouped["table_preview"]["records"]
            assert [row["group"] for row in records] == ["A", "B"]
            assert [row["count"] for row in records] == [4, 4]
            assert [row["mean"] for row in records] == [715, 755]
            assert [row["unit"] for row in records] == ["nm", "nm"]
            filtered = _copy_report(page, _node(page, "SciencePreprocessFilter"), "SciencePreprocessFilter")
            assert filtered["table_summary"]["rows"] == 8
            _inspect_table(
                page, analyzer, "BatchSpectrumAnalyzer", "逐峰结构化特征", 16, output / "02-feature-table.png"
            )
            _inspect_table(
                page,
                grouped_node,
                "ScienceStatsGrouped",
                "结果表格",
                2,
                output / "03-group-statistics-table.png",
            )
            _write_json(output / "spectrum-report.json", spectrum)
            _write_json(output / "grouped-report.json", grouped)
            results["cases"]["eight_curve_features"] = {
                "curves": 8,
                "feature_rows": len(data["features"]),
                "window_candidate_rows": 8,
                "group_curve_counts": [4, 4],
                "lambda10_group_means_nm": [715, 755],
                "primary_peak_nm": 530,
                "window_nm": [650, 850],
                "nodes_retained": len(payload["data"]["nodes"]),
                "edges_retained": len(payload["data"]["edges"]),
                "controls": [
                    "x_column",
                    "y_column",
                    "x_unit",
                    "intensity_unit",
                    "baseline_method",
                    "lambda10_enabled",
                    "lambda10_min_nm",
                    "lambda10_max_nm",
                ],
            }
            print(
                "UI verified eight full curves, 16 feature rows, candidate filtering and two group means",
                flush=True,
            )

            payload = payloads["02_eight_curve_bands"]
            print("Import eight-curve band pipeline", flush=True)
            _import(page, base_url, payload, output / "eight-curve-bands.json")
            plot = _node(page, "ScienceVizSpectra")
            _choose(page, plot, "cfg_band", "sd")
            _choose(page, plot, "cfg_band", "iqr")
            _run(_node(page, "ScienceExportReport"))
            report = _copy_report(page, plot, "ScienceVizSpectra")
            assert report["data"]["method"] == "band"
            bands = report["data"]["plot_data"]["bands"]
            assert len(bands) == 2 and all(band["n_curves"] == 4 for band in bands)
            assert all(len(band["x"]) == 501 and not band["interpolated"] for band in bands)
            assert all(
                any(hi > lo for hi, lo in zip(band["upper"], band["lower"], strict=True)) for band in bands
            )
            final = _copy_report(page, _node(page, "ScienceExportReport"), "ScienceExportReport")
            images = _html(context, final, output / "04-band-html.png")
            assert images
            _write_json(output / "band-report.json", report)
            page.screenshot(path=str(output / "05-band-canvas.png"), animations="disabled")
            results["cases"]["eight_curve_bands"] = {
                "curves": 8,
                "groups": 2,
                "curves_per_band": 4,
                "points_per_band": 501,
                "band": "iqr",
                "nonzero_band_width": True,
                "embedded_images_decoded": len(images),
                "edges_retained": len(payload["data"]["edges"]),
                "controls": ["cfg_band"],
            }
            print("UI verified two real spectral IQR bands and decoded HTML PNG", flush=True)
            assert not results["page_errors"], results["page_errors"]
            assert not results["http_errors"], results["http_errors"]
            results["passed"] = True
        except Exception as error:
            results["passed"] = False
            results["error"] = str(error)
            page.screenshot(path=str(output / "failure.png"), animations="disabled")
            (output / "failure.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
            raise
        finally:
            _write_json(output / "acceptance.json", results)
            browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7872")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/ui-research-acceptance")
    parser.add_argument("--chrome-executable")
    args = parser.parse_args()
    result = accept_ui(args.base_url, args.output, args.chrome_executable)
    print(json.dumps({"passed": result["passed"], "cases": result["cases"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
