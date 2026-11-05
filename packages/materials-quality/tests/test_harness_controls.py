import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from lfx.schema import DataFrame

from materials_quality.agent.permissions import PermissionStore
from materials_quality.agent.skill_registry import SkillRegistry
from materials_quality.agent.skill_sandbox import SkillSandbox
from materials_quality.agent.store import SessionStore
from materials_quality.agent.workflow import apply_actions, sanitize_installed_components


def _skill_zip(description="safe study skill", script="print('ok')"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "SKILL.md",
            f"---\nname: demo-skill\ndescription: {description}\nmetadata:\n  version: 1.0.0\n---\nUse the supplied research context.\n",
        )
        archive.writestr("analyze.py", script)
    return output.getvalue()


def test_project_permission_presets_and_script_gate(tmp_path):
    store = PermissionStore(tmp_path / "settings.json")
    project = "p-1"
    assert store.get_preset(project) == "project_collaboration"
    assert store.authorize(project_id=project, action="workflow.list")["allowed"]
    assert store.authorize(project_id=project, action="workflow.run", task_authorized=True)["allowed"]
    assert not store.authorize(project_id=None, action="workflow.run", task_authorized=True)["allowed"]
    assert store.authorize(project_id=project, action="workflow.run")["requires_approval"]
    store.set_preset(project, "per_action")
    assert store.authorize(project_id=project, action="workflow.run", task_authorized=True)[
        "requires_approval"
    ]
    store.set_preset(project, "skill_sandbox")
    assert store.authorize(
        project_id=project,
        action="skill.script",
        task_authorized=True,
        trusted_skill=True,
        script_execution=True,
    )["allowed"]
    assert not store.authorize(
        project_id=project,
        action="skill.script",
        task_authorized=True,
        trusted_skill=False,
        script_execution=True,
    )["allowed"]


def test_report_artifact_requires_intent_and_obeys_project_permission(tmp_path):
    from materials_quality.agent.harness import StudyUIAgent

    agent = StudyUIAgent(tmp_path / "report.sqlite3", model=object())
    project = agent.store.create_project("reports")
    session = agent.new_session(project_id=project)
    args = {"title": "Experiment", "content": "# Experiment\n\nMeasured result and limitations."}
    assert agent._authorize_tool(session, "write_research_report", args, "请生成实验报告")["allowed"]
    result = agent._dispatch(session, "write_research_report", args, "请生成实验报告")
    artifact = result["artifact"]
    assert artifact["sha256"] == hashlib.sha256(args["content"].encode()).hexdigest()
    assert agent.store.get_artifact(artifact["id"], session)["project_id"] == project
    with pytest.raises(PermissionError):
        agent._dispatch(session, "write_research_report", args, "不要生成报告")
    agent.permissions.set_preset(project, "per_action")
    assert agent._authorize_tool(session, "write_research_report", args, "请生成实验报告")["requires_approval"]


@pytest.mark.parametrize(
    "message",
    [
        "请建立并运行一个真实原始数据工作流。",
        "请帮我建立工作流，完成数据导入和分析。",
        "搭建并运行 XRD 工作流。",
        "请直接在项目内修复并运行现有工作流 41367d0a，用户已授权对公开原始数据工作流进行建流、修改、运行和迭代。",
        "请在当前项目中为公开原始数据新建并运行一个工作流。",
        "我授权你在当前项目工作流 BiFeO3 XRD 内追加一个特征表导出节点。",
        "Build a workflow from the raw measurements and run it.",
    ],
)
def test_explicit_build_intent_accepts_natural_language_variants(message):
    from materials_quality.agent.harness import _explicit_build_intent

    assert _explicit_build_intent(message)


@pytest.mark.parametrize(
    "message",
    [
        "先不要搭建工作流，只列出所需节点。",
        "不需要创建工作流，请先解释方法。",
        "Do not build a workflow yet; just discuss the design.",
        "暂不新建并运行拉伸工作流，只讨论方案。",
        "不要在 BiFeO3 XRD 工作流中添加导出节点，只解释方案。",
    ],
)
def test_negated_build_request_does_not_authorize_canvas_changes(message):
    from materials_quality.agent.harness import _explicit_build_intent

    assert not _explicit_build_intent(message)


@pytest.mark.parametrize(
    "message",
    [
        "请搭建并运行一个真实原始数据工作流。",
        "创建并运行工作流，处理当前数据。",
        "请直接修复并运行现有工作流。",
        "请修正现有 JSON 工作流并实际运行。",
        "Please build a workflow and run it.",
    ],
)
def test_explicit_build_and_run_authorizes_both_actions(message):
    from materials_quality.agent.harness import _explicit_build_intent, _explicit_run_intent

    assert _explicit_build_intent(message)
    assert _explicit_run_intent(message)


