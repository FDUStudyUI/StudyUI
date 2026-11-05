import io
import json
from urllib.error import HTTPError, URLError

import pytest

from materials_quality.agent import model as model_module
from materials_quality.agent.model import ChatModel
from materials_quality.agent.harness import StudyUIAgent


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_transient_network_failure_is_retried(monkeypatch):
    attempts = []

    class Opener:
        def open(self, request, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                raise URLError("temporary")
            return Reply(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    monkeypatch.setattr(model_module.time, "sleep", lambda _: None)
    assert ChatModel(base_url="https://example.com", model="test").complete([], []) == {"content": "ok"}
    assert len(attempts) == 2


def test_authentication_error_is_not_retried(monkeypatch):
    attempts = []

    class Opener:
        def open(self, request, timeout):
            attempts.append(1)
            raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    with pytest.raises(ValueError, match="HTTP 401"):
        ChatModel(base_url="https://example.com", model="test").complete([], [])
    assert len(attempts) == 1


def test_empty_model_reply_continues_current_turn_without_user_reprompt(tmp_path):
    class Model:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, *, max_tokens=3000):
            self.calls += 1
            return {"content": "" if self.calls == 1 else "继续完成当前任务。"}

    model = Model()
    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=model)
    project = agent.store.create_project("test")
    session = agent.new_session(project_id=project)
    result = agent.run_turn(session, "请分析数据")
    assert result["message"] == "继续完成当前任务。"
    assert model.calls == 2


@pytest.mark.parametrize("level", ["default", "none", "low", "high", "max"])
def test_deepseek_level_is_sent_and_old_history_is_compatible(monkeypatch, level):
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(json.loads(request.data))
            return Reply(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    model = ChatModel(base_url="https://api.deepseek.com", model="deepseek-flash", reasoning_effort=level)
    model.complete([{"role": "assistant", "content": "old"},
                    {"role": "assistant", "content": "", "reasoning_content": "prior reasoning"}],
                   [{"type": "function"}], max_tokens=16)
    payload = requests[0]
    assert payload["messages"][0]["reasoning_content"] == ""
    assert payload["messages"][1]["reasoning_content"] == "prior reasoning"
    if level == "default":
        assert "thinking" not in payload and "reasoning_effort" not in payload
    elif level == "none":
        assert payload["thinking"] == {"type": "disabled"}
        assert "reasoning_effort" not in payload
    else:
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == level
        assert payload["max_tokens"] >= 32768


def test_reasoning_is_preserved_between_agent_tool_rounds(tmp_path):
    class Model:
        def __init__(self):
            self.calls = []

        def complete(self, messages, tools, *, max_tokens=3000):
            self.calls.append([dict(item) for item in messages])
            if len(self.calls) == 1:
                return {"content": "", "reasoning_content": "private test reasoning", "tool_calls": [
                    {"id": "a", "function": {"name": "list_research_skills", "arguments": "{}"}}
                ]}
            return {"content": "done", "reasoning_content": "final test reasoning"}

    model = Model()
    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=model)
    session = agent.new_session(project_id=agent.store.create_project("test"))
    assert agent.run_turn(session, "列出技能")["message"] == "done"
    assert any(m.get("reasoning_content") == "private test reasoning" for m in model.calls[1])
    assert agent.store.messages(session)[-1]["reasoning_content"] == "final test reasoning"


def test_reasoning_model_can_batch_five_read_only_tools(tmp_path):
    class Model:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, *, max_tokens=3000):
            self.calls += 1
            if self.calls == 1:
                return {"content": "", "reasoning_content": "reasoning", "tool_calls": [
                    {"id": str(i), "function": {"name": "list_research_skills", "arguments": "{}"}}
                    for i in range(5)
                ]}
            assert len([m for m in messages if m.get("role") == "tool"]) == 5
            return {"content": "done"}

    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=Model())
    session = agent.new_session(project_id=agent.store.create_project("test"))
    assert agent.run_turn(session, "列出技能")["message"] == "done"


