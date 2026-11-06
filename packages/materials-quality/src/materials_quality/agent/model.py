"""OpenAI-compatible chat-completions client with bounded tool calling."""

from __future__ import annotations

import json
import os
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .tasks import checkpoint

_MAX_RESPONSE_BYTES = 2_000_000
_MAX_STREAM_LINE = 256_000
_MAX_STREAM_TOOLS = 128


class _StreamUnsupported(ValueError):
    pass


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("non-finite JSON value")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Model returned invalid strict JSON") from exc
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ChatModel:
    def __init__(self, *, base_url=None, model=None, api_key=None, timeout=120, reasoning_effort="default"):
        self.base_url = base_url or os.environ.get("STUDYUI_MODEL_BASE_URL", "")
        self.model = model or os.environ.get("STUDYUI_MODEL", "")
        self.api_key = api_key if api_key is not None else os.environ.get("STUDYUI_MODEL_API_KEY", "")
        self.timeout = timeout
        if reasoning_effort not in {"default", "none", "low", "high", "max"}:
            raise ValueError("Invalid reasoning effort")
        self.reasoning_effort = reasoning_effort

    @property
    def deepseek_api(self):
        return urlsplit(self.base_url).hostname in {"api.deepseek.com", "api.deepseek.cn"}

    @property
    def supports_vision(self):
        return self.deepseek_api and self.model.casefold() in {
            "deepseek-flash",
            "deepseek-v4-flash-vision-exp",
        }

    def _endpoint(self):
        parsed = urlsplit(self.base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not self.model or not parsed.hostname:
            raise ValueError("Configure STUDYUI_MODEL_BASE_URL and STUDYUI_MODEL before chatting")
        if (
            parsed.scheme != "https"
            and not (parsed.scheme == "http" and local)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Remote model services must use HTTPS; local loopback HTTP is allowed")
        if not 0 < float(self.timeout) <= 120:
            raise ValueError("Model timeout must be in (0, 120]")
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def _execute_http(self, payload, headers, *, is_stream, on_chunk=None):
        request = Request(
            self._endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        for attempt in range(2):
            checkpoint()
            response_started = False
            try:
                with build_opener(_NoRedirect).open(request, timeout=self.timeout) as response:
                    response_started = True
                    checkpoint()
                    content_type = getattr(response, "headers", {}).get("Content-Type", "")
                    if is_stream and ("text/event-stream" in content_type.lower() or not content_type):
                        return _read_stream(response, on_chunk)
                    raw = response.read(_MAX_RESPONSE_BYTES + 1)
                    checkpoint()
                    if len(raw) > _MAX_RESPONSE_BYTES:
                        raise ValueError("Model response exceeded 2 MB")
                    body = strict_json(raw.decode("utf-8"))
                    return body["choices"][0]["message"]
            except HTTPError as exc:
                try:
                    checkpoint()
                    if is_stream and not response_started and _stream_unsupported(exc):
                        raise _StreamUnsupported("Model service does not support streaming") from None
                finally:
                    if exc.fp is not None:
                        exc.close()
                if attempt == 0 and not response_started and (exc.code == 429 or 500 <= exc.code < 600):
                    time.sleep(0.4)
                    continue
                raise ValueError(f"Model service returned HTTP {exc.code}") from None
            except (URLError, OSError, HTTPException) as exc:
                checkpoint()
                if attempt == 0 and not response_started:
                    time.sleep(0.4)
                    continue
                raise ValueError(f"Model request failed: {type(exc).__name__}") from exc
            except (UnicodeError, KeyError, IndexError, TypeError) as exc:
                raise ValueError(f"Model request failed: {type(exc).__name__}") from exc
        raise ValueError("Model service request failed after retries")

    def complete(self, messages, tools, *, max_tokens=3000, on_chunk=None):
        # DeepSeek requires each previous assistant reasoning field when tools
        # are present. Older StudyUI sessions did not persist it; an empty field
        # represents unavailable historical reasoning, never invented text.
        if self.deepseek_api or self.reasoning_effort in {"low", "high", "max"}:
            messages = [
                {**m, "reasoning_content": m.get("reasoning_content") or ""}
                if m.get("role") == "assistant" else m for m in messages
            ]
        else:
            messages = [{k: v for k, v in m.items() if k != "reasoning_content"} for m in messages]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if self.reasoning_effort != "default":
            payload["thinking"] = {"type": "disabled" if self.reasoning_effort == "none" else "enabled"}
            if self.reasoning_effort != "none":
                payload["reasoning_effort"] = self.reasoning_effort
        if self.deepseek_api and self.reasoning_effort != "none":
            payload["max_tokens"] = max(max_tokens, 65536 if self.reasoning_effort == "max" else 32768)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key

        if on_chunk:
            payload["stream"] = True
            try:
                message = self._execute_http(payload, headers, is_stream=True, on_chunk=on_chunk)
            except _StreamUnsupported:
                payload.pop("stream")
                headers["Accept"] = "application/json"
                message = self._execute_http(payload, headers, is_stream=False)
        else:
            headers["Accept"] = "application/json"
            message = self._execute_http(payload, headers, is_stream=False, on_chunk=None)

        if not isinstance(message, dict):
            raise ValueError("Model response did not contain a message")
        return message


def _stream_unsupported(error):
    if error.code not in {400, 422, 501} or error.fp is None:
        return False
    try:
        raw = error.read(8193)
        if len(raw) > 8192:
            return False
        body = strict_json(raw.decode("utf-8"))
    except (ValueError, OSError, HTTPException):
        return False
    checkpoint()
    detail = body.get("error") if isinstance(body, dict) else None
    if not isinstance(detail, dict):
        return False
    code = detail.get("code")
    return code in ("stream_not_supported", "unsupported_streaming") or (
        code in ("unsupported_parameter", "unsupported_value") and detail.get("param") == "stream"
    )


class _StreamText:
    def __init__(self, on_chunk):
        self.on_chunk = on_chunk
        self.parts = {"content": [], "reasoning": []}
        self.thinking = False
        self.pending = ""

    def append(self, kind, text):
        if text:
            self.parts[kind].append(text)
            self.on_chunk(kind, text)
            checkpoint()

    def content(self, fragment):
        text = self.pending + fragment
        self.pending = ""
        while text:
            tag = "</think>" if self.thinking else "<think>"
            kind = "reasoning" if self.thinking else "content"
            before, found, after = text.partition(tag)
            if found:
                self.append(kind, before)
                self.thinking = not self.thinking
                text = after
                continue
            for size in range(min(len(tag) - 1, len(text)), 0, -1):
                if text.endswith(tag[:size]):
                    self.pending = text[-size:]
                    text = text[:-size]
                    break
            self.append(kind, text)
            break

    def message(self):
        if self.thinking:
            raise ValueError("Model stream ended inside a thinking block")
        self.append("content", self.pending)
        message = {"role": "assistant", "content": "".join(self.parts["content"]) or None}
        if self.parts["reasoning"]:
            message["reasoning_content"] = "".join(self.parts["reasoning"])
        return message


def _accumulate_tools(tools, fragments):
    if not isinstance(fragments, list):
        raise ValueError("Invalid model stream tool calls")
    for fragment in fragments:
        if not isinstance(fragment, dict):
            raise ValueError("Invalid model stream tool call")
        index = fragment.get("index")
        if type(index) is not int or not 0 <= index < _MAX_STREAM_TOOLS:
            raise ValueError("Invalid model stream tool call index")
        if fragment.get("type") not in (None, "function"):
            raise ValueError("Invalid model stream tool call type")
        function = fragment.get("function", {})
        if not isinstance(function, dict):
            raise ValueError("Invalid model stream tool function")
        fields = tools.setdefault(index, {"id": [], "name": [], "arguments": []})
        for name, data in (("id", fragment), ("name", function), ("arguments", function)):
            value = data.get(name)
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError("Invalid model stream tool call field")
                fields[name].append(value)


def _complete_tools(tools):
    if sorted(tools) != list(range(len(tools))):
        raise ValueError("Model stream tool call indexes are incomplete")
    calls = []
    ids = set()
    for index in range(len(tools)):
        fields = {name: "".join(parts) for name, parts in tools[index].items()}
        call_id = fields["id"]
        if not call_id.strip() or call_id in ids or not fields["name"].strip():
            raise ValueError("Model stream tool call is missing a unique ID or function name")
        arguments = fields["arguments"]
        if not isinstance(strict_json(arguments), dict):
            raise ValueError("Model stream tool arguments must be a JSON object")
        calls.append({
            "id": call_id,
            "type": "function",
            "function": {"name": fields["name"], "arguments": arguments},
        })
        ids.add(call_id)
    return calls


def _read_stream(response, on_chunk):
    text = _StreamText(on_chunk)
    tools = {}
    total_bytes = 0
    finish_reason = None
    done = False
    while True:
        checkpoint()
        line = response.readline(_MAX_STREAM_LINE + 1)
        checkpoint()
        if not line:
            break
        if len(line) > _MAX_STREAM_LINE:
            raise ValueError("Model stream line exceeded 256 KB")
        total_bytes += len(line)
        if total_bytes > _MAX_RESPONSE_BYTES:
            raise ValueError("Model response exceeded 2 MB")
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            done = True
            break
        chunk = strict_json(data.decode("utf-8"))
        if not isinstance(chunk, dict) or "error" in chunk:
            raise ValueError("Model stream returned an invalid event")
        choices = chunk.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise ValueError("Invalid model stream choices")
        if not choices:  # Usage-only chunk.
            continue
        choice = choices[0]
        delta = choice.get("delta", {}) if isinstance(choice, dict) else None
        if not isinstance(delta, dict) or finish_reason is not None:
            raise ValueError("Invalid model stream delta")
        finish_reason = choice.get("finish_reason")
        if finish_reason not in (None, "stop", "tool_calls"):
            raise ValueError("Model stream returned an unsuccessful finish reason")
        for field in ("reasoning_content", "content"):
            value = delta.get(field)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError("Invalid model stream text")
            if field == "reasoning_content":
                text.append("reasoning", value)
            else:
                text.content(value)
        if delta.get("tool_calls") is not None:
            _accumulate_tools(tools, delta["tool_calls"])

    if not done and finish_reason is None:
        raise ValueError("Model stream ended without a finish marker")
    if finish_reason == "tool_calls" and not tools:
        raise ValueError("Model stream ended without the indicated tool calls")
    message = text.message()
    if tools:
        message["tool_calls"] = _complete_tools(tools)
    return message