def test_explicit_intent_allows_scientific_context_between_action_and_workflow():
    from materials_quality.agent.harness import _explicit_build_intent, _explicit_run_intent

    message = "请修复并运行现有 BiFeO3 原始 XRD 工作流 41367d0a。"
    assert _explicit_build_intent(message)
    assert _explicit_run_intent(message)


@pytest.mark.parametrize(
    "message",
    [
        "先不要搭建并运行工作流，只解释方法。",
        "暂不运行工作流，请先检查参数。",
        "暂不修复并运行现有工作流，只做只读排查。",
        "请不要修复或运行当前 BiFeO3 原始 XRD 工作流。",
        "Do not run the workflow yet.",
    ],
)
def test_negated_run_request_does_not_authorize_execution(message):
    from materials_quality.agent.harness import _explicit_run_intent

    assert not _explicit_run_intent(message)


def test_graph_tool_schema_documents_only_valid_action_keys():
    from materials_quality.agent.harness import TOOLS

    build = next(tool["function"] for tool in TOOLS if tool["function"]["name"] == "build_workflow")
    action = build["parameters"]["properties"]["actions"]["items"]
    assert action["required"] == ["op"]
    assert set(action["properties"]) == {
        "op",
        "node_id",
        "component_type",
        "config",
        "source",
        "output",
        "target",
        "input",
        "x",
        "y",
    }


def test_scientific_missing_tokens_are_configurable_and_not_redacted_as_credentials():
    from materials_quality.agent.harness import _redact_for_audit
    from materials_quality.agent.workflow import _is_secret, _safe_value, apply_actions

    values = ["NA", "maj.73", "paź.78"]
    assert not _is_secret("cfg_missing_tokens", {})
    assert _safe_value("cfg_missing_tokens", {}, values) == values
    assert _safe_value("raw_y", {}, "counts") == "counts"
    assert _safe_value("raw_data", {}, "private measurement payload") != "private measurement payload"
    assert _is_secret("cfg_api_token", {})
    flow = {
        "data": {
            "nodes": [
                {"id": "missing", "data": {"node": {"template": {"cfg_missing_tokens": {"value": []}}}}}
            ],
            "edges": [],
        }
    }
    configured, _ = apply_actions(
        flow,
        [{"op": "set_node_config", "node_id": "missing", "config": {"cfg_missing_tokens": values}}],
        {},
    )
    assert configured["data"]["nodes"][0]["data"]["node"]["template"]["cfg_missing_tokens"]["value"] == values
    assert _redact_for_audit({"cfg_missing_tokens": values, "api_token": "secret-value"}) == {
        "cfg_missing_tokens": values,
        "api_token": "[已隐藏]",
    }


def test_skill_import_hash_update_history_and_review_reset(tmp_path):
    registry = SkillRegistry(tmp_path / "skills")
    first = registry.import_zip("demo.zip", _skill_zip())
    expected = hashlib.sha256(b"print('ok')").hexdigest()
    assert first["resources"]["analyze.py"] == expected
    assert "upload.zip" not in first["resources"]
    registry.trust(first["name"], first["sha256"])
    second = registry.update_zip(
        "demo.zip", _skill_zip(script="print('updated')"), first["name"], first["sha256"]
    )
    assert second["sha256"] != first["sha256"]
    assert not second["trusted"] and not second["enabled"]
    assert first["sha256"] in second["version_history"]
    assert (tmp_path / "skills" / ".versions" / first["name"] / first["sha256"] / "SKILL.md").is_file()
    with pytest.raises(ValueError, match="变化"):
        registry.update_zip("demo.zip", _skill_zip(), first["name"], first["sha256"])


def test_skill_sandbox_fails_closed_without_docker(tmp_path, monkeypatch):
    registry = SkillRegistry(tmp_path / "skills")
    imported = registry.import_zip("demo.zip", _skill_zip())
    registry.trust(imported["name"], imported["sha256"])
    sandbox = SkillSandbox(registry)
    monkeypatch.setattr("materials_quality.agent.skill_sandbox.shutil.which", lambda _name: None)
    with pytest.raises(RuntimeError, match="Docker"):
        sandbox.run(imported["name"], "analyze.py", {"x": 1})


