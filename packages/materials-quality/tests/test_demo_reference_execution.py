"""Explicit reference runs execute a bound local graph without consulting a model."""

from copy import deepcopy

import pytest

from materials_quality.agent.harness import StudyUIAgent


class NeverModel:
    model = "must-not-be-called"

    def complete(self, *args, **kwargs):
        raise AssertionError("Reference workflow must not call an LLM")


class Workflows:
    def __init__(self):
        self.flow = {
            "id": "reference",
            "folder_id": None,
            "name": "Reference",
            "studyui_demo": {"dataset_id": "example", "source_sha256": "abc"},
            "data": {"nodes": [{"id": "n", "data": {"type": "SafeNode"}}], "edges": []},
        }
        self.runs = []

    def get_flow(self, flow_id):
        return deepcopy(self.flow)

    def run_flow(self, flow_id, **kwargs):
        self.runs.append((flow_id, kwargs))
        return {"flow_id": flow_id, "outputs": []}


@pytest.fixture
def reference(tmp_path, monkeypatch):
    from materials_quality.agent import reference_execution

    workflows = Workflows()
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=workflows, model=NeverModel())
    project = agent.store.create_project("reference")
    session = agent.new_session(project_id=project)
    workflows.flow["folder_id"] = project
    monkeypatch.setattr(
        reference_execution,
        "_reference_info",
        lambda _: (
            {"id": "example", "sha256": "abc"},
            {"data": {"nodes": [{"data": {"type": "SafeNode"}}]}},
        ),
    )
    return agent, workflows, project, session


def test_reference_canvas_never_calls_model_and_binds_snapshot(reference):
    agent, workflows, project, session = reference
    result = agent.run_canvas_workflow("reference", session_id=session)
    assert result["workflow_result"]["flow_id"] == "reference"
    assert result["model"] == "本地参考工作流"
    assert len(workflows.runs) == 1
    options = workflows.runs[0][1]
    assert options["external_data_approved"] is False
    assert options["expected_digest"]
    assert options["expected_project_id"] == project
    assert "reference_workflow_completed" in [row["kind"] for row in agent.store.events(session)]


@pytest.mark.parametrize("preset", ["read_only", "per_action"])
def test_reference_cannot_bypass_project_permissions(reference, preset):
    agent, workflows, project, session = reference
    agent.permissions.set_preset(project, preset)
    with pytest.raises(PermissionError):
        agent.run_canvas_workflow("reference", session_id=session)
    assert not workflows.runs


def test_reference_cannot_run_in_another_project(reference):
    agent, workflows, _, _ = reference
    session = agent.new_session(project_id=agent.store.create_project("other"))
    with pytest.raises(PermissionError):
        agent.run_canvas_workflow("reference", session_id=session)
    assert not workflows.runs


@pytest.mark.parametrize("change", ["ai", "unknown", "digest"])
def test_changed_reference_cannot_gain_unreviewed_execution(reference, change):
    agent, workflows, _, session = reference
    if change == "digest":
        workflows.flow["studyui_demo"]["source_sha256"] = "wrong"
    else:
        workflows.flow["data"]["nodes"][0]["data"]["type"] = (
            "StudyUIAIAnalysis" if change == "ai" else "ArbitraryPython"
        )
    with pytest.raises(ValueError):
        agent.run_canvas_workflow("reference", session_id=session)
    assert not workflows.runs


def test_failed_reference_does_not_record_completion(reference, monkeypatch):
    agent, workflows, _, session = reference

    def fail(*args, **kwargs):
        raise ValueError("bad parameter")

    monkeypatch.setattr(workflows, "run_flow", fail)
    with pytest.raises(ValueError, match="bad parameter"):
        agent.run_canvas_workflow("reference", session_id=session)
    kinds = [row["kind"] for row in agent.store.events(session)]
    assert "reference_workflow_failed" in kinds
    assert "reference_workflow_completed" not in kinds


def test_reference_cancel_after_compute_does_not_claim_completion(reference, monkeypatch):
    import threading

    from materials_quality.agent.tasks import TaskCancelled, _cancel

    agent, workflows, _, session = reference
    signal = threading.Event()

    def run(*args, **kwargs):
        signal.set()
        return {"outputs": []}

    monkeypatch.setattr(workflows, "run_flow", run)
    token = _cancel.set(signal)
    try:
        with pytest.raises(TaskCancelled):
            agent.run_canvas_workflow("reference", session_id=session)
    finally:
        _cancel.reset(token)
    assert "reference_workflow_completed" not in [e["kind"] for e in agent.store.events(session)]


def test_reference_allows_visual_analysis_parameter_changes(reference, monkeypatch):
    from materials_quality.agent import reference_execution
    from materials_quality.demos.catalog import get_dataset
    from materials_quality.demos.reference import load_reference_flow

    agent, workflows, project, session = reference
    original = load_reference_flow("raman_spectra")
    item = get_dataset("raman_spectra")
    workflows.flow = deepcopy(original)
    workflows.flow.update(
        id="reference",
        folder_id=project,
        studyui_demo={"dataset_id": item["id"], "source_sha256": item["sha256"]},
    )
    monkeypatch.setattr(reference_execution, "_reference_info", lambda _: (item, original))
    analysis = next(n for n in workflows.flow["data"]["nodes"] if n["id"].endswith("-analysis"))
    analysis["data"]["node"]["template"]["prominence"]["value"] = 0.75
    result = agent.run_canvas_workflow("reference", session_id=session)
    assert result["task_status"] == "completed"
    assert len(workflows.runs) == 1


@pytest.mark.parametrize("change", ["bundle", "path", "json_mode", "edge", "handle", "duplicate_source"])
def test_reference_pins_original_source_but_not_analysis_parameters(reference, monkeypatch, change):
    from materials_quality.agent import reference_execution
    from materials_quality.demos.catalog import get_dataset
    from materials_quality.demos.reference import load_reference_flow

    agent, workflows, project, session = reference
    original = load_reference_flow("ti64_tensile")
    item = get_dataset("ti64_tensile")
    workflows.flow = deepcopy(original)
    workflows.flow.update(
        id="reference",
        folder_id=project,
        studyui_demo={
            "dataset_id": item["id"],
            "source_sha256": item["sha256"],
        },
    )
    monkeypatch.setattr(reference_execution, "_reference_info", lambda _: (item, original))
    nodes = workflows.flow["data"]["nodes"]
    source = next(n for n in nodes if n["data"]["type"] == "ScienceFixtureBundle")
    imported = next(n for n in nodes if n["data"]["type"] == "ScienceIoTableImport")
    if change == "bundle":
        source["data"]["node"]["template"]["bundle_base64"]["value"] = "e30="
    elif change == "path":
        imported["data"]["node"]["template"]["cfg_path"]["value"] = "another.csv"
    elif change == "json_mode":
        imported["data"]["node"]["template"]["ui_mode"]["value"] = "json"
    elif change == "edge":
        workflows.flow["data"]["edges"] = []
    elif change == "handle":
        edge = next(e for e in workflows.flow["data"]["edges"] if e["target"] == imported["id"])
        edge["data"]["sourceHandle"]["name"] = "table"
    else:
        extra = deepcopy(source)
        extra["id"] += "-other"
        nodes.append(extra)
    with pytest.raises(ValueError, match="来源|导入|连接"):
        agent.run_canvas_workflow("reference", session_id=session)
    assert not workflows.runs
