"""Boundary regressions: model HTTP retry classification and constructor type limits.

Round-2 boundary campaign on the OpenAI-compatible client. These cases crashed
or silently accepted wrong types on the pre-fix tree; no network is used.
"""

import io
import json
from urllib.error import HTTPError

import pytest

from materials_quality.agent import model as model_module
from materials_quality.agent.model import ChatModel


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def connect(monkeypatch, *replies):
    requests = []
    remaining = iter(replies)

    class Opener:
        def open(self, request, timeout):
            requests.append(json.loads(request.data))
            reply = next(remaining)
            if isinstance(reply, Exception):
                raise reply
            return reply

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    return requests


def http_error(code, body=b"{}", headers=None):
    return HTTPError("https://example.com/chat/completions", code, "probe", headers or {}, io.BytesIO(body))


def ok_body():
    return Reply(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())


def test_http_501_is_permanent_and_not_retried(monkeypatch):
    requests = connect(monkeypatch, http_error(501), ok_body())

    with pytest.raises(ValueError, match="HTTP 501"):
        ChatModel(base_url="https://example.com", model="test").complete([], [])

    assert len(requests) == 1


def test_http_501_stream_unsupported_still_falls_back(monkeypatch):
    error = http_error(501, b'{"error": {"code": "stream_not_supported"}}')
    requests = connect(monkeypatch, error, ok_body())
    seen = []

    result = ChatModel(base_url="https://example.com", model="test").complete(
        [], [], on_chunk=lambda kind, text: seen.append(kind)
    )

    assert result["content"] == "ok"
    assert [request.get("stream") for request in requests] == [True, None]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout": None},
        {"timeout": ""},
        {"timeout": float("inf")},
        {"timeout": float("nan")},
        {"max_output_tokens": float("inf")},
        {"max_output_tokens": float("nan")},
        {"reasoning_effort": []},
        {"reasoning_effort": {}},
        {"api_key": 123},
        {"base_url": 123},
        {"model": 123},
    ],
)
def test_constructor_rejects_wrong_types_with_valueerror(kwargs):
    options = {"base_url": "https://example.com", "model": "test"}
    options.update(kwargs)
    with pytest.raises(ValueError):
        ChatModel(**options)


@pytest.mark.parametrize(
    "message",
    [
        {"content": 123},
        {"content": ["x"]},
        {"content": "x", "tool_calls": {"id": "call-1"}},
        {"content": "x", "tool_calls": ["not-a-dict"]},
    ],
)
def test_non_stream_wrong_typed_message_fields_are_rejected(monkeypatch, message):
    body = json.dumps({"choices": [{"message": message, "finish_reason": "stop"}]}).encode()
    connect(monkeypatch, Reply(body))

    with pytest.raises(ValueError, match="Model response"):
        ChatModel(base_url="https://example.com", model="test").complete([], [])
