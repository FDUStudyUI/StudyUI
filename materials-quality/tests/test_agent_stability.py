"""Regression tests for cancellation, bounded inference and truthful outcomes."""

import io
import json
import threading
import time

import pytest

from materials_quality.agent import model as model_module
from materials_quality.agent.harness import StudyUIAgent
from materials_quality.agent.model import ChatModel
from materials_quality.agent.tasks import TaskManager


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_invalid_stream_tool_arguments_can_be_repaired_without_replaying_tools(tmp_path):
    class Model:
        calls = 0

        def complete(self, messages, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise model_module.ModelToolArgumentsError("Invalid tool JSON")
            assert any("不要重复创建" in m.get("content", "") for m in messages)
            return {"content": "已恢复，等待补充数据。"}

    model = Model()
    agent = StudyUIAgent(tmp_path / "state.db", canvas=object(), model=model)
    session = agent.new_session(project_id=agent.store.create_project("test"))
    assert agent.run_turn(session, "你好")["task_status"] == "completed"
    assert model.calls == 2


def wait_task(manager, task_id, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        task = manager.get(task_id)
        if task["terminal"]:
            return task
        time.sleep(0.01)
    return manager.get(task_id)


def test_cancel_model_wait_releases_session_without_waiting_for_provider(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    effects = []

    class Opener:
        def open(self, request, timeout):
            entered.set()
            release.wait(3)
            return Reply(json.dumps({"choices": [{"message": {"content": "late"}}]}).encode())

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    manager = TaskManager(tmp_path / "tasks.db")
    model = ChatModel(base_url="https://example.com", model="test")

    def work(progress):
        model.complete([], [], on_chunk=lambda *args: effects.append(args))
        effects.append("next tool")

    task = manager.submit("s", "first", work)
    try:
        assert entered.wait(1)
        manager.cancel(task["id"])
        assert wait_task(manager, task["id"], 0.8)["status"] == "cancelled"
        next_task = manager.submit("s", "second", lambda progress: {"message": "ok"})
        assert wait_task(manager, next_task["id"])["status"] == "completed"
    finally:
        release.set()
    time.sleep(0.05)
    assert effects == []


def test_model_has_total_budget_even_when_provider_never_returns(monkeypatch):
    release = threading.Event()

    class Opener:
        def open(self, request, timeout):
            release.wait(2)
            return Reply(b'{"choices":[{"message":{"content":"late"}}]}')

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    monkeypatch.setattr(model_module, "MODEL_CALL_BUDGET_SECONDS", 0.1, raising=False)
    try:
        with pytest.raises(TimeoutError):
            ChatModel(base_url="https://example.com", model="test").complete([], [])
    finally:
        release.set()


def test_model_failure_does_not_invent_retry_count(tmp_path):
    class Model:
        def complete(self, *args, **kwargs):
            raise ValueError("Model service returned HTTP 401 after 1 attempts")

    agent = StudyUIAgent(tmp_path / "state.db", canvas=object(), model=Model())
    session = agent.new_session(project_id=agent.store.create_project("test"))
    result = agent.run_turn(session, "你好")
    assert "重试 5 次" not in result["message"]
    assert result["task_status"] == "failed"


def test_repeated_identical_tool_failure_stops_without_another_model_summary(tmp_path):
    class Model:
        calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            return {
                "tool_calls": [
                    {
                        "id": str(self.calls),
                        "function": {"name": "inspect_workflow", "arguments": '{"flow_id":"missing"}'},
                    }
                ]
            }

    model = Model()
    agent = StudyUIAgent(tmp_path / "state.db", canvas=object(), model=model)
    session = agent.new_session(project_id=agent.store.create_project("test"))
    result = agent.run_turn(session, "查看工作流")
    assert model.calls <= 3
    assert result["task_status"] == "failed"
    assert "重复" in result["message"]


def test_failed_build_is_not_marked_complete_by_a_fluent_answer(tmp_path):
    class Model:
        calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "tool_calls": [{"id": "bad", "function": {"name": "build_workflow", "arguments": "{}"}}]
                }
            return {"content": "已经完成全部工作流。"}

    agent = StudyUIAgent(tmp_path / "state.db", canvas=object(), model=Model())
    session = agent.new_session(project_id=agent.store.create_project("test"))
    result = agent.run_turn(session, "创建一个拉伸分析工作流")
    assert result["task_status"] == "failed"
    assert result["verification"]["unresolved_tools"] == ["build_workflow"]


def test_waiting_for_workflow_slot_is_cancellable(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import lfx.load

    from materials_quality.agent import workflow_executor as executor

    calls = []
    monkeypatch.setattr(lfx.load, "run_flow_from_json", lambda *a, **kw: calls.append(1))
    runner = executor.FileWorkflowExecutor(SimpleNamespace(read=lambda _: ({"data": {}}, "v1")))
    manager = TaskManager(tmp_path / "tasks.db")
    executor._WORKFLOW_RUN_GATE.acquire()
    try:
        task = manager.submit("s", "r", lambda progress: runner.run("f"))
        time.sleep(0.1)
        manager.cancel(task["id"])
        assert wait_task(manager, task["id"], 0.8)["status"] == "cancelled"
    finally:
        executor._WORKFLOW_RUN_GATE.release()
    time.sleep(0.1)
    assert calls == []


def test_turn_budget_stops_before_next_model_call(tmp_path, monkeypatch):
    from materials_quality.agent import tasks

    class Model:
        calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            time.sleep(0.05)
            return {
                "tool_calls": [{"id": "a", "function": {"name": "list_research_skills", "arguments": "{}"}}]
            }

    monkeypatch.setattr(tasks, "TURN_BUDGET_SECONDS", 0.01)
    model = Model()
    agent = StudyUIAgent(tmp_path / "state.db", canvas=object(), model=model)
    session = agent.new_session(project_id=agent.store.create_project("test"))
    result = agent.run_turn(session, "列出技能")
    assert result["task_status"] == "failed"
    assert "预算" in result["message"]
    assert model.calls <= 1


def test_real_stream_cancellation_shuts_down_transport_and_discards_late_tokens(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    entered, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            entered.set()
            release.wait(3)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    manager = TaskManager(tmp_path / "tasks.db")
    model = ChatModel(base_url=f"http://127.0.0.1:{server.server_port}", model="test")
    callbacks = []
    try:
        task = manager.submit(
            "s", "r", lambda progress: model.complete([], [], on_chunk=lambda *args: callbacks.append(args))
        )
        assert entered.wait(2)
        manager.cancel(task["id"])
        assert wait_task(manager, task["id"], 0.8)["status"] == "cancelled"
        assert callbacks == []
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_stream_callbacks_stay_on_caller_thread(monkeypatch):
    caller = threading.get_ident()

    class Opener:
        def open(self, request, timeout):
            return Reply(
                b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            )

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    threads = []
    ChatModel(base_url="https://example.com", model="test").complete(
        [], [], on_chunk=lambda *args: threads.append(threading.get_ident())
    )
    assert threads and all(value == caller for value in threads)


def test_missing_build_plan_does_not_create_an_empty_successful_flow(tmp_path):
    agent = StudyUIAgent(tmp_path / "state.db", canvas=object(), model=object())
    session = agent.new_session(project_id=agent.store.create_project("test"))
    with pytest.raises(ValueError, match="protocol|actions"):
        agent._dispatch(
            session, "build_workflow", {"name": "analysis", "rationale": "test"}, "创建一个分析工作流"
        )


def test_corrected_build_arguments_clear_unaddressed_failure(tmp_path, monkeypatch):
    class Model:
        calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls > 2:
                return {"content": "工作流已创建。"}
            args = {} if self.calls == 1 else {"name": "analysis"}
            return {
                "tool_calls": [
                    {
                        "id": str(self.calls),
                        "function": {"name": "build_workflow", "arguments": json.dumps(args)},
                    }
                ]
            }

    agent = StudyUIAgent(tmp_path / "state.db", canvas=object(), model=Model())
    session = agent.new_session(project_id=agent.store.create_project("test"))
    monkeypatch.setattr(agent, "_authorize_tool", lambda *args: {"allowed": True})

    def dispatch(session, name, args, text):
        if not args:
            raise ValueError("Missing build arguments")
        return {"status": "created", "flow_id": "fixed"}

    monkeypatch.setattr(agent, "_dispatch", dispatch)
    result = agent.run_turn(session, "创建分析工作流")
    assert result["task_status"] == "completed"
    assert result["verification"]["unresolved_tools"] == []


def test_loop_stop_records_unexecuted_tool_calls_for_next_turn(tmp_path, monkeypatch):
    class Model:
        def complete(self, *args, **kwargs):
            return {
                "tool_calls": [
                    {
                        "id": str(i),
                        "function": {"name": "inspect_workflow", "arguments": '{"flow_id":"missing"}'},
                    }
                    for i in range(4)
                ]
            }

    agent = StudyUIAgent(tmp_path / "state.db", canvas=object(), model=Model())
    session = agent.new_session(project_id=agent.store.create_project("test"))
    monkeypatch.setattr(agent, "_authorize_tool", lambda *args: {"allowed": True})
    calls = []

    def dispatch(*args):
        calls.append(1)
        raise ValueError("Missing flow")

    monkeypatch.setattr(agent, "_dispatch", dispatch)
    assert agent.run_turn(session, "查看工作流")["task_status"] == "failed"
    assert len(calls) == 3
    messages = agent.store.messages(session)
    replies = [m for m in messages if m["role"] == "tool"]
    assert {m["tool_call_id"] for m in replies} == {"0", "1", "2", "3"}
    assert json.loads(replies[-1]["content"])["status"] == "not_run"