def test_agent_graph_connections_have_canvas_handles_and_auto_layout():
    catalog = {
        "materials_sources": {
            "RawSource": {
                "display_name": "Raw source",
                "template": {},
                "outputs": [{"name": "table", "types": ["DataFrame"]}],
            }
        },
        "materials_skills": {
            "StudyUIAIAnalysis": {
                "display_name": "AI 分析",
                "template": {
                    "input_table": {"type": "other", "input_types": ["DataFrame"]},
                    "analysis_request": {"type": "str"},
                },
                "outputs": [],
            }
        },
    }
    flow = {"id": "test", "data": {"nodes": [], "edges": []}}
    actions = [
        {"op": "add_node", "component_type": "RawSource", "node_id": "raw"},
        {"op": "add_node", "component_type": "StudyUIAIAnalysis", "node_id": "analysis"},
        {"op": "connect", "source": "raw", "output": "table", "target": "analysis", "input": "input_table"},
    ]
    result, _ = apply_actions(flow, actions, catalog)
    assert result["data"]["nodes"][0]["position"] != result["data"]["nodes"][1]["position"]
    edge = result["data"]["edges"][0]
    assert edge["source"] == "raw" and edge["target"] == "analysis"
    assert json.loads(edge["sourceHandle"])["name"] == "table"
    assert json.loads(edge["targetHandle"])["fieldName"] == "input_table"
    assert edge["data"]["sourceHandle"]["name"] == "table"


def test_workflow_rebinding_restores_active_science_form_fields():
    from materials_quality.science.catalog import component_class

    component = component_class("preprocess.reshape")()
    installed = component.to_frontend_node()["data"]["node"]
    saved = component.to_frontend_node()
    saved["id"] = "reshape"
    saved["data"]["id"] = "reshape"
    saved["data"]["type"] = "SciencePreprocessReshape"
    template = saved["data"]["node"]["template"]
    # Emulate a saved graph whose template was created with method=types and
    # later switched to wide_to_long without refreshing conditional visibility.
    template["cfg_method"]["value"] = "wide_to_long"
    template["cfg_id_vars"]["value"] = ["sample_id"]
    template["cfg_value_vars"]["value"] = ["0", "30"]
    assert template["cfg_id_vars"]["show"] is False

    flow = {"id": "legacy", "data": {"nodes": [saved], "edges": []}}
    catalog = {"materials_preprocessing": {"SciencePreprocessReshape": installed}}
    rebound = sanitize_installed_components(flow, catalog)
    restored = rebound["data"]["nodes"][0]["data"]["node"]["template"]
    assert restored["cfg_id_vars"]["value"] == ["sample_id"]
    assert restored["cfg_value_vars"]["value"] == ["0", "30"]
    assert restored["cfg_id_vars"]["show"] is True
    assert restored["cfg_value_vars"]["show"] is True


def test_ai_analysis_subagent_requires_approval_and_reports_chunk_coverage(monkeypatch, tmp_path):
    from components.materials_skills.ai_analysis import StudyUIAIAnalysis
    from materials_quality.agent.execution_context import external_data_approval, reset_external_data_approval

    class FakeModel:
        def __init__(self):
            self.calls = []

        def complete(self, messages, tools, *, max_tokens=3000):
            payload = json.loads(messages[-1]["content"])
            self.calls.append(payload)
            empty = {
                "conclusions": ["描述性观察"],
                "evidence": [{"claim": "原始记录", "row_references": [1]}],
                "limitations": [],
                "unresolved": [],
            }
            return {"content": json.dumps(empty, ensure_ascii=False)}

    fake = FakeModel()
    monkeypatch.setattr(StudyUIAIAnalysis, "_model", lambda self: fake)
    node = StudyUIAIAnalysis().set(
        input_table=DataFrame({"value": list(range(160))}), analysis_request="总结数据分布，不推断因果。"
    )
    with pytest.raises(PermissionError, match="StudyUI"):
        node.build_analysis()
    token = external_data_approval(True)
    try:
        result = node.build_analysis().data
        summary = node.build_summary().text
    finally:
        reset_external_data_approval(token)
    assert result["coverage"]["total_rows"] == 160
    assert result["coverage"]["analyzed_rows"] == 160
    assert result["coverage"]["chunk_count"] == 2
    assert len(result["coverage"]["input_sha256"]) == 64
    assert len(fake.calls) == 3
    assert "160/160" in summary


def test_approval_records_are_one_shot_and_publish_only_summary(tmp_path):
    store = SessionStore(tmp_path / "agent.sqlite3")
    project = store.create_project("approval project")
    session = store.create_session("approval test", project_id=project)
    store.create_approval(
        "approval-a",
        session,
        project,
        "workflow.delete",
        "删除测试工作流",
        {
            "tool": "delete_workflow",
            "args": {"flow_id": "flow-a"},
            "summary": {"title": "删除工作流：flow-a", "impact": "移入恢复目录"},
        },
    )
    rows = store.pending_approvals(session)
    assert rows[0]["summary"]["impact"] == "移入恢复目录"
    assert store.decide_approval("approval-a", "approved")
    assert not store.decide_approval("approval-a", "approved")
    assert store.pending_approvals(session) == []
    assert [
        event["detail"]["decision"] for event in store.events(session) if event["kind"] == "approval_decided"
    ] == ["approved"]


