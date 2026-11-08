"""Regression tests: finish_reason truncation must not kill long agent runs.

User evidence: desktop task 4eaa3448 failed at round 13 with
"ValueError: Model stream returned an unsuccessful finish reason" after six
minutes of work, and repo tasks failed with a stale "Model response exceeded
2 MB" message while the real limit is 16 MB.

Behavior contract covered here:
- finish_reason "length" is a truncation, never a task failure: complete tool
  calls and partial content are returned with a clear {"truncated": True}
  marker plus the provider's finish_reason. Nothing is fabricated as "stop".
- "content_filter" (and similar provider refusals) is permanent: no retry.
- "insufficient_system_resource" is retried only when no output was emitted;
  after partial output the partial reply is returned instead of duplicating it.
- "stop"/"tool_calls" responses are unchanged (no truncation marker).
- Byte-limit errors report the actual configured limit instead of the stale
  constant "2 MB".
"""

import io
import json

import pytest

from materials_quality.agent import model as model_module
from materials_quality.agent.model import ChatModel


def frame(delta, finish=None):
    return ("data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]}) + "\n\n").encode()


DONE = b"data: [DONE]\n\n"


def connect(monkeypatch, *replies):
    requests = []
    remaining = iter(replies)

    class Opener:
        def open(self, request, timeout):
            requests.append(json.loads(request.data))
            reply = next(remaining)
            if isinstance(reply, Exception):
                raise reply
            return io.BytesIO(reply)

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    return ChatModel(base_url="https://example.com", model="test"), requests


def no_retry_backoff(monkeypatch):
    monkeypatch.setattr(ChatModel, "_wait_before_retry", staticmethod(lambda *args: None))


def complete_stream(model):
    return model.complete([], [], on_chunk=lambda *_: None)


def test_length_with_complete_tool_calls_returns_calls_and_truncation_marker(monkeypatch):
    stream = b"".join(
        [
            frame(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "function": {"name": "inspect_research_file", "arguments": '{"path":'},
                        }
                    ]
                }
            ),
            frame({"tool_calls": [{"index": 0, "function": {"arguments": '"/data/tensile.csv"}'}}]}),
            frame({}, "length"),
            DONE,
        ]
    )
    model, requests = connect(monkeypatch, stream)

    result = complete_stream(model)

    assert result["truncated"] is True
    assert result["finish_reason"] == "length"
    assert result["tool_calls"][0]["function"]["name"] == "inspect_research_file"
    assert json.loads(result["tool_calls"][0]["function"]["arguments"]) == {"path": "/data/tensile.csv"}
    assert len(requests) == 1


def test_length_with_content_only_returns_partial_message(monkeypatch):
    stream = frame({"content": "第一段"}) + frame({"content": "，第二段"}, "length") + DONE
    model, requests = connect(monkeypatch, stream)

    result = complete_stream(model)

    assert result["content"] == "第一段，第二段"
    assert result["truncated"] is True
    assert result["finish_reason"] == "length"
    assert "tool_calls" not in result
    assert len(requests) == 1


def test_length_with_cut_tool_call_json_keeps_partial_content(monkeypatch):
    stream = b"".join(
        [
            frame({"content": "正在分析数据"}),
            frame(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_cut",
                            "function": {"name": "inspect_research_file", "arguments": '{"path":'},
                        }
                    ]
                }
            ),
            frame({}, "length"),
            DONE,
        ]
    )
    model, requests = connect(monkeypatch, stream)

    result = complete_stream(model)

    assert result["content"] == "正在分析数据"
    assert result["truncated"] is True
    assert result["truncated_tool_calls"] is True
    assert "tool_calls" not in result
    assert len(requests) == 1


def test_length_marker_without_done_chunk_returns_partial_message(monkeypatch):
    model, requests = connect(monkeypatch, frame({"content": "半截回答"}, "length"))

    result = complete_stream(model)

    assert result["content"] == "半截回答"
    assert result["truncated"] is True
    assert len(requests) == 1


def test_content_filter_is_permanent_and_not_retried(monkeypatch):
    model, requests = connect(monkeypatch, frame({"content": "partial"}, "content_filter") + DONE)

    with pytest.raises(ValueError) as excinfo:
        complete_stream(model)

    message = str(excinfo.value)
    assert "content_filter" in message
    assert "will not help" in message
    assert len(requests) == 1


def test_insufficient_system_resource_is_retried_without_duplicate_output(monkeypatch):
    no_retry_backoff(monkeypatch)
    model, requests = connect(
        monkeypatch,
        frame({}, "insufficient_system_resource") + DONE,
        frame({"content": "ok"}) + frame({}, "stop") + DONE,
    )
    seen = []

    result = model.complete([], [], on_chunk=lambda kind, text: seen.append((kind, text)))

    assert result["content"] == "ok"
    assert len(requests) == 2
    assert ("reset", {"attempt": 2, "max_attempts": 6}) in seen
    assert [item for item in seen if item[0] == "content"] == [("content", "ok")]


