"""Regression tests for acceptance locators, separate from real Langflow E2E."""

import importlib
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="requires the ui-test extra and a browser")
ui = importlib.import_module("scripts.ui_acceptance")


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


def test_rule_editor_closure_ignores_an_unrelated_dialog(page):
    page.set_content("""
        <div role="dialog" data-testid="assistant-onboarding-tooltip">Try the assistant</div>
        <div class="react-flow__node" data-id="MaterialQualityContext-test">
          <button aria-label="Expand text editor"
            onclick="document.getElementById('editor').hidden=false">Edit</button>
        </div>
        <div role="dialog" id="editor" hidden>
          <textarea>old rules</textarea>
          <button data-testid="genericModalBtnSave"
            onclick="document.getElementById('editor').remove()">Finish Editing</button>
        </div>
    """)
    assert ui._edit_rules(page, "new rules") == "old rules"
    assert page.get_by_test_id("assistant-onboarding-tooltip").is_visible()
    assert page.locator("#editor").count() == 0


def test_output_viewer_selection_excludes_assistant_dialog(page):
    page.set_content("""
        <div role="dialog" data-testid="assistant-onboarding-tooltip">Try the assistant</div>
        <div role="dialog"><textarea>completed_checks=6</textarea>
          <button data-testid="btn-close-modal">Close</button>
        </div>
    """)
    assert ui._output_dialog(page).locator("textarea").input_value() == "completed_checks=6"
    assert ui._output_dialog(page).count() == 1