def test_model_profiles_keep_credentials_out_of_json_and_public_api(tmp_path, monkeypatch):
    from materials_quality.agent.model_profiles import ModelProfiles

    class FakeKeyring:
        values = {}

        @classmethod
        def set_password(cls, service, ref, value):
            cls.values[(service, ref)] = value

        @classmethod
        def get_password(cls, service, ref):
            return cls.values.get((service, ref))

        @classmethod
        def delete_password(cls, service, ref):
            cls.values.pop((service, ref), None)

    monkeypatch.setattr(ModelProfiles, "_keyring", staticmethod(lambda: FakeKeyring))
    path = tmp_path / "settings.json"
    profiles = ModelProfiles(path)
    first = profiles.save(
        name="DeepSeek", base_url="https://api.deepseek.com", model="deepseek-flash", api_key="test-secret", reasoning_effort="max"
    )
    profiles.save(name="Local", base_url="http://127.0.0.1:1234/v1", model="local-model", create_new=True)
    assert len(profiles.list_profiles()) == 2
    profiles.activate(first["id"])
    public = json.dumps(profiles.public())
    assert "test-secret" not in public
    assert "test-secret" not in path.read_text(encoding="utf-8")
    assert profiles.public()["model"] == "deepseek-flash"
    assert profiles.public()["reasoning_effort"] == "max"
    profiles.save(name="DeepSeek", base_url="https://api.deepseek.com", model="deepseek-flash")
    assert profiles.public()["reasoning_effort"] == "max"
    with pytest.raises(ValueError, match="思考等级"):
        profiles.save(name="DeepSeek", base_url="https://api.deepseek.com", model="deepseek-flash", reasoning_effort="extreme")
    profiles.remove(profiles.list_profiles()[1]["id"])
    assert len(profiles.list_profiles()) == 1


def test_generated_artifacts_are_copied_hashed_and_session_scoped(tmp_path):
    from materials_quality.agent.harness import StudyUIAgent, _artifact_candidates

    run_dir = tmp_path / "studyui-run"
    run_dir.mkdir()
    source = run_dir / "summary.csv"
    source.write_bytes(b"strain,stress_MPa\n0.01,120\n")
    payload = {"outputs": [{"outputs": [{"name": "artifacts", "data": [{"path": str(source)}]}]}]}
    assert _artifact_candidates(payload) == [str(source)]

    agent = StudyUIAgent(tmp_path / "agent.sqlite3", model=object())
    project_id = agent.store.create_project("artifact project")
    session_id = agent.new_session(project_id=project_id)
    artifacts = agent._store_generated_artifacts(payload, session_id)
    assert len(artifacts) == 1
    item = artifacts[0]
    assert item["name"] == "summary.csv"
    assert item["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    stored = agent.store.get_artifact(item["id"], session_id)
    assert Path(stored["path"]).read_bytes() == source.read_bytes()
    assert agent.store.get_artifact(item["id"], "another-session") is None


def test_import_source_is_not_registered_as_generated_artifact(tmp_path):
    from materials_quality.agent.harness import StudyUIAgent

    directory = tmp_path / "studyui-run"
    directory.mkdir()
    raw = directory / "raw.csv"
    output = directory / "report.html"
    raw.write_text("x\n1\n", encoding="utf-8")
    output.write_text("report", encoding="utf-8")
    payload = {"outputs": [{"outputs": [{"name": "artifacts", "data": [{"path": str(raw)}, {"path": str(output)}]}]}]}
    flow = {"data": {"nodes": [{"data": {"type": "ScienceIoTableImport", "node": {"template": {"cfg_path": {"value": str(raw)}}}}}]}}
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", model=object())
    project = agent.store.create_project("test")
    session = agent.new_session(project_id=project)
    artifacts = agent._store_generated_artifacts(payload, session, flow=flow)
    assert [item["name"] for item in artifacts] == ["report.html"]


def test_lfx_debug_outputs_summarize_tables_and_collect_only_declared_artifacts(tmp_path):
    from materials_quality.agent.harness import _artifact_candidates, _compact_run_result

    source = tmp_path / "verified.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    payload = {
        "outputs": [
            {
                "inputs": {},
                "outputs": [
                    {
                        "component_id": "export",
                        "results": {
                            "table": [
                                {"path": "not-a-declared-artifact", "x": 1, "y": "measurement-secret"},
                                {"x": 2, "y": 3},
                            ],
                            "report": {
                                "data": {
                                    "input_rows": 7660,
                                    "output_rows": 7624,
                                    "input_sha256": "a" * 64,
                                    "source_files": [{"path": r"C:\private\raw.xy", "sha256": "b" * 64}],
                                }
                            },
                            "artifacts": [{"path": str(source), "sha256": "c" * 64}],
                        },
                    }
                ],
            }
        ]
    }

    assert _artifact_candidates(payload) == [str(source)]
    summary = _compact_run_result(payload)
    rendered = json.dumps(summary, ensure_ascii=False)
    assert '"rows": 2' in rendered
    assert '"input_rows": 7660' in rendered
    assert '"output_rows": 7624' in rendered
    assert "measurement-secret" not in rendered
    assert r"C:\private" not in rendered


