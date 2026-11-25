import threading
import time
from types import SimpleNamespace

from materials_quality.agent import dsh_sdk_engine


def test_wait_for_decision_returns_approved():
    dsh_sdk_engine.register_waiter("approval-ok")
    result = {}

    def waiter():
        result["outcome"] = dsh_sdk_engine.wait_for_decision("approval-ok", timeout=5)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.1)
    dsh_sdk_engine.signal_decision("approval-ok", "approved")
    thread.join(5)
    assert result.get("outcome") == "approved"


def test_wait_for_decision_returns_rejected_immediately():
    dsh_sdk_engine.register_waiter("approval-reject")
    started = time.monotonic()
    result = {}

    def waiter():
        result["outcome"] = dsh_sdk_engine.wait_for_decision("approval-reject", timeout=30)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.1)
    dsh_sdk_engine.signal_decision("approval-reject", "rejected")
    thread.join(5)
    assert result.get("outcome") == "rejected"
    assert time.monotonic() - started < 3


def test_wait_for_decision_times_out():
    started = time.monotonic()
    assert dsh_sdk_engine.wait_for_decision("approval-missing", timeout=0.2) is None
    assert time.monotonic() - started < 3


def test_project_event_maps_assistant_message_and_usage():
    event = {
        "type": "assistant/message",
        "data": {
            "turn": 1,
            "step": 1,
            "message": {"content": [{"type": "text", "text": "hello"}, {"type": "tool_use"}]},
            "usage": {"inputTokens": 10, "outputTokens": 2},
        },
    }
    projected, usage = dsh_sdk_engine._project_event(event, {}, set())
    assert projected == [{"type": "content_chunk", "delta": "hello"}]
    assert usage == {"inputTokens": 10, "outputTokens": 2}


def test_project_event_maps_tool_call_and_result():
    calls: dict[str, str] = {}
    projected, _ = dsh_sdk_engine._project_event(
        {"type": "tool/call", "data": {"callId": "c1", "name": "bash", "arguments": "{}"}}, calls, set()
    )
    assert projected[0]["type"] == "tool_start"
    assert projected[0]["id"] == "c1"
    assert projected[0]["name"] == "bash"
    projected, _ = dsh_sdk_engine._project_event(
        {
            "type": "tool/result",
            "data": {"message": {"toolCallId": "c1", "isError": False}},
        },
        calls,
        set(),
    )
    assert projected[0] == {
        "type": "tool_end",
        "step": {"id": "c1", "name": "bash", "status": "completed", "summary": ""},
    }


def test_project_event_stream_chunk():
    projected, _ = dsh_sdk_engine._project_event(
        {"type": "agent/assistant-stream", "data": {"chunk": {"text": "tok"}, "turn": 1, "step": 1}},
        {},
        set(),
    )
    assert projected == [{"type": "content_chunk", "delta": "tok"}]


def test_summarize_run_builds_usage_and_steps():
    result = SimpleNamespace(
        events=[
            {"type": "assistant/message", "data": {"usage": {"inputTokens": 10, "outputTokens": 3}}},
            {"type": "tool/call", "data": {"callId": "c1", "name": "read", "arguments": "{}"}},
            {"type": "tool/result", "data": {"message": {"toolCallId": "c1", "isError": True}}},
        ]
    )
    usage, steps = dsh_sdk_engine._summarize_run(result)
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 3
    assert steps == [
        {"id": "c1", "name": "read", "arguments": "{}", "status": "failed"},
    ]


def test_sdk_available_reports_boolean():
    assert isinstance(dsh_sdk_engine.sdk_available(), bool)
