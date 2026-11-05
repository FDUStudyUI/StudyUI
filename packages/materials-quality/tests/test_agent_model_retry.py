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