def test_high_effort_turn_has_a_total_tool_budget(tmp_path):
    class Model:
        def complete(self, messages, tools, *, max_tokens=3000):
            if not tools:
                return {"content": "已根据当前结果完成总结。"}
            return {"content": "", "tool_calls": [
                {"id": f"{len(messages)}-{i}", "function": {"name": "list_research_skills", "arguments": "{}"}}
                for i in range(12)
            ]}

    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=Model())
    session = agent.new_session(project_id=agent.store.create_project("test"))
    result = agent.run_turn(session, "列出科研技能")
    events = agent.store.events(session, limit=200)
    successful = [event for event in events if event["kind"] == "tool_call" and event["detail"].get("ok")]
    assert result["message"].startswith("本轮工具调用总量已达上限")
    assert len(successful) == 64


def test_turn_limits_workflow_retries(tmp_path):
    class Model:
        def complete(self, messages, tools, *, max_tokens=3000):
            if any(message.get("role") == "tool" for message in messages):
                return {"content": "根据运行结果完成总结。"}
            return {"content": "", "tool_calls": [
                {"id": str(i), "function": {"name": "run_workflow", "arguments": '{"flow_id":"known"}'}}
                for i in range(5)
            ]}

    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=Model())
    session = agent.new_session(project_id=agent.store.create_project("test"))
    dispatched = []
    agent._authorize_tool = lambda *_: {"allowed": True, "action": "workflow.run"}
    agent._dispatch = lambda *_: (dispatched.append(True) or {"status": "completed"})
    agent.run_turn(session, "运行工作流")
    assert len(dispatched) == 4


def test_long_session_keeps_original_research_goal(tmp_path):
    class Model:
        def complete(self, messages, tools, *, max_tokens=3000):
            assert any("研究原始光谱数据" in m.get("content", "") for m in messages if m["role"] == "system")
            return {"content": "done"}

    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=Model())
    session = agent.new_session(project_id=agent.store.create_project("test"))
    agent.store.append_message(session, {"role": "user", "content": "研究原始光谱数据"})
    for i in range(70):
        agent.store.append_message(session, {"role": "tool", "name": "example", "content": str(i)})
    assert agent.run_turn(session, "继续完成工作流")['message'] == 'done'


def test_other_session_workflow_needs_explicit_reference(tmp_path):
    class Workflows:
        def get_flow(self, flow_id):
            return {"id": flow_id, "name": "其他研究流程", "folder_id": project, "data": {"nodes": []}}

    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=Workflows(), model=object())
    project = agent.store.create_project("test")
    session = agent.new_session(project_id=project)
    agent.store.append_event(session, "workflow_created", {"flow_id": "own-flow"})
    agent.store.append_message(session, {"role": "user", "content": "请研究光谱数据"})
    with pytest.raises(PermissionError, match="其他会话"):
        agent._authorize_tool(session, "run_workflow", {"flow_id": "other-flow"}, "请运行工作流")
    agent.store.append_message(session, {"role": "user", "content": "请运行 other-flow 工作流"})
    assert agent._authorize_tool(session, "run_workflow", {"flow_id": "other-flow"}, "请运行 other-flow 工作流")["allowed"]


def test_workflow_first_recovery_intent_respects_negation():
    from materials_quality.agent.harness import _explicit_build_intent, _explicit_run_intent, _explicit_report_intent

    assert _explicit_build_intent("请完成工作流的调整、运行和实验报告")
    assert _explicit_run_intent("请完成工作流的调整、运行和实验报告")
    assert not _explicit_build_intent("不要完成工作流的调整、运行")
    assert not _explicit_run_intent("不要完成工作流的调整、运行")
    assert _explicit_report_intent("确保无需数据外传审批即可运行，交付实验报告；不要发送原始数据")
    assert not _explicit_report_intent("不要生成实验报告，只解释方法")


def test_natural_workflow_completion_request_authorizes_build():
    from materials_quality.agent.harness import _explicit_build_intent, _explicit_run_intent

    request = "根据原始数据自行确定分析和图表，完成并运行工作流，交付实验报告。"
    assert _explicit_build_intent(request)
    assert _explicit_run_intent(request)
    assert not _explicit_build_intent("不要完成并运行工作流，只介绍方法。")


def test_agent_prompt_uses_repository_metadata_and_stops_duplicate_runs(tmp_path):
    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=object())
    prompt = agent._system_prompt()
    assert "以 DOI/记录号向 DataCite 定点核对一次" in prompt
    assert "不能说记录没有元数据" in prompt
    assert "不得为重新生成相同附件而重跑" in prompt
