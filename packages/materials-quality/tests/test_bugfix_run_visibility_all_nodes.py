"""Regression tests: run_workflow must expose every node output, bounded and actionable."""

import json

import pytest

from materials_quality.agent.file_workflow_client import FileWorkflowClient
from materials_quality.agent.harness import StudyUIAgent, _bounded_tool_content
from materials_quality.agent.workflow import flow_digest, flow_summary
from materials_quality.agent.workflow_executor import FileWorkflowExecutor


class _FlowStore:
    def __init__(self, flow):
        self.flow = flow

    def read(self, _flow_id):
        return self.flow, 1


def _mechanics_flow():
    return {
        "id": "flow-mech",
        "name": "Ti64 三节点力学",
        "description": "",
        "folder_id": None,
        "data": {
            "nodes": [
                {"id": "imp", "data": {"type": "ScienceIoTableImport"}},
                {"id": "mech", "data": {"type": "ScienceMaterialsMechanics"}},
                {"id": "viz", "data": {"type": "ScienceVizMechanics"}},
            ],
            "edges": [
                {"id": "e1", "source": "imp", "target": "mech"},
                {"id": "e2", "source": "mech", "target": "viz"},
            ],
        },
    }


def _run_payload(chart_path):
    rows = [
        {"strain_fraction": 0.001 * index, "stress_MPa": 210.0 * index, "specimen": "A"}
        for index in range(1, 5)
    ]
    return {
        "flow_id": "flow-mech",
        "revision": 3,
        "outputs": [
            {
                "outputs": [
                    {
                        "component_id": "imp",
                        "component_display_name": "导入",
                        "results": {"table": {"data": rows}, "summary": {"text": "导入 4 行"}},
                    },
                    {
                        "component_id": "mech",
                        "component_display_name": "力学分析",
                        "results": {
                            "table": {
                                "data": [
                                    {
                                        "source_row": row,
                                        "strain_fraction": row * 0.001,
                                        "stress_MPa": row * 210.0,
                                    }
                                    for row in range(1, 5)
                                ]
                            },
                            "report": {
                                "text": "elastic_modulus_MPa=110000.0; yield offset crossing absent",
                                "execution_status": "completed",
                            },
                            "summary": {"text": "弹性模量 110 GPa；未找到偏置线交点"},
                        },
                    },
                    {
                        "component_id": "viz",
                        "component_display_name": "应力应变图",
                        "results": {
                            "report": {"text": "已生成应力应变图"},
                            "artifacts": [{"path": str(chart_path), "sha256": "a" * 64}],
                        },
                    },
                ]
            }
        ],
    }


class _RecordingWorkflows:
    def __init__(self, flow, payload):
        self.flow = flow
        self.payload = payload
        self.calls = []

    def get_flow(self, _flow_id):
        return self.flow

    def run_flow(self, flow_id, **kwargs):
        self.calls.append({"flow_id": flow_id, **kwargs})
        return self.payload


def _agent_with_fake_workflow(tmp_path, flow, payload):
    workflows = _RecordingWorkflows(flow, payload)
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=workflows, model=object())
    project = agent.store.create_project("run visibility")
    session = agent.new_session(project_id=project)
    flow["folder_id"] = project
    agent.project_root = tmp_path
    agent._turn_state.value = {"skill_preflight_complete": True, "canvas_run": None}
    return agent, session, workflows


def test_run_workflow_requests_and_returns_every_node_output(tmp_path):
    chart = tmp_path / "stress_strain.png"
    chart.write_bytes(b"png")
    flow = _mechanics_flow()
    agent, session, workflows = _agent_with_fake_workflow(tmp_path, flow, _run_payload(chart))
    agent._approved_execution = {
        "approved": True,
        "session_id": session,
        "tool": "run_workflow",
        "args": {"flow_id": flow["id"]},
        "action": "workflow.run",
        "flow_id": flow["id"],
        "flow_digest": flow_digest(flow),
        "flow_project_id": flow["folder_id"],
    }

    result = agent._dispatch(session, "run_workflow", {"flow_id": flow["id"]}, "运行这个工作流")

    assert workflows.calls[0]["include_all_nodes"] is True
    assert result["status"] == "completed"
    compact = result["result"]
    assert compact["execution_status"] == "completed"
    assert compact["nodes_total"] == 3
    assert [node["node_id"] for node in compact["outputs"]] == ["imp", "mech", "viz"]
    mech = compact["outputs"][1]
    assert "elastic_modulus_MPa=110000.0" in mech["outputs"]["report"]["text"]
    assert "弹性模量" in mech["outputs"]["summary"]["text"]
    assert mech["outputs"]["table"]["rows"] == 4
    assert "strain_fraction" in mech["outputs"]["table"]["columns"]
    viz = compact["outputs"][2]
    assert viz["outputs"]["artifacts"]["files"] == [chart.name]


