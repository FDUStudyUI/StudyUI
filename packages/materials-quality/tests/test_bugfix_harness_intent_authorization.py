"""Regression tests: negative Chinese/English phrasings must not authorize tool actions."""

import pytest

from materials_quality.agent.harness import (
    StudyUIAgent,
    _explicit_build_intent,
    _explicit_cancel_approval,
    _explicit_delete_intent,
    _explicit_report_intent,
    _explicit_research_task_intent,
    _explicit_run_intent,
    _explicit_skill_run,
    _explicit_workflow_proposal_intent,
)


@pytest.mark.parametrize(
    "message",
    [
        "不用运行工作流，先解释方法。",
        "不必运行工作流，只需说明思路。",
        "没必要运行工作流。",
        "我不打算运行工作流。",
        "勿运行工作流。",
        "不用执行工作流。",
        "不用实际运行工作流。",
    ],
)
def test_declined_run_request_does_not_authorize_execution(message):
    assert not _explicit_run_intent(message)


@pytest.mark.parametrize(
    "message",
    [
        "不用修改工作流，只说明方案。",
        "不必调整工作流，先解释原理。",
        "没必要修复工作流。",
    ],
)
def test_declined_build_request_does_not_authorize_canvas_changes(message):
    assert not _explicit_build_intent(message)


def test_declined_research_request_does_not_authorize_analysis_task():
    assert not _explicit_research_task_intent("不用分析这批光谱数据，先说明方法。")


def test_declined_run_phrase_requires_approval_instead_of_automatic_execution(tmp_path):
    flow = {"id": "flow-local", "folder_id": None, "data": {"nodes": [], "edges": []}}

    class Workflows:
        def get_flow(self, _flow_id):
            return flow

    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=Workflows(), model=object())
    project_id = agent.store.create_project("declined run")
    session_id = agent.new_session(project_id=project_id)
    flow["folder_id"] = project_id
    message = "不用运行工作流，先解释方法。"
    agent.store.append_message(session_id, {"role": "user", "content": message})
    agent._turn_state.value = {"skill_preflight_complete": True, "canvas_run": None}

    decision = agent._authorize_tool(session_id, "run_workflow", {"flow_id": "flow-local"}, message)

    assert decision["allowed"] is False
    assert decision["requires_approval"] is True


@pytest.mark.parametrize(
    "message",
    [
        "不要删除工作流。",
        "不必删除工作流。",
        "不用移除工作流。",
    ],
)
def test_declined_delete_request_does_not_authorize_deletion(message):
    assert not _explicit_delete_intent(message)


@pytest.mark.parametrize(
    "message",
    [
        "不要运行技能脚本。",
        "不用运行技能脚本。",
    ],
)
def test_declined_skill_run_request_does_not_authorize_script(message):
    assert not _explicit_skill_run(message)


@pytest.mark.parametrize(
    "message",
    [
        "不要取消这个审批。",
        "不用取消审批。",
    ],
)
def test_declined_cancel_request_does_not_authorize_cancellation(message):
    assert not _explicit_cancel_approval(message)


@pytest.mark.parametrize(
    "message",
    [
        "不用写报告。",
        "不打算生成报告。",
        "没必要输出报告。",
    ],
)
def test_declined_report_request_does_not_authorize_report(message):
    assert not _explicit_report_intent(message)


@pytest.mark.parametrize(
    "message",
    [
        "不必提交工作流提案。",
        "不用提交提案。",
    ],
)
def test_declined_proposal_request_does_not_authorize_proposal(message):
    assert not _explicit_workflow_proposal_intent(message)


def test_agent_cannot_cancel_approval_after_user_declines_cancellation(tmp_path):
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=object(), model=object())
    project_id = agent.store.create_project("approval cancel")
    session_id = agent.new_session(project_id=project_id)
    queued = agent.request_approval(
        session_id,
        "workflow.delete",
        "delete flow",
        {"tool": "delete_workflow", "args": {"flow_id": "flow-a", "reason": "cleanup"}},
    )

    with pytest.raises(PermissionError):
        agent._authorize_tool(
            session_id,
            "cancel_approval",
            {"approval_id": queued["approval_id"]},
            "不要取消这个审批，先保留。",
        )

    assert agent.store.get_approval(queued["approval_id"])["status"] == "pending"
