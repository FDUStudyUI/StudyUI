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


def test_read_actual_report_disclosures_and_restore_compact_view(page, tmp_path):
    from pathlib import Path

    from materials_quality.science.viz_report import build_report

    data = {"sources": [{"sha256": "source-id"}], "results": {"mean": 42}, "warnings": []}
    report = build_report(None, {"output_dir": str(tmp_path)}, data)
    page.goto(Path(report.artifacts[0]).as_uri())
    assert ui._read_report_section(page, "Data sources") == data["sources"]
    assert ui._read_report_section(page, "Complete results") == data["results"]
    assert page.locator("details[open]").count() == 0


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


def test_source_upload_recovers_when_late_autoselect_races_the_first_click(page, tmp_path):
    """Langflow publishes saved rows before the upload callback auto-selects."""
    source = tmp_path / "specimen.csv"
    source.write_text("strain,stress\n0,0\n", encoding="utf-8")
    page.set_content("""
      <div id="node"><button data-testid="button_open_file_management"
        onclick="document.getElementById('files').hidden=false">Select file</button></div>
      <div role="dialog" id="files" hidden>
        <button data-testid="drag-files-component"
          onclick="document.getElementById('upload').click()">Upload</button>
        <input id="upload" type="file" hidden>
        <div id="rows"></div>
        <button data-testid="select-files-modal-button" onclick="
          if(document.querySelector('[role=checkbox]').getAttribute('aria-checked')==='true'){
            document.body.dataset.selected='true';document.getElementById('files').hidden=true
          }">Select files</button>
      </div>
      <script>
        document.getElementById('upload').onchange = event => {
          const name = event.target.files[0].name.replace(/\\.[^.]+$/, '');
          const row = document.createElement('div');
          row.dataset.testid = 'file-item-' + name;
          row.style.cssText = 'width:400px;height:60px';
          row.innerHTML = '<button role="checkbox" aria-checked="false">Select</button>'
            + '<button data-testid="context-menu-button-' + name + '">Actions</button>';
          const checkbox = row.querySelector('[role=checkbox]');
          const toggle = () => {
            document.body.dataset.clicks = String(Number(document.body.dataset.clicks || 0) + 1);
            checkbox.setAttribute('aria-checked', checkbox.getAttribute('aria-checked') !== 'true');
          };
          row.onclick = toggle;
          checkbox.onclick = event => {event.stopPropagation();toggle()};
          let delivered = false;
          row.onpointerdown = () => {
            if (!delivered) {
              delivered = true;
              // Upload Promise completion lands after the old aria read but before click.
              queueMicrotask(() => checkbox.setAttribute('aria-checked', 'true'));
            }
          };
          document.getElementById('rows').append(row);
        };
      </script>""")
    ui._source_upload(page, page.locator("#node"), source)
    assert page.locator("body").get_attribute("data-selected") == "true"
    assert page.locator("body").get_attribute("data-clicks") == "2"