def test_run_workflow_falls_back_when_client_lacks_visibility_flag(tmp_path):
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    flow = _mechanics_flow()
    payload = _run_payload(chart)

    class _LegacyWorkflows:
        def __init__(self):
            self.calls = []

        def get_flow(self, _flow_id):
            return flow

        def run_flow(
            self,
            flow_id,
            input_value="",
            tweaks=None,
            external_data_approved=False,
            expected_digest=None,
            expected_project_id=None,
        ):
            self.calls.append(flow_id)
            return payload

    workflows = _LegacyWorkflows()
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=workflows, model=object())
    project = agent.store.create_project("legacy")
    session = agent.new_session(project_id=project)
    flow["folder_id"] = project
    agent.project_root = tmp_path
    agent._turn_state.value = {"skill_preflight_complete": True, "canvas_run": None}
    agent._approved_execution = {
        "approved": True,
        "session_id": session,
        "tool": "run_workflow",
        "args": {"flow_id": flow["id"]},
        "action": "workflow.run",
        "flow_id": flow["id"],
        "flow_digest": flow_digest(flow),
        "flow_project_id": flow["folder_id"],
    }

    result = agent._dispatch(session, "run_workflow", {"flow_id": flow["id"]}, "运行这个工作流")

    assert workflows.calls == [flow["id"]]
    assert [node["node_id"] for node in result["result"]["outputs"]] == ["imp", "mech", "viz"]


def test_bounded_run_result_keeps_every_node_id_within_budget():
    outputs = [
        {"node_id": f"node-{index}", "outputs": {"report": {"text": f"report {index} " * 220}}}
        for index in range(12)
    ]
    tool_result = {
        "status": "completed",
        "flow_name": "long run",
        "result": {"session_id": "s", "execution_status": "completed", "nodes_total": 12, "outputs": outputs},
        "artifacts": [],
    }

    content = _bounded_tool_content("run_workflow", tool_result)
    parsed = json.loads(content)

    assert len(content) <= 8_000
    node_ids = [node["node_id"] for node in parsed["result"]["outputs"]]
    assert node_ids == [f"node-{index}" for index in range(12)]
    assert parsed["result"]["nodes_total"] == 12
    assert "report 7" in content


def test_compact_run_result_exposes_failed_nodes_and_execution_status():
    from materials_quality.agent.harness import _compact_run_result

    payload = {
        "outputs": [
            {
                "outputs": [
                    {"component_id": "imp", "results": {"table": [{"x": 1, "y": 2}]}},
                    {
                        "component_id": "viz",
                        "status": "failed",
                        "error": "unit declarations must map existing columns",
                        "results": {},
                    },
                ]
            }
        ]
    }

    compact = _compact_run_result(payload)

    assert compact["execution_status"] == "failed"
    assert compact["nodes_total"] == 2
    assert compact["failed_nodes"] == [
        {
            "node_id": "viz",
            "status": "failed",
            "error": "unit declarations must map existing columns",
        }
    ]
    failed = next(node for node in compact["outputs"] if node["node_id"] == "viz")
    assert failed["execution_status"] == "failed"
    assert "unit declarations" in failed["error"]


def test_other_session_upload_permission_message_is_actionable(tmp_path):
    flow = _mechanics_flow()
    agent, session, _ = _agent_with_fake_workflow(tmp_path, flow, {"outputs": []})
    older = tmp_path / "uploads" / "old-session-1" / "Ti64.csv"
    older.parent.mkdir(parents=True)
    older.write_text("strain,stress\n0.001,210\n", encoding="utf-8")

    with pytest.raises(PermissionError) as excinfo:
        agent._require_project_local_path(session, str(older))

    message = str(excinfo.value)
    assert "其他会话" in message
    assert "重新上传" in message
    assert "管理可访问的本地文件夹" not in message


def test_unlisted_directory_message_still_offers_add_folder_and_upload(tmp_path):
    flow = _mechanics_flow()
    agent, session, _ = _agent_with_fake_workflow(tmp_path, flow, {"outputs": []})
    elsewhere = tmp_path / "elsewhere" / "data.csv"
    elsewhere.parent.mkdir()
    elsewhere.write_text("x,y\n1,2\n", encoding="utf-8")

    with pytest.raises(PermissionError) as excinfo:
        agent._require_project_local_path(session, str(elsewhere))

    message = str(excinfo.value)
    assert "管理可访问的本地文件夹" in message
    assert "重新上传" in message


def test_bare_filename_denial_names_the_actionable_fix(tmp_path):
    flow = _mechanics_flow()
    agent, session, _ = _agent_with_fake_workflow(tmp_path, flow, {"outputs": []})

    with pytest.raises(ValueError, match="完整绝对路径"):
        agent._authorized_research_file(session, "Ti64.csv", "请检查 Ti64.csv")


def test_missing_inspect_path_names_the_actionable_fix(tmp_path):
    flow = _mechanics_flow()
    agent, session, _ = _agent_with_fake_workflow(tmp_path, flow, {"outputs": []})

    with pytest.raises(PermissionError, match="上传|完整路径"):
        agent._dispatch(session, "inspect_research_file", {}, "读取数据文件")