def test_lfx_serialized_data_wrappers_preserve_aggregate_metadata_and_real_artifacts(tmp_path):
    from materials_quality.agent.harness import _artifact_candidates, _compact_run_result

    artifact = tmp_path / "processed.csv"
    artifact.write_text("x,y\n1,2\n", encoding="utf-8")
    payload = {
        "outputs": [
            {
                "outputs": [
                    {
                        "component_id": "raw-import",
                        "results": {
                            "table": {
                                "text_key": "text",
                                "data": [
                                    {"two_theta_deg": 20.0, "intensity_counts": "must-not-leak"},
                                    {"two_theta_deg": 20.1, "intensity_counts": "must-not-leak"},
                                ],
                            },
                            "features": [
                                {"peak_position": 31.2, "height": 12.0, "fwhm": 0.4}
                            ],
                            "report": {
                                "text_key": "text",
                                "data": {
                                    "schema_version": "science-result/1",
                                    "execution_status": "completed",
                                    "data": {
                                        "input_rows": 7660,
                                        "output_rows": 7624,
                                        "input_sha256": "a" * 64,
                                        "source_files": [
                                            {"path": r"C:\private\raw.xy", "sha256": "b" * 64}
                                        ],
                                    },
                                    "table_summary": {"rows": 7624, "columns": ["two_theta_deg"]},
                                },
                            },
                            "summary": {"text_key": "text", "data": {"text": "7624 行，1 列"}},
                        },
                        "outputs": {
                            "table": {"type": "array", "message": [{"message": "display-only"}]},
                            "report": {"type": "message", "message": "display-only"},
                        },
                    },
                    {
                        "component_id": "export",
                        "results": {
                            "artifacts": [
                                {"path": str(artifact), "sha256": "c" * 64},
                                {"path": "array", "sha256": "d" * 64},
                            ]
                        },
                    },
                ]
            }
        ]
    }

    assert _artifact_candidates(payload) == [str(artifact)]
    summary = _compact_run_result(payload)
    raw_node, export_node = summary["outputs"]
    rendered = json.dumps(summary, ensure_ascii=False)
    assert raw_node["outputs"]["table"] == {"rows": 2, "columns": ["two_theta_deg", "intensity_counts"]}
    assert raw_node["outputs"]["features"] == {"rows": 1, "columns": ["peak_position", "height", "fwhm"]}
    assert raw_node["outputs"]["report"]["data"]["input_sha256"] == "a" * 64
    assert raw_node["outputs"]["summary"] == {"text": "7624 行，1 列"}
    assert export_node["outputs"]["artifacts"] == {"count": 1, "files": ["processed.csv"]}
    assert "must-not-leak" not in rendered
    assert "display-only" not in rendered
    assert r"C:\private" not in rendered


def test_agent_run_blocks_cross_project_workflows(tmp_path):
    from materials_quality.agent.harness import StudyUIAgent

    flow = {
        "id": "foreign-flow",
        "folder_id": "another-project",
        "data": {"nodes": [], "edges": []},
    }

    class FakeWorkflows:
        def get_flow(self, _flow_id):
            return flow

    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=FakeWorkflows(), model=object())
    project_id = agent.store.create_project("owned project")
    session_id = agent.new_session(project_id=project_id)
    decision = agent._authorize_tool(
        session_id, "run_workflow", {"flow_id": flow["id"]}, "请运行现有工作流。"
    )

    assert not decision["allowed"]
    assert decision["requires_approval"]
    assert decision["action"] == "workflow.run"
    assert "不属于当前项目" in decision["reason"]


