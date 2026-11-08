"""Offline end-to-end acceptance: uploaded file -> inspect -> workflow -> completed run.

Mirrors the user journey that failed in the portable demo (session d432bbb9):
a Ti64 CSV is uploaded into a project session, inspected through the real
harness authorization path (no extra project directories), used as an
absolute cfg_path in a workflow built through the real workflow machinery,
and executed locally by FileWorkflowClient with no model/network calls.
"""

import json
from pathlib import Path

import pytest

from materials_quality.agent import uploads
from materials_quality.agent.data_inspection import inspect_file
from materials_quality.agent.file_workflow_client import FileWorkflowClient
from materials_quality.agent.harness import StudyUIAgent, _compact_run_result
from materials_quality.agent.workflow import apply_actions
from materials_quality.demos.catalog import get_dataset, read_demo_bytes
from materials_quality.demos.reference import load_reference_flow

DATASET = "ti64_tensile"
WORKFLOW_TYPES = (
    "ScienceIoTableImport",
    "ScienceMaterialsMechanics",
    "ScienceVizMechanics",
    "ScienceExportReport",
)


def _catalog():
    """Catalog of the real installed component classes (bundles from the verified reference flow)."""
    flow = load_reference_flow(DATASET)
    return {
        "materials_demo": {
            node["data"]["type"]: node["data"]["node"]
            for node in flow["data"]["nodes"]
            if node["data"]["type"] in WORKFLOW_TYPES
        }
    }


@pytest.fixture
def agent(tmp_path):
    workflows, components = tmp_path / "workflows", tmp_path / "components"
    workflows.mkdir()
    components.mkdir()
    harness = StudyUIAgent(
        tmp_path / "agent.sqlite3",
        langflow=FileWorkflowClient(workflows, components, catalog_loader=_catalog),
        model=object(),
    )
    project = harness.store.create_project("上传数据项目")
    session = harness.new_session("上传数据会话", project_id=project)
    return harness, project, session


def _upload(harness, session):
    item = get_dataset(DATASET)
    saved = uploads.save_upload(harness, session, item["filename"], read_demo_bytes(DATASET))
    return Path(saved["path"]), item


def _build_flow(harness, session, csv_path, *, with_report):
    client = harness.langflow
    catalog = client.component_catalog()
    flow = client.create_flow("上传数据力学工作流", project_id=harness._session_project(session))

    def add(node_id, component_type, x):
        return {
            "op": "add_node",
            "node_id": node_id,
            "component_type": component_type,
            "x": x,
            "y": 0,
        }

    def connect(source, output, target, input_name):
        return {
            "op": "connect",
            "source": source,
            "output": output,
            "target": target,
            "input": input_name,
        }

    actions = [
        add("import", "ScienceIoTableImport", 0),
        add("mechanics", "ScienceMaterialsMechanics", 420),
        add("viz", "ScienceVizMechanics", 840),
        {
            "op": "set_node_config",
            "node_id": "import",
            "config": {"cfg_path": str(csv_path), "cfg_delimiter": "auto"},
        },
        connect("import", "table", "mechanics", "input_table"),
        connect("import", "report", "mechanics", "input_data"),
        connect("import", "table", "viz", "input_table"),
        connect("import", "report", "viz", "input_data"),
    ]
    if with_report:
        actions.append(add("report", "ScienceExportReport", 1260))
        actions.append(connect("mechanics", "report", "report", "reports"))
        actions.append(connect("viz", "report", "report", "reports"))
    flow = client.get_flow(flow["id"])
    candidate, _ = apply_actions(flow, actions, catalog)
    client.update_flow(flow["id"], candidate)
    return flow["id"]