def test_executor_include_all_nodes_requests_debug_and_keeps_legacy_default(monkeypatch):
    import lfx.load

    captured = {}

    def fake_run_flow_from_json(flow, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(lfx.load, "run_flow_from_json", fake_run_flow_from_json)
    store = _FlowStore({"id": "flow-1", "data": {"nodes": [], "edges": []}})
    executor = FileWorkflowExecutor(store)

    executor.run("flow-1", include_all_nodes=True)
    assert captured["output_type"] == "debug"

    executor.run("flow-1")
    assert captured["output_type"] == "any"

    executor.run("flow-1", output_type="debug")
    assert captured["output_type"] == "any"


def test_client_forwards_include_all_nodes_and_defaults_to_false(tmp_path):
    client = FileWorkflowClient(tmp_path / "workflows", tmp_path / "components")
    recorded = []

    class _Recorder:
        def run(self, flow_id, **kwargs):
            recorded.append({"flow_id": flow_id, **kwargs})
            return {"flow_id": flow_id, "outputs": []}

    client.executor = _Recorder()

    client.run_flow("flow-1")
    client.run_flow("flow-1", include_all_nodes=True)

    assert recorded[0]["include_all_nodes"] is False
    assert recorded[1]["include_all_nodes"] is True


def test_inspect_workflow_bounded_payload_keeps_configured_paths_and_columns(tmp_path):
    data_dir = tmp_path / "project-data"
    data_dir.mkdir()
    source = data_dir / "Ti64.csv"
    source.write_text("strain,stress\n0.001,210\n", encoding="utf-8")
    flow = {
        "id": "flow-inspect",
        "name": "检查配置",
        "description": "",
        "data": {
            "nodes": [
                {
                    "id": "imp",
                    "data": {
                        "type": "ScienceIoTableImport",
                        "node": {
                            "display_name": "导入",
                            "template": {"cfg_path": {"name": "cfg_path", "value": str(source)}},
                        },
                    },
                },
                {
                    "id": "viz",
                    "data": {
                        "type": "ScienceVizMechanics",
                        "node": {
                            "display_name": "力学图",
                            "template": {
                                "x": {"name": "x", "value": "strain"},
                                "y": {"name": "y", "value": "stress"},
                            },
                        },
                    },
                },
            ],
            "edges": [{"id": "e1", "source": "imp", "target": "viz"}],
        },
    }

    payload = json.loads(_bounded_tool_content("inspect_workflow", flow_summary(flow)))
    nodes = {node["id"]: node for node in payload["nodes"]}

    assert nodes["imp"]["config"]["cfg_path"].endswith("Ti64.csv")
    assert nodes["viz"]["config"]["x"] == "strain"
    assert nodes["viz"]["config"]["y"] == "stress"


def test_truncated_model_output_requests_bounded_continuation(tmp_path):
    class Model:
        def __init__(self):
            self.calls = []

        def complete(self, messages, tools, *, max_tokens=3000):
            self.calls.append([dict(message) for message in messages])
            if len(self.calls) <= 2:
                return {
                    "content": f"部分分析{len(self.calls)}",
                    "truncated": True,
                    "finish_reason": "length",
                }
            return {"content": "最终结论：弹性模量 110 GPa。"}

    model = Model()
    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=model)
    session = agent.new_session(project_id=agent.store.create_project("truncation"))
    events = []

    result = agent.run_turn(session, "分析应力应变数据", on_progress=events.append)

    assert len(model.calls) == 3
    assert result["message"] == "最终结论：弹性模量 110 GPa。"
    truncated_events = [event for event in events if event.get("type") == "content_truncated"]
    assert len(truncated_events) == 2
    second_call = model.calls[1]
    assert any(
        message.get("role") == "system" and "截断" in str(message.get("content", ""))
        for message in second_call
    )
    assert any(
        message.get("role") == "assistant" and message.get("content") == "部分分析1"
        for message in second_call
    )


def test_truncated_model_output_continuation_is_bounded(tmp_path):
    class Model:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, *, max_tokens=3000):
            self.calls += 1
            return {
                "content": f"部分内容{self.calls}",
                "truncated": True,
                "finish_reason": "length",
            }

    model = Model()
    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=model)
    session = agent.new_session(project_id=agent.store.create_project("truncation"))

    result = agent.run_turn(session, "继续分析")

    assert model.calls == 3
    assert "多次达到长度上限" in result["message"]
    events = agent.store.events(session, limit=200)
    assert any(event["kind"] == "model_output_truncated" for event in events)


def test_system_prompt_guides_mechanics_result_table_plot_columns(tmp_path):
    flow = _mechanics_flow()
    agent, _, _ = _agent_with_fake_workflow(tmp_path, flow, {"outputs": []})

    prompt = agent._system_prompt()

    assert "strain_fraction" in prompt
    assert "stress_MPa" in prompt
    assert "cfg_x" in prompt and "cfg_y" in prompt
