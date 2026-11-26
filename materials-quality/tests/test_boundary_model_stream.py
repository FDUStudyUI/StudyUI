"""Boundary regressions: fragmented/SSE-grammar-safe model stream parsing.

Round-2 boundary campaign on the OpenAI-compatible streaming client. Each test
below failed on the pre-fix tree (unexpected ValueError / silently wrong result)
and now pins the corrected behavior. Fake HTTP responses only, no network.
"""

import io
import json
import random

import pytest

from materials_quality.agent import model as model_module
from materials_quality.agent.model import ChatModel


class FragmentedReply(io.BytesIO):
    """A response whose readline() returns transport fragments instead of whole lines."""

    def __init__(self, data, sizes=None):
        super().__init__(data)
        self.sizes = list(sizes) if sizes else None
        self.index = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def readline(self, size=-1):
        if self.sizes:
            limit = self.sizes[self.index % len(self.sizes)]
            self.index += 1
            if size is not None and size > 0:
                limit = min(limit, size)
            return super().readline(limit)
        return super().readline(size)


def frame(delta, finish=None):
    return ("data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]}) + "\n\n").encode()


DONE = b"data: [DONE]\n\n"

REPRESENTATIVE = b"".join(
    [
        frame({"reasoning_content": "分析"}),
        frame({"content": "结果：σ=1.2"}),
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
        frame({"tool_calls": [{"index": 0, "function": {"arguments": '"/data/a.csv"}'}}]}),
        b'data: {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2}}\n\n',
        frame({}, "tool_calls"),
        DONE,
    ]
)


def connect(monkeypatch, reply):
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(json.loads(request.data))
            return reply

    monkeypatch.setattr(model_module, "build_opener", lambda *_: Opener())
    return ChatModel(base_url="https://example.com", model="test"), requests


def test_stream_is_identical_for_every_byte_fragmentation(monkeypatch):
    model, _ = connect(monkeypatch, io.BytesIO(REPRESENTATIVE))
    expected = model.complete([], [], on_chunk=lambda *_: None)

    for sizes in ([1], [2], [3], [5], [7], list(range(1, 10)), [64, 1, 3]):
        reply = FragmentedReply(REPRESENTATIVE, sizes)
        model, requests = connect(monkeypatch, reply)
        result = model.complete([], [], on_chunk=lambda *_: None)
        assert result == expected, f"fragmentation sizes={sizes!r} changed the parsed message"
        assert len(requests) == 1


def test_stream_is_identical_for_seeded_random_fragmentation(monkeypatch):
    rng = random.Random(20261108)
    model, _ = connect(monkeypatch, io.BytesIO(REPRESENTATIVE))
    expected = model.complete([], [], on_chunk=lambda *_: None)

    for _ in range(5):
        sizes = [rng.randint(1, 17) for _ in range(400)]
        model, _ = connect(monkeypatch, FragmentedReply(REPRESENTATIVE, sizes))
        assert model.complete([], [], on_chunk=lambda *_: None) == expected


def test_stream_accepts_cr_only_and_crlf_line_endings(monkeypatch):
    lf_stream = frame({"content": "hi"}) + frame({}, "stop") + DONE
    for ending in (b"\r\n", b"\r"):
        model, _ = connect(monkeypatch, io.BytesIO(lf_stream.replace(b"\n", ending)))
        result = model.complete([], [], on_chunk=lambda *_: None)
        assert result["content"] == "hi"


def test_stream_joins_spec_compliant_multi_line_data_events(monkeypatch):
    payload = b'{"choices": [{"delta": {"content": "hello"}}], "usage": {"total_tokens": 3}}'
    cut = payload.index(b"],") + 1
    stream = b"data: " + payload[:cut] + b"\ndata: " + payload[cut:] + b"\n\n"
    stream += frame({}, "stop") + DONE
    model, requests = connect(monkeypatch, io.BytesIO(stream))

    result = model.complete([], [], on_chunk=lambda *_: None)

    assert result["content"] == "hello"
    assert len(requests) == 1


def test_stream_strips_utf8_bom_from_first_event(monkeypatch):
    stream = b"\xef\xbb\xbf" + frame({"content": "hi"}) + frame({}, "stop") + DONE
    model, _ = connect(monkeypatch, io.BytesIO(stream))

    result = model.complete([], [], on_chunk=lambda *_: None)

    assert result["content"] == "hi"


def test_stream_ignores_duplicate_terminal_finish_reason(monkeypatch):
    stream = frame({"content": "hi"}) + frame({}, "stop") + frame({}, "stop") + DONE
    model, requests = connect(monkeypatch, io.BytesIO(stream))

    result = model.complete([], [], on_chunk=lambda *_: None)

    assert result["content"] == "hi"
    assert len(requests) == 1


def test_stream_error_event_reports_provider_detail(monkeypatch):
    stream = b'data: {"error": {"code": "rate_limit", "message": "busy"}}\n\n'
    model, requests = connect(monkeypatch, io.BytesIO(stream))

    with pytest.raises(ValueError) as excinfo:
        model.complete([], [], on_chunk=lambda *_: None)

    message = str(excinfo.value)
    assert "rate_limit" in message
    assert "busy" in message
    assert len(requests) == 1