def test_ai_workflow_run_requests_single_use_external_data_approval(tmp_path):
    from materials_quality.agent.harness import StudyUIAgent

    flow = {
        "id": "ai-flow",
        "folder_id": "project",
        "data": {"nodes": [{"data": {"type": "StudyUIAIAnalysis"}}], "edges": []},
    }

    class FakeWorkflows:
        def get_flow(self, _flow_id):
            return flow

    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=FakeWorkflows(), model=object())
    project_id = agent.store.create_project("AI project")
    flow["folder_id"] = project_id
    session_id = agent.new_session(project_id=project_id)
    args = {"flow_id": flow["id"]}
    decision = agent._authorize_tool(session_id, "run_workflow", args, "请运行 AI 分析工作流。")

    assert not decision["allowed"]
    assert decision["requires_approval"]
    assert decision["external_data"]
    approval_id = agent._create_tool_approval(
        session_id, "run_workflow", args, "请运行 AI 分析工作流。", decision["reason"]
    )
    approval = agent.store.get_approval(approval_id)
    assert approval["request"]["external_data"] is True
    assert approval["request"]["flow_digest"] == decision["flow_digest"]


def test_changed_workflow_invalidates_approval_before_execution(tmp_path):
    from materials_quality.agent.harness import StudyUIAgent

    flow = {"id": "flow-a", "folder_id": "project", "data": {"nodes": [], "edges": []}}
    runs = []

    class FakeWorkflows:
        def get_flow(self, _flow_id):
            return flow

        def run_flow(self, flow_id, **_kwargs):
            runs.append(flow_id)
            return {"outputs": []}

    client = FakeWorkflows()
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=client, model=object())
    project_id = agent.store.create_project("approval project")
    flow["folder_id"] = project_id
    session_id = agent.new_session(project_id=project_id)
    approval_id = agent._create_tool_approval(
        session_id,
        "run_workflow",
        {"flow_id": flow["id"]},
        "请运行工作流。",
        "逐项审批",
    )
    flow["name"] = "changed after approval"

    with pytest.raises(ValueError, match="审批后工作流已变化"):
        agent.decide_approval(approval_id, "approved")
    assert runs == []
    failures = [
        event
        for event in agent.store.events(session_id)
        if event["kind"] == "approved_action_completed" and not event["detail"]["ok"]
    ]
    assert len(failures) == 1


def test_successful_tool_calls_are_written_to_the_audit_log(tmp_path):
    from materials_quality.agent.harness import StudyUIAgent

    class FakeWorkflows:
        pass

    class FakeModel:
        def __init__(self):
            self.turn = 0

        def complete(self, _messages, _tools, *, max_tokens=3000):
            self.turn += 1
            if self.turn == 1:
                return {
                    "tool_calls": [
                        {
                            "id": "call-skills",
                            "function": {"name": "list_research_skills", "arguments": "{}"},
                        }
                    ]
                }
            return {"content": "已完成只读查询。"}

    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=FakeWorkflows(), model=FakeModel())
    project_id = agent.store.create_project("audit project")
    session_id = agent.new_session(project_id=project_id)
    agent.run_turn(session_id, "列出可用科研 Skill。")
    calls = [event for event in agent.store.events(session_id) if event["kind"] == "tool_call"]

    assert len(calls) == 1
    assert calls[0]["detail"] == {"name": "list_research_skills", "ok": True, "action": "skill.list"}


def test_component_catalog_queries_are_cached_and_bounded_per_turn(tmp_path):
    from materials_quality.agent.harness import MAX_COMPONENT_SEARCHES_PER_TURN, StudyUIAgent

    class FakeWorkflows:
        catalog_calls = 0

        def component_catalog(self):
            self.catalog_calls += 1
            return {
                "materials_analysis": {
                    "ScienceMaterialsXrd": {
                        "display_name": "XRD analysis",
                        "description": "XRD curve and peak analysis",
                        "template": {"cfg_x": {"type": "str", "display_name": "X axis"}},
                        "outputs": [{"name": "features", "display_name": "Features", "types": ["Table"]}],
                    }
                }
            }

    workflows = FakeWorkflows()
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=workflows, model=object())
    project_id = agent.store.create_project("component lookup")
    session_id = agent.new_session(project_id=project_id)
    agent._turn_state.value = {
        "component_queries": 0,
        "component_cache": {},
        "last_components": [],
    }
    try:
        first = agent._dispatch(session_id, "list_components", {"query": "XRD", "limit": 5}, "")
        cached = agent._dispatch(session_id, "list_components", {"query": "xrd", "limit": 5}, "")
        assert first["components"][0]["type"] == "ScienceMaterialsXrd"
        assert cached["cached"] is True

        for query in (f"other-{index}" for index in range(MAX_COMPONENT_SEARCHES_PER_TURN - 1)):
            agent._dispatch(session_id, "list_components", {"query": query, "limit": 5}, "")
        exhausted = agent._dispatch(session_id, "list_components", {"query": "four", "limit": 5}, "")
        assert exhausted["search_budget_reached"] is True
        assert "components" not in exhausted
        assert workflows.catalog_calls == MAX_COMPONENT_SEARCHES_PER_TURN
    finally:
        del agent._turn_state.value


