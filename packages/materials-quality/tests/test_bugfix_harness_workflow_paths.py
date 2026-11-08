"""Regression tests: workflow path validation must cover generated input names."""

import pytest

from materials_quality.agent.harness import StudyUIAgent


class _Workflows:
    def __init__(self, flow):
        self.flow = flow

    def get_flow(self, _flow_id):
        return self.flow


def _agent(tmp_path, flow):
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=_Workflows(flow), model=object())
    project_id = agent.store.create_project("path validation")
    session_id = agent.new_session(project_id=project_id)
    flow["folder_id"] = project_id
    return agent, session_id


def _workflow_with(config_name, value):
    return {
        "id": "flow-local",
        "folder_id": None,
        "data": {
            "nodes": [
                {
                    "id": "export-1",
                    "data": {
                        "type": "ScienceExportReport",
                        "node": {"template": {config_name: {"name": config_name, "value": value}}},
                    },
                }
            ],
            "edges": [],
        },
    }


def _table_import_workflow(path_value):
    template = {
        "cfg_path": {
            "name": "cfg_path",
            "display_name": "local file",
            "value": path_value,
            "info": "fill the absolute path of an existing file",
        },
        "cfg_delimiter": {"name": "cfg_delimiter", "value": ""},
    }
    node = {"id": "import-1", "data": {"type": "ScienceIoTableImport", "node": {"template": template}}}
    return {"id": "flow-local", "folder_id": None, "data": {"nodes": [node], "edges": []}}


@pytest.mark.parametrize("field", ["cfg_output_dir", "output_dir"])
def test_workflow_run_rejects_output_directory_outside_project(tmp_path, field):
    outside = tmp_path / "outside"
    outside.mkdir()
    flow = _workflow_with(field, str(outside))
    agent, session_id = _agent(tmp_path, flow)
    agent._turn_state.value = {"skill_preflight_complete": True, "canvas_run": None}

    with pytest.raises(PermissionError):
        agent._validate_workflow_local_paths(session_id, flow)
    with pytest.raises(PermissionError):
        agent._authorize_tool(session_id, "run_workflow", {"flow_id": "flow-local"}, "run the workflow")


def test_workflow_run_rejects_output_directory_tweak_outside_project(tmp_path):
    inside = tmp_path / "project-data"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    flow = _workflow_with("cfg_output_dir", "")
    agent, session_id = _agent(tmp_path, flow)
    agent.store.add_project_directory(agent.store.session_context(session_id)["project_id"], inside)
    agent._turn_state.value = {"skill_preflight_complete": True, "canvas_run": None}

    with pytest.raises(PermissionError):
        agent._validate_workflow_local_paths(session_id, flow, {"export-1": {"cfg_output_dir": str(outside)}})
    with pytest.raises(PermissionError):
        agent._authorize_tool(
            session_id,
            "run_workflow",
            {"flow_id": "flow-local", "tweaks": {"export-1": {"cfg_output_dir": str(outside)}}},
            "run the workflow",
        )


def test_template_field_metadata_is_not_treated_as_a_filesystem_path(tmp_path):
    inside = tmp_path / "project-data"
    inside.mkdir()
    source = inside / "measurements.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    flow = _table_import_workflow(str(source))
    agent, session_id = _agent(tmp_path, flow)
    agent.store.add_project_directory(agent.store.session_context(session_id)["project_id"], inside)
    agent._turn_state.value = {"skill_preflight_complete": True, "canvas_run": None}

    agent._validate_workflow_local_paths(session_id, flow)
    decision = agent._authorize_tool(
        session_id, "run_workflow", {"flow_id": "flow-local"}, "run the workflow"
    )
    assert decision["allowed"] is True


def test_empty_template_path_field_does_not_block_workflow_run(tmp_path):
    inside = tmp_path / "project-data"
    inside.mkdir()
    flow = _table_import_workflow("")
    agent, session_id = _agent(tmp_path, flow)
    agent.store.add_project_directory(agent.store.session_context(session_id)["project_id"], inside)
    agent._turn_state.value = {"skill_preflight_complete": True, "canvas_run": None}

    agent._validate_workflow_local_paths(session_id, flow)
    decision = agent._authorize_tool(
        session_id, "run_workflow", {"flow_id": "flow-local"}, "run the workflow"
    )
    assert decision["allowed"] is True


def test_in_file_dataset_paths_are_not_treated_as_local_files(tmp_path):
    inside = tmp_path / "project-data"
    inside.mkdir()
    flow = {
        "id": "flow-local",
        "folder_id": None,
        "data": {
            "nodes": [
                {
                    "id": "instrument-1",
                    "data": {
                        "type": "ScienceIoInstrumentImport",
                        "node": {
                            "template": {
                                "dataset_path": {"name": "dataset_path", "value": "/entry/data/data"},
                                "x_axis_path": {"name": "x_axis_path", "value": "/entry/x"},
                            }
                        },
                    },
                }
            ],
            "edges": [],
        },
    }
    agent, session_id = _agent(tmp_path, flow)
    agent.store.add_project_directory(agent.store.session_context(session_id)["project_id"], inside)

    agent._validate_workflow_local_paths(session_id, flow)
