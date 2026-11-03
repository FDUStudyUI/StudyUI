"""Run V2 candidate, unit, policy and failure lessons through actual native controls."""

import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

from scripts.build_reliability_examples import build_examples
from scripts.ui_acceptance import _write_json
from scripts.ui_forms_acceptance import _choose, _import, _node, _run
from scripts.ui_skill_acceptance import (
    _report_when,
    _save_native_controls,
    _saved_planner_fields,
    _set_number,
    _watch_writes,
)


def _reopen(page, writes, expected):
    _save_native_controls(page, writes, expected)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(".react-flow__node")).to_have_count(3)
    expect(page.locator(".react-flow__edge")).to_have_count(3)
    return _node(page, "ResearchSkillPlanner"), _node(page, "ResearchSkillExecutor")


def _plan(page, node, predicate=lambda plan: plan["ready"]):
    _run(node)
    return _report_when(page, node, "ResearchSkillPlanner", "经校验的分析计划", predicate)


def _result(page, node, predicate):
    _run(node)
    return _report_when(page, node, "ResearchSkillExecutor", "分析报告与追溯", predicate)


def accept_ui(base_url, output, executable=None):
    if urlparse(base_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("V2 UI validation requires an isolated loopback service")
    output.mkdir(parents=True, exist_ok=True)
    payloads = build_examples(output / "flows")
    receipt = {"passed": False, "json_typed": False, "cases": {}, "page_errors": [], "http_errors": []}
    with sync_playwright() as runtime:
        options = {"headless": True}
        if executable:
            options["executable_path"] = executable
        browser = runtime.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1900, "height": 1650}, permissions=["clipboard-read", "clipboard-write"]
        )
        page = context.new_page()
        page.set_default_timeout(60000)
        writes = _watch_writes(page)
        page.on("pageerror", lambda e: receipt["page_errors"].append(str(e)))
        page.on(
            "response",
            lambda r: (
                receipt["http_errors"].append(f"{r.status} {r.url}")
                if r.status >= 400 and "/api/" in r.url
                else None
            ),
        )
        try:
            for case, payload in payloads.items():
                print(f"V2 UI: {case}", flush=True)
                _import(page, base_url, payload, output / f"{case}.json")
                # Assert the actual native values that the generated lesson and
                # subsequent user edits intend to persist, never the old server value.
                expected = {
                    k: v
                    for k, v in _saved_planner_fields(payload).items()
                    if k
                    in {
                        "task",
                        "selection_rule",
                        "prominence_mode",
                        "prominence",
                        "unit_mode",
                        "unit_confirmed",
                        "unit_column",
                        "small_sample_policy",
                        "window_confirmed",
                        "window_low",
                        "window_high",
                        "noise_confirmed",
                        "design",
                        "value_unit",
                    }
                }
                planner, executor = _node(page, "ResearchSkillPlanner"), _node(page, "ResearchSkillExecutor")
                plan = _plan(page, planner)
                assert plan["schema_version"] == "research-plan/2"
                assert plan["analysis_contract"]["contract_sha256"]
                planner, executor = _reopen(page, writes, expected)
                report = _result(page, executor, lambda r: r["schema_version"] == "research-result/1")
                if case == "competing":
                    assert report["tables"]["table"]["preview"][0]["window_candidate_nm"] == 730
                    planner, executor = _reopen(page, writes, expected)
                    _choose(page, planner, "selection_rule", "最红端候选")
                    expected["selection_rule"] = "最红端候选"
                    plan = _plan(
                        page, planner, lambda p: p["ready"] and p["parameters"]["selection_rule"] == "redmost"
                    )
                    planner, executor = _reopen(page, writes, expected)
                    expect(planner.get_by_test_id("dropdown_str_selection_rule")).to_contain_text(
                        "最红端候选"
                    )
                    report = _result(
                        page,
                        executor,
                        lambda r: r["tables"]["table"]["preview"][0].get("window_candidate_nm") == 790,
                    )
                    assert report["tables"]["table"]["preview"][0]["ambiguous"] is True
                    planner, executor = _reopen(page, writes, expected)
                    _choose(page, planner, "prominence_mode", "参考噪声窗口")
                    expected["prominence_mode"] = "参考噪声窗口"
                    expect(planner.get_by_test_id("toggle_bool_noise_confirmed")).to_be_visible()
                    pending = _plan(page, planner, lambda p: not p["ready"])
                    assert any(i["field"] == "noise_window" for i in pending["issues"])
                    planner, executor = _reopen(page, writes, expected)
                    _choose(page, planner, "prominence_mode", "指定突出度阈值")
                    expected["prominence_mode"] = "指定突出度阈值"
                    _set_number(planner, "prominence", 0.5)
                    expected["prominence"] = 0.5
                    _plan(page, planner)
                    planner, executor = _reopen(page, writes, expected)
                    report = _result(
                        page, executor, lambda r: r["plan"]["parameters"]["prominence_mode"] == "absolute"
                    )
                elif case == "nested":
                    pair = report["data"]["group_inference"]["pairwise"][0]
                    assert pair["n_a"] == pair["n_b"] == 3
                    assert abs(pair["mean_difference"] + 30) < 1e-9
                    assert report["tables"]["table"]["rows"] == 12
                    assert (
                        report["tables"]["table"]["contract"]["roles"]["experimental_unit"]
                        == "experimental_unit"
                    )
                elif case == "small_n":
                    assert report["status"] == "descriptive_only"
                    pair = report["data"]["pairwise"][0]
                    assert pair["p_raw"] is None and pair["mean_difference_ci_low"] is None
                    assert pair["n_a"] == pair["n_b"] == 2
                else:
                    assert report["status"] == "failed" and report["counts"]["failed"] == 1
                    assert report["tables"]["groups"]["preview"][0]["n_eligible"] == 0
                report_path = output / f"{case}-report.json"
                _write_json(report_path, report)
                html_path = next(Path(p) for p in report["artifacts"] if p.endswith("report.html"))
                view = context.new_page()
                view.goto(html_path.as_uri(), wait_until="load")
                expect(view.get_by_role("heading", name="StudyUI 科研分析报告", exact=True)).to_be_visible()
                images = view.locator("img").evaluate_all("ims=>ims.map(i=>i.complete&&i.naturalWidth>0)")
                assert all(images)
                if case in {"nested", "small_n"}:
                    assert images
                view.screenshot(path=str(output / f"{case}-report.png"), animations="disabled")
                view.close()
                page.screenshot(path=str(output / f"{case}-canvas.png"), animations="disabled")
                receipt["cases"][case] = {
                    "url": page.url,
                    "status": report["status"],
                    "images_decoded": len(images),
                    "contract": report["tables"]["table"]["contract"],
                    "controls": "native dropdowns, checkboxes and numbers; save/reopen retained",
                }
            assert not receipt["page_errors"] and not receipt["http_errors"], receipt
            receipt["passed"] = True
        except Exception:
            page.screenshot(path=str(output / "failure.png"), animations="disabled")
            (output / "failure.txt").write_text(page.locator("body").inner_text(), "utf-8")
            raise
        finally:
            receipt["saved_checkpoints"] = writes.get("saved_checkpoints", [])
            _write_json(output / "acceptance.json", receipt)
            browser.close()
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7867")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-reliability-acceptance"))
    parser.add_argument("--executable")
    args = parser.parse_args()
    accept_ui(args.base_url, args.output.resolve(), args.executable)
