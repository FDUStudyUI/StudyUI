"""Small regressions for real-form browser locators; E2E remains separate."""

import importlib
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="requires ui-test extra")

ui = importlib.import_module("scripts.ui_forms_acceptance")


@pytest.fixture
def page():
    with playwright.sync_playwright() as runtime:
        options = {"headless": True}
        if executable := os.environ.get("PLAYWRIGHT_CHROME_EXECUTABLE"):
            options["executable_path"] = executable
        browser = runtime.chromium.launch(**options)
        page = browser.new_page()
        page.set_default_timeout(5000)
        yield page
        browser.close()


def test_range_control_targets_mechanics_after_import_renames_suffix(page):
    page.set_content("""
      <div class="react-flow__node" data-id="ScienceVizMechanics-OTHER">
        <input data-testid="float_float_cfg_fit_range_max" value="99">
      </div>
      <div class="react-flow__node" data-id="ScienceMaterialsMechanics-random123">
        <input data-testid="float_float_cfg_fit_range_max" value="0">
      </div>""")
    ui._field(ui._node(page, "ScienceMaterialsMechanics"), "cfg_fit_range_max").fill("0.0008")
    assert page.locator('[data-id="ScienceVizMechanics-OTHER"] input').input_value() == "99"
    assert page.locator('[data-id="ScienceMaterialsMechanics-random123"] input').input_value() == "0.0008"


def test_dropdown_control_is_scoped_to_edited_node(page):
    page.set_content("""
      <div class="react-flow__node" data-id="ScienceVizMechanics-unrelated">
        <button data-testid="dropdown_str_cfg_method">overlay</button>
      </div>
      <div class="react-flow__node" data-id="SciencePreprocessMissing-imported">
        <button data-testid="dropdown_str_cfg_method"
          onclick="document.getElementById('choices').hidden=false">keep</button>
      </div>
      <div id="choices" hidden><div role="option" onclick="
        document.querySelector('[data-id=SciencePreprocessMissing-imported] button').innerText='linear';
        this.parentNode.hidden=true">linear</div></div>""")
    ui._choose(page, ui._node(page, "SciencePreprocessMissing"), "cfg_method", "linear")
    assert (
        ui._node(page, "ScienceVizMechanics").get_by_test_id("dropdown_str_cfg_method").inner_text()
        == "overlay"
    )


def test_native_rule_table_dialog_excludes_assistant_onboarding(page):
    page.set_content("""
      <div role="dialog" data-testid="assistant-onboarding-tooltip">Assistant</div>
      <div role="dialog"><button data-testid="add-row-button">Add row</button>
        <div class="ag-cell">stress</div></div>""")
    assert ui._rule_table_dialog(page).count() == 1
    assert ui._rule_table_dialog(page).locator(".ag-cell").inner_text() == "stress"
