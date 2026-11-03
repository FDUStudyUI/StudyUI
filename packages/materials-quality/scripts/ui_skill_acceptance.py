"""Verify real Skill controls, pending plans, execution and report rendering through UI."""

import argparse
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

from scripts.build_skill_examples import build_examples
from scripts.ui_acceptance import _write_json
from scripts.ui_forms_acceptance import _copy_report, _field, _import, _node, _run
from scripts.ui_research_acceptance import _switch


def _report_when(page, node, class_name, label, predicate):
    """Wait for the newly rendered output rather than accepting a previous run's JSON."""
    deadline = monotonic() + 30
    value = None
    while monotonic() < deadline:
        value = _copy_report(page, node, class_name, label=label)
        if predicate(value):
            return value
        page.wait_for_timeout(250)
    raise AssertionError(f"Expected updated output, got {value}")


def _set_number(node, name, value):
    # Langflow's controlled number editor can append a second fill() to its editing buffer.
    # Use real select/replace keystrokes and verify the visible value before running.
    control = _field(node, name)
    control.click()
    control.press("Control+A")
    control.press("Backspace")
    control.press_sequentially(str(value), delay=50)
    expect(control).to_have_value(str(value))
    control.press("Tab")


def _watch_writes(page):
    state = {"pending": set(), "last": monotonic()}

    def started(request):
        if request.method in {"POST", "PATCH", "PUT", "DELETE"} and "/api/" in request.url:
            state["pending"].add(request)
            state["last"] = monotonic()

    def finished(request):
        if request in state["pending"]:
            state["pending"].discard(request)
            state["last"] = monotonic()

    page.on("request", started)
    page.on("requestfinished", finished)
    page.on("requestfailed", finished)
    return state


def _saved_reopen(page, writes, expected_window):
    """Cross a save/reopen boundary before editing/running the next component.

    Langflow 1.13 can announce a newer flow revision after a component run while
    its editor is still saving. Reopening a settled flow also verifies that the
    confirmed parameters and all three connections survived persistence.
    """
    writes["last"] = monotonic()
    deadline = monotonic() + 30
    while writes["pending"] or monotonic() - writes["last"] < 1.5:
        if monotonic() > deadline:
            raise AssertionError("Flow writes did not settle before reopen")
        page.wait_for_timeout(100)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(".react-flow__node")).to_have_count(3)
    expect(page.locator(".react-flow__edge")).to_have_count(3)
    planner = _node(page, "ResearchSkillPlanner")
    expect(planner.get_by_test_id("toggle_bool_window_confirmed")).to_have_attribute("aria-checked", "true")
    assert float(_field(planner, "window_low").input_value()) == expected_window
    return planner, _node(page, "ResearchSkillExecutor")