def test_uploaded_file_is_inspectable_without_project_directories(agent):
    harness, project, session = agent
    path, item = _upload(harness, session)
    assert harness.store.project_directories(project) == []
    assert path.is_file() and path.is_relative_to(harness.working_directory(session) / "uploads" / session)
    user_text = f'请读取并分析已上传的材料数据文件 "{path}"'

    resolved = harness._authorized_research_file(session, str(path), user_text)
    assert resolved == path.resolve()
    report = inspect_file(resolved)
    assert report["sha256"] == item["sha256"]
    assert report["format"] == ".csv"
    assert report["first_row_text_labels"]


def test_other_session_upload_is_denied_with_actionable_message(agent):
    harness, _, session = agent
    project_id = harness.store.session_context(session)["project_id"]
    other_session = harness.new_session("另一个会话", project_id=project_id)
    other_path, _ = _upload(harness, other_session)
    with pytest.raises(PermissionError, match="未授权|不能访问|会话"):
        harness._authorized_research_file(session, str(other_path), f'请读取 "{other_path}"')


def test_uploaded_csv_workflow_runs_to_completed_with_chart_and_report(agent):
    harness, _, session = agent
    path, item = _upload(harness, session)
    harness._turn_state.value = {"skill_preflight_complete": True, "canvas_run": None}
    flow_id = _build_flow(harness, session, path, with_report=True)
    flow = harness.langflow.get_flow(flow_id)
    harness._require_project_flow(session, flow)
    harness._validate_workflow_local_paths(session, flow, {})
    decision = harness._authorize_tool(
        session, "run_workflow", {"flow_id": flow_id}, "请运行这个工作流并生成报告"
    )
    assert decision["allowed"] is True

    result = harness.langflow.run_flow(flow_id)
    assert result["flow_id"] == flow_id
    assert result["outputs"], "the workflow returned no output"
    artifacts = harness._store_generated_artifacts(result, session, flow=flow)
    names = [item["name"] for item in artifacts]
    report_artifact = next(item for item in artifacts if item["name"].endswith(".html"))
    assert "analysis-report.html" in names
    stored = harness.store.get_artifact(report_artifact["id"], session)
    html = Path(stored["path"]).read_text(encoding="utf-8", errors="replace")
    # The delivered report embeds the mechanics chart and the uploaded source identity.
    assert "data:image/png;base64," in html
    assert item["sha256"] in html


def test_missing_absolute_path_message_points_to_upload_or_project_dir(agent):
    harness, _, session = agent
    missing = harness.working_directory(session) / "uploads" / session / "missing.csv"
    with pytest.raises(ValueError, match="文件不存在|完整绝对路径"):
        harness._authorized_research_file(session, str(missing), f'请检查 "{missing}"')


def test_bare_filename_denial_is_actionable(agent):
    harness, _, session = agent
    path, _ = _upload(harness, session)
    with pytest.raises(ValueError, match="上传目录|完整绝对路径|不存在"):
        harness._authorized_research_file(session, path.name, f"请检查 {path.name}")


def test_three_node_chain_returns_mechanics_metrics_and_chart(agent):
    harness, _, session = agent
    path, _ = _upload(harness, session)
    harness._turn_state.value = {"skill_preflight_complete": True, "canvas_run": None}
    flow_id = _build_flow(harness, session, path, with_report=False)
    flow = harness.langflow.get_flow(flow_id)
    harness._validate_workflow_local_paths(session, flow, {})
    result = harness.langflow.run_flow(flow_id)
    # The run result must expose the mechanics metrics and the chart artifact, not
    # only the sink node output: elastic modulus and offset-yield data are serialized
    # and the viz report references the rendered PNG.
    raw_json = json.dumps(result, ensure_ascii=False, default=str)
    assert "elastic_modulus_MPa" in raw_json
    assert "yield_strain" in raw_json or "yield_offset" in raw_json
    assert ".png" in raw_json
    # The agent-facing projection keeps the mechanics-derived table and the chart name.
    compact = _compact_run_result(result, flow=flow)
    compact_json = json.dumps(compact, ensure_ascii=False, default=str)
    assert "strain_fraction" in compact_json and "stress_MPa" in compact_json
    assert "mechanics-overlay.png" in compact_json or ".png" in compact_json