def test_retryable_reason_exhaustion_reports_actionable_failure(monkeypatch):
    no_retry_backoff(monkeypatch)
    reply = frame({}, "insufficient_system_resource") + DONE
    model, requests = connect(monkeypatch, reply, reply, reply, reply, reply, reply)

    with pytest.raises(ValueError) as excinfo:
        complete_stream(model)

    message = str(excinfo.value)
    assert message.startswith("Model request failed:")
    assert "insufficient_system_resource" in message
    assert "6 attempts" in message
    assert len(requests) == 6


def test_retryable_reason_after_partial_output_continues_without_retry(monkeypatch):
    model, requests = connect(
        monkeypatch, frame({"content": "partial"}, "insufficient_system_resource") + DONE
    )

    result = complete_stream(model)

    assert result["content"] == "partial"
    assert result["truncated"] is True
    assert result["finish_reason"] == "insufficient_system_resource"
    assert len(requests) == 1


def test_stop_finish_reason_is_unchanged(monkeypatch):
    model, requests = connect(monkeypatch, frame({"content": "done"}) + frame({}, "stop") + DONE)

    result = complete_stream(model)

    assert result["content"] == "done"
    assert "truncated" not in result
    assert "finish_reason" not in result
    assert len(requests) == 1


def test_tool_calls_finish_reason_is_unchanged(monkeypatch):
    stream = b"".join(
        [
            frame(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "function": {"name": "list_research_skills", "arguments": "{}"},
                        }
                    ]
                }
            ),
            frame({}, "tool_calls"),
            DONE,
        ]
    )
    model, requests = connect(monkeypatch, stream)

    result = complete_stream(model)

    assert result["tool_calls"][0]["function"]["name"] == "list_research_skills"
    assert "truncated" not in result
    assert "finish_reason" not in result
    assert len(requests) == 1


def test_stream_response_limit_message_reports_actual_limit(monkeypatch):
    monkeypatch.setattr(model_module, "_MAX_RESPONSE_BYTES", 3_000_000)
    heartbeat = b":" + b"x" * 200_000 + b"\n"
    model, requests = connect(monkeypatch, heartbeat * 16)

    with pytest.raises(ValueError) as excinfo:
        complete_stream(model)

    message = str(excinfo.value)
    assert "3 MB (3,000,000 bytes)" in message
    assert "2 MB" not in message
    assert len(requests) == 1


def test_stream_line_limit_message_reports_actual_limit(monkeypatch):
    oversized_line = b"data: " + b"x" * model_module._MAX_STREAM_LINE + b"\n"
    model, requests = connect(monkeypatch, oversized_line)

    with pytest.raises(ValueError) as excinfo:
        complete_stream(model)

    message = str(excinfo.value)
    assert "256 KB (256,000 bytes)" in message
    assert len(requests) == 1


def test_non_stream_oversized_response_reports_true_16_mb_limit(monkeypatch):
    payload = b"x" * (model_module._MAX_RESPONSE_BYTES + 1)

    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(payload)

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())

    with pytest.raises(ValueError) as excinfo:
        ChatModel(base_url="https://example.com", model="test").complete([], [])

    message = str(excinfo.value)
    assert "16 MB (16,000,000 bytes)" in message
    assert "2 MB" not in message


def test_non_stream_length_returns_partial_message(monkeypatch):
    payload = {
        "choices": [
            {"message": {"content": "部分答案"}, "finish_reason": "length"},
        ]
    }
    model, requests = connect(monkeypatch, json.dumps(payload, ensure_ascii=False).encode())

    result = model.complete([], [])

    assert result["content"] == "部分答案"
    assert result["truncated"] is True
    assert result["finish_reason"] == "length"
    assert len(requests) == 1


def test_non_stream_content_filter_is_permanent_and_not_retried(monkeypatch):
    payload = {"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]}
    model, requests = connect(monkeypatch, json.dumps(payload).encode())

    with pytest.raises(ValueError, match="content_filter"):
        model.complete([], [])

    assert len(requests) == 1


def test_non_stream_insufficient_system_resource_is_retried(monkeypatch):
    no_retry_backoff(monkeypatch)
    retryable = {"choices": [{"message": {"content": ""}, "finish_reason": "insufficient_system_resource"}]}
    success = {"choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}]}
    model, requests = connect(monkeypatch, json.dumps(retryable).encode(), json.dumps(success).encode())

    result = model.complete([], [])

    assert result["content"] == "READY"
    assert len(requests) == 2