def accept_ui(base_url, output, executable=None):
    if urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("UI acceptance requires an isolated loopback service")
    output.mkdir(parents=True, exist_ok=True)
    payloads = build_examples(output / "flows")
    results = {"cases": {}, "page_errors": [], "http_errors": [], "passed": False}
    with sync_playwright() as runtime:
        options = {"headless": True}
        if executable:
            options["executable_path"] = executable
        browser = runtime.chromium.launch(**options)
        context = browser.new_context(
            viewport={"width": 1900, "height": 1550}, permissions=["clipboard-read", "clipboard-write"]
        )
        page = context.new_page()
        writes = _watch_writes(page)
        page.set_default_timeout(60000)
        page.on("pageerror", lambda e: results["page_errors"].append(str(e)))
        page.on(
            "response",
            lambda r: (
                results["http_errors"].append(f"{r.status} {r.url}")
                if r.status >= 400 and "/api/" in r.url
                else None
            ),
        )
        try:
            for task, payload in payloads.items():
                print(f"Import and run skill {task}", flush=True)
                _import(page, base_url, payload, output / f"{task}.json")
                planner, executor = _node(page, "ResearchSkillPlanner"), _node(page, "ResearchSkillExecutor")
                if task == "spectra":
                    _switch(planner, "window_confirmed", False)
                    _run(planner)
                    pending = _report_when(
                        page, planner, "ResearchSkillPlanner", "经校验的分析计划", lambda p: not p["ready"]
                    )
                    _write_json(output / "pending-plan.json", pending)
                    assert not pending["ready"] and any(
                        i["field"] == "peak_window" for i in pending["issues"]
                    )
                    _switch(planner, "window_confirmed", True)
                    _set_number(planner, "window_low", 720)
                    _run(planner)
                    _report_when(
                        page,
                        planner,
                        "ResearchSkillPlanner",
                        "经校验的分析计划",
                        lambda p: p["ready"] and p["parameters"]["peak_window"] == [720, 850],
                    )
                    planner, executor = _saved_reopen(page, writes, 720)
                    _run(executor)
                    changed = _report_when(
                        page,
                        executor,
                        "ResearchSkillExecutor",
                        "分析报告与追溯",
                        lambda r: r.get("plan", {}).get("parameters", {}).get("peak_window") == [720, 850],
                    )
                    assert changed["tables"]["groups"]["preview"][0]["mean"] == 725
                    planner, executor = _saved_reopen(page, writes, 720)
                    _set_number(planner, "window_low", 650)
                    _run(planner)
                    _report_when(
                        page,
                        planner,
                        "ResearchSkillPlanner",
                        "经校验的分析计划",
                        lambda p: p["ready"] and p["parameters"]["peak_window"] == [650, 850],
                    )
                    planner, executor = _saved_reopen(page, writes, 650)
                _run(executor)
                report = _report_when(
                    page,
                    executor,
                    "ResearchSkillExecutor",
                    "分析报告与追溯",
                    lambda r, task=task: (
                        r.get("plan", {}).get("parameters", {}).get("peak_window") == [650, 850]
                        if task == "spectra"
                        else r.get("task") == task
                    ),
                )
                assert report["schema_version"] == "research-result/1" and report["status"] == "completed"
                assert report["provenance"]["raw_preserved"]
                if task == "spectra":
                    assert report["tables"]["features"]["rows"] == 16
                    assert [r["mean"] for r in report["tables"]["groups"]["preview"]] == [715, 755]
                if task == "mechanics":
                    assert report["counts"]["completed"] == 20
                    assert abs(report["tables"]["table"]["preview"][0]["elastic_modulus_MPa"] - 200000) < 1e-6
                if task == "contrast":
                    assert [r["count"] for r in report["tables"]["groups"]["preview"]] == [4, 4]
                html = next(Path(p) for p in report["artifacts"] if p.endswith(".html"))
                view = context.new_page()
                view.goto(html.as_uri(), wait_until="load")
                expect(view.get_by_role("heading", name="StudyUI 科研分析报告", exact=True)).to_be_visible()
                images = view.locator("img").evaluate_all("ims=>ims.map(i=>i.complete&&i.naturalWidth>0)")
                assert images and all(images)
                view.screenshot(path=str(output / f"{task}-report.png"), animations="disabled")
                view.close()
                page.screenshot(path=str(output / f"{task}-canvas.png"), animations="disabled")
                _write_json(output / f"{task}-report.json", report)
                results["cases"][task] = {
                    "url": page.url,
                    "counts": report["counts"],
                    "tables": report["tables"],
                    "images_decoded": len(images),
                }
            assert not results["page_errors"] and not results["http_errors"], results
            results["passed"] = True
        except Exception:
            page.screenshot(path=str(output / "failure.png"), animations="disabled")
            (output / "failure.txt").write_text(page.locator("body").inner_text(), "utf-8")
            raise
        finally:
            _write_json(output / "acceptance.json", results)
            browser.close()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:7867")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-skill-acceptance"))
    parser.add_argument("--executable")
    args = parser.parse_args()
    accept_ui(args.base_url, args.output.resolve(), args.executable)