def test_component_search_ranks_exact_fields_and_keeps_tool_json_valid(tmp_path):
    import json

    from materials_quality.agent.harness import _bounded_tool_content
    from materials_quality.agent.workflow import component_catalog_summary

    catalog = {
        "materials_sources": {
            "ScienceIoDatabaseImport": {
                "display_name": "Database import",
                "description": "Read a database table",
                "template": {"cfg_path": {"type": "str", "display_name": "Path"}},
                "outputs": [{"name": "table", "types": ["Table"]}],
            },
            "ScienceIoTableImport": {
                "display_name": "Raw table import",
                "description": "Import raw delimited experimental files",
                "template": {
                    **{
                        f"cfg_field_{index}": {
                            "type": "str",
                            "display_name": f"Field {index}",
                            "value": "x" * 200,
                        }
                        for index in range(20)
                    },
                    "cfg_delimiter": {"type": "str", "display_name": "Delimiter"},
                    "code": {"type": "code", "display_name": "Code", "value": "secret-code"},
                },
                "outputs": [{"name": "table", "types": ["Table"]}],
            },
        }
    }
    rows = component_catalog_summary(catalog, "CSV import delimiter", limit=5)
    assert rows[0]["type"] == "ScienceIoTableImport"
    assert all(row["name"] != "code" for row in rows[0]["inputs"])

    content = _bounded_tool_content("list_components", {"components": rows})
    assert len(content) <= 8_000
    assert json.loads(content)["components"][0]["type"] == "ScienceIoTableImport"

    plots = component_catalog_summary(
        {
            "materials_visualization": {
                "ScienceVizSpectra": {
                    "display_name": "Curve plot",
                    "description": "Plot selected x-y series",
                    "template": {
                        "cfg_x": {"type": "str", "display_name": "X"},
                        "cfg_columns": {"type": "str", "list": True, "display_name": "Y series"},
                        "cfg_conditions": {"type": "table", "display_name": "Conditions", "table_schema": [{"name": "column", "type": "str"}, {"name": "op", "type": "str"}]},
                    },
                    "outputs": [{"name": "artifacts", "types": ["File"]}],
                },
                "ScienceExportReport": {
                    "display_name": "Report export",
                    "description": "Export a report",
                    "template": {"cfg_format": {"type": "str", "display_name": "Format"}},
                    "outputs": [],
                },
            }
        },
        "line chart plot",
        limit=5,
    )
    assert plots[0]["type"] == "ScienceVizSpectra"
    assert next(field for field in plots[0]["inputs"] if field["name"] == "cfg_columns")["is_list"] is True
    assert next(field for field in plots[0]["inputs"] if field["name"] == "cfg_conditions")["table_schema"][1]["name"] == "op"


def test_oversized_tool_result_is_valid_json():
    import json

    from materials_quality.agent.harness import _bounded_tool_content

    content = _bounded_tool_content("search_literature", {"detail": "x" * 20_000})
    parsed = json.loads(content)
    assert parsed["truncated"] is True
    assert parsed["tool"] == "search_literature"


def test_missing_report_preserves_per_column_counts_without_rows():
    from materials_quality.agent.harness import _message_or_report_summary

    report = {"data": {"metrics": {"columns": {"voltage": {"missing_count": 3, "missing_ratio": 0.3}},
                                    "rows": [{"row_position": 1, "value": "private"}]},
                       "provenance": {"mode": "shared", "source": {"source_name": "raw.csv", "source_sha256": "abc"}}}}
    result = _message_or_report_summary(report)
    assert result["metrics"]["columns"]["voltage"] == {"missing_count": 3, "missing_ratio": 0.3}
    assert "rows" not in result["metrics"]
    assert result["provenance"]["source"]["source_name"] == "raw.csv"
    assert "private" not in str(result)


def test_large_workflow_inspection_preserves_graph_instead_of_generic_truncation():
    import json
    from materials_quality.agent.harness import _bounded_tool_content

    summary = {
        "id": "flow", "name": "large", "node_count": 8, "edge_count": 1,
        "nodes": [{"id": f"node-{i}", "component": "ScienceIoTableImport", "config": {"long_setting": "x" * 2000}, "inputs": [], "outputs": [{"name": "table"}]} for i in range(8)],
        "edges": [{"source": "node-0", "target": "node-1", "sourceHandle": json.dumps({"id": "node-0", "name": "table"}), "targetHandle": json.dumps({"id": "node-1", "fieldName": "input_table"})}],
    }
    result = json.loads(_bounded_tool_content("inspect_workflow", summary))
    assert len(result["nodes"]) == 8
    assert result["edges"][0]["output"] == "table"
    assert result["edges"][0]["input"] == "input_table"
    assert "result_keys" not in result


