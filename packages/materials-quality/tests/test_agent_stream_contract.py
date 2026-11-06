import io
import json
from urllib.error import HTTPError

import pytest

from materials_quality.agent import model as model_module
from materials_quality.agent.model import ChatModel
from materials_quality.agent.tasks import TaskCancelled


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
            if isinstance(reply, bytes):
                reply = io.BytesIO(reply)
            return reply

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    return ChatModel(base_url="https://example.com", model="test"), requests


@pytest.mark.parametrize("suffix", [b"", b"data: {bad}\n", b'data: {"choices":[],"choices":[]}\n'])
def test_partial_stream_fails_without_replaying(monkeypatch, suffix):
    model, requests = connect(monkeypatch, frame({"content": "partial"}) + suffix)
    seen = []
    with pytest.raises(ValueError):
        model.complete([], [], on_chunk=lambda *chunk: seen.append(chunk))
    assert seen == [("content", "partial")]
    assert len(requests) == 1


@pytest.mark.parametrize("tool", [
    {"index": -1},
    {"index": 100_000},
    {"index": True},
    {"index": 0, "id": "call", "function": {"name": "run", "arguments": "{"}},
    {"index": 0, "id": "call", "function": {"name": "run", "arguments": "[]"}},
])
def test_malformed_tool_fragments_fail(monkeypatch, tool):
    model, requests = connect(monkeypatch, frame({"tool_calls": [tool]}) + DONE)
    with pytest.raises(ValueError):
        model.complete([], [], on_chunk=lambda *_: None)
    assert len(requests) == 1


def test_split_think_tags_and_tools(monkeypatch):
    stream = b"".join(frame({"content": s}) for s in ("<thi", "nk>private</thi", "nk>public"))
    stream += frame({"tool_calls": [{
        "index": 0, "id": "call", "function": {"name": "run", "arguments": '{"x":'},
    }]})
    stream += frame({"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]})
    model, requests = connect(monkeypatch, stream + frame({}, "tool_calls"))
    seen = []
    result = model.complete([], [], on_chunk=lambda *chunk: seen.append(chunk))
    assert seen == [("reasoning", "private"), ("content", "public")]
    assert result["content"] == "public"
    assert result["reasoning_content"] == "private"
    assert result["tool_calls"][0]["function"]["arguments"] == '{"x":1}'
    assert len(requests) == 1


def test_stream_callback_cancellation_propagates(monkeypatch):
    model, requests = connect(monkeypatch, frame({"content": "partial"}) + DONE)

    def cancel(*_):
        raise TaskCancelled()

    with pytest.raises(TaskCancelled):
        model.complete([], [], on_chunk=cancel)
    assert len(requests) == 1


def test_line_read_is_bounded(monkeypatch):
    class BoundedReply(io.BytesIO):
        def readline(self, size=-1):
            assert 0 < size < 2_000_000
            return super().readline(size)

    model, requests = connect(monkeypatch, BoundedReply(b"x" * 1_000_000))
    with pytest.raises(ValueError, match="line"):
        model.complete([], [], on_chunk=lambda *_: None)
    assert len(requests) == 1


def test_disconnect_after_output_does_not_retry(monkeypatch):
    class BrokenReply(io.BytesIO):
        def readline(self, size=-1):
            if self.tell():
                raise OSError("broken")
            return super().readline(size)

    model, requests = connect(monkeypatch, BrokenReply(frame({"content": "partial"})))
    with pytest.raises(ValueError, match="request failed"):
        model.complete([], [], on_chunk=lambda *_: None)
    assert len(requests) == 1


def test_explicit_unsupported_stream_falls_back(monkeypatch):
    error = HTTPError("https://example.com", 400, "bad request", {}, io.BytesIO(
        b'{"error":{"code":"stream_not_supported"}}'
    ))
    model, requests = connect(monkeypatch, error, b'{"choices":[{"message":{"content":"ok"}}]}')
    assert model.complete([], [], on_chunk=lambda *_: None)["content"] == "ok"
    assert [request.get("stream") for request in requests] == [True, None]


def test_stream_total_includes_heartbeat_lines(monkeypatch):
    heartbeat = b":" + b"x" * 249_998 + b"\n"
    model, requests = connect(monkeypatch, heartbeat * 9 + DONE)
    with pytest.raises(ValueError, match="2 MB"):
        model.complete([], [], on_chunk=lambda *_: None)
    assert len(requests) == 1


def test_stream_checkpoints_after_blocked_read(monkeypatch):
    cancelled = False

    class Reply(io.BytesIO):
        def readline(self, size=-1):
            nonlocal cancelled
            cancelled = True
            return super().readline(size)

    def checkpoint():
        if cancelled:
            raise TaskCancelled()

    monkeypatch.setattr(model_module, "checkpoint", checkpoint)
    model, requests = connect(monkeypatch, Reply(frame({"content": "partial"}) + DONE))
    seen = []
    with pytest.raises(TaskCancelled):
        model.complete([], [], on_chunk=lambda *chunk: seen.append(chunk))
    assert seen == []
    assert len(requests) == 1


def test_ambiguous_client_error_does_not_fall_back(monkeypatch):
    error = HTTPError("https://example.com", 400, "bad request", {}, io.BytesIO(
        b'{"error":{"code":"invalid_request_error","message":"bad request"}}'
    ))
    model, requests = connect(monkeypatch, error)
    with pytest.raises(ValueError, match="HTTP 400"):
        model.complete([], [], on_chunk=lambda *_: None)
    assert len(requests) == 1