def test_known_aggregate_outputs_are_visible_while_raw_measurements_remain_hidden():
    import json
    from materials_quality.agent.harness import _compact_run_result

    payload = {"outputs": [{"outputs": [
        {"component_id": "raw", "results": {"table": [{"signal": "raw-secret", "x": 1.234}]}},
        {"component_id": "stats", "results": {"table": {"data": [{"group": "A", "signal_mean": 2.5, "signal_count": 10}, {"group": "B", "signal_mean": 3.5, "signal_count": 12}]}}},
    ]}]}
    flow = {"data": {"nodes": [{"id": "raw", "data": {"type": "ScienceIoTableImport"}}, {"id": "stats", "data": {"type": "ScienceStatsGrouped"}}]}}
    result = _compact_run_result(payload, flow=flow)
    rendered = json.dumps(result)
    assert "raw-secret" not in rendered and "1.234" not in rendered
    derived = result["outputs"][1]["outputs"]["table"]
    assert derived["aggregate_preview"][0]["signal_mean"] == 2.5
    assert derived["aggregate_ranges"]["signal_count"] == {"min": 10, "max": 12}


def test_singleton_group_mean_is_not_exposed_as_aggregate():
    import json
    from materials_quality.agent.harness import _compact_run_result

    payload = {"outputs": [{"outputs": [{"component_id": "stats", "results": {"table": [
        {"group": "private-id", "value_count": 1, "value_mean": 713.42},
        {"group": "B", "value_count": 2, "value_mean": 10.0},
    ]}}]}]}
    flow = {"data": {"nodes": [{"id": "stats", "data": {"type": "ScienceStatsGrouped"}}]}}
    result = _compact_run_result(payload, flow=flow)
    assert "713.42" not in json.dumps(result)
    assert "private-id" not in json.dumps(result)
    assert result["outputs"][0]["outputs"]["table"]["aggregate_suppressed_rows"] == 1


def test_workflow_summary_and_tool_reply_omit_component_source_code():
    import json

    from materials_quality.agent.harness import _bounded_tool_content
    from materials_quality.agent.workflow import flow_summary

    flow = {
        "id": "flow-1",
        "name": "test",
        "data": {
            "nodes": [
                {
                    "id": "import",
                    "data": {
                        "type": "ScienceIoTableImport",
                        "node": {
                            "display_name": "Table import",
                            "template": {
                                "cfg_path": {"value": "D:\\data\\raw.csv"},
                                "input_data": {"value": "private table payload"},
                                "code": {"value": "x" * 20_000},
                                "config_json": {"value": '{"raw":"x"}'},
                            },
                            "outputs": [],
                        },
                    },
                }
            ],
            "edges": [],
        },
    }
    summary = flow_summary(flow)
    assert "code" not in summary["nodes"][0]["config"]
    assert "input_data" not in summary["nodes"][0]["config"]
    assert "config_json" not in summary["nodes"][0]["config"]
    assert "code" not in summary["nodes"][0]["inputs"]

    content = _bounded_tool_content("inspect_workflow", summary)
    assert len(content) < 8_000
    assert "private table payload" not in content
    assert "x" * 2_000 not in content
    assert json.loads(content)["node_count"] == 1


def test_tool_round_limit_requests_a_final_summary_without_more_tools(tmp_path, monkeypatch):
    from materials_quality.agent import harness as harness_module
    from materials_quality.agent.harness import StudyUIAgent

    class FakeWorkflows:
        pass

    class FakeModel:
        calls = 0

        def complete(self, _messages, tools, *, max_tokens=3000):
            self.calls += 1
            if tools:
                return {
                    "tool_calls": [
                        {
                            "id": "call-skills",
                            "function": {"name": "list_research_skills", "arguments": "{}"},
                        }
                    ]
                }
            return {"content": "已完成的结果已核验；当前没有未完成审批。"}

    monkeypatch.setattr(harness_module, "MAX_TOOL_ROUNDS", 1)
    agent = StudyUIAgent(
        tmp_path / "agent.sqlite3", langflow=FakeWorkflows(), model=FakeModel()
    )
    project_id = agent.store.create_project("final summary")
    session_id = agent.new_session(project_id=project_id)
    result = agent.run_turn(session_id, "列出科研 Skill。")

    assert "已核验" in result["message"]
    assert "工具调用轮数已达上限" in result["message"]
