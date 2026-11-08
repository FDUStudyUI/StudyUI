"""OpenAI-compatible chat-completions client with bounded tool calling."""

from __future__ import annotations

import json
import os
import re
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .tasks import TaskCancelled, checkpoint

_MAX_RESPONSE_BYTES = 16_000_000
_MAX_STREAM_LINE = 256_000
_MAX_STREAM_TOOLS = 128
_MODEL_REQUEST_ATTEMPTS = 6  # Initial request plus at least five retries.
_RETRY_BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0, 8.0)

# finish_reason values that mean the provider delivered the answer it was asked for.
_FINISH_REASONS_COMPLETE = frozenset({"stop", "tool_calls"})
# The provider hit its output/context limit. The reply is partial but still useful:
# a long agent run must continue from it instead of failing the whole task.
_FINISH_REASONS_TRUNCATED = frozenset({"length", "max_tokens"})
# A transient provider-side failure that can succeed when retried (DeepSeek returns
# this while its system resources are exhausted).
_FINISH_REASONS_RETRYABLE = frozenset({"insufficient_system_resource"})
# The provider refused or aborted the response; retrying the identical request cannot help.
_FINISH_REASONS_PERMANENT = frozenset({"content_filter", "safety", "sensitive", "blocked"})


def _retryable_http_status(status):
    """Retry only HTTP responses that are likely to recover without a config change."""
    if status == 501:
        # "Not Implemented" is permanent: the same request cannot start working on retry.
        return False
    return status in {408, 425, 429} or 500 <= status < 600


def _format_byte_limit(limit):
    """Describe a byte limit together with its exact value, never a stale hard-coded one."""
    if limit % 1_000_000 == 0:
        human = f"{limit // 1_000_000} MB"
    elif limit % 1_000 == 0:
        human = f"{limit // 1_000} KB"
    else:
        return f"{limit:,} bytes"
    return f"{human} ({limit:,} bytes)"


def _finish_reason_error(reason):
    """Actionable explanation for a provider finish_reason that is not a normal completion."""
    if reason in _FINISH_REASONS_RETRYABLE:
        return (
            f"Model provider reported finish reason {reason!r}; the provider was temporarily unable "
            "to complete the request. Retry the request or continue the session later."
        )
    if reason in _FINISH_REASONS_PERMANENT:
        return (
            f"Model provider stopped the response with finish reason {reason!r}; retrying the same "
            "request will not help. Rephrase the request or check the provider moderation settings."
        )
    return (
        f"Model response ended with unsupported finish reason {reason!r}; the task was stopped "
        "instead of being reported as successful. Retry the request or use a provider that returns "
        "finish_reason 'stop' or 'tool_calls'."
    )


def _apply_finish_reason(message, finish_reason):
    """Keep a max-token truncated reply; refuse replies the provider did not complete."""
    if not isinstance(message, dict):
        raise ValueError("Model response did not contain a message")
    if finish_reason is None or finish_reason in _FINISH_REASONS_COMPLETE:
        return message
    if finish_reason in _FINISH_REASONS_TRUNCATED:
        message = dict(message)
        message["truncated"] = True
        message["finish_reason"] = finish_reason
        return message
    if finish_reason in _FINISH_REASONS_RETRYABLE:
        raise _RetryableModelResponse(_finish_reason_error(finish_reason))
    raise _PermanentModelResponse(_finish_reason_error(finish_reason))


class _StreamUnsupported(ValueError):
    pass


class _InvalidStreamResponse(ValueError):
    pass


class _RetryableModelResponse(ValueError):
    """Provider-side transient failure raised before any output reached the caller."""


class _PermanentModelResponse(ValueError):
    """Provider-side stop that retrying the identical request cannot fix."""


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


DEFAULT_MAX_OUTPUT_TOKENS = 32_768
MAX_OUTPUT_TOKENS_LIMIT = 100_000_000


class ChatModel:
    def __init__(
        self,
        *,
        base_url=None,
        model=None,
        api_key=None,
        timeout=120,
        reasoning_effort="default",
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        self.base_url = base_url or os.environ.get("STUDYUI_MODEL_BASE_URL", "")
        self.model = model or os.environ.get("STUDYUI_MODEL", "")
        self.api_key = api_key if api_key is not None else os.environ.get("STUDYUI_MODEL_API_KEY", "")
        if not isinstance(self.base_url, str):
            raise ValueError("Invalid model base URL")
        if not isinstance(self.model, str):
            raise ValueError("Invalid model name")
        if not isinstance(self.api_key, str):
            raise ValueError("Invalid model API key")
        try:
            self.timeout = float(timeout)
        except (TypeError, ValueError):
            raise ValueError("Model timeout must be in (0, 120]") from None
        if not 0 < self.timeout <= 120:
            raise ValueError("Model timeout must be in (0, 120]")
        if not isinstance(reasoning_effort, str) or reasoning_effort not in {
            "default",
            "none",
            "low",
            "high",
            "max",
        }:
            raise ValueError("Invalid reasoning effort")
        self.reasoning_effort = reasoning_effort
        try:
            self.max_output_tokens = int(max_output_tokens)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Invalid max output tokens") from None
        if not 256 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS_LIMIT:
            raise ValueError("Invalid max output tokens")

    @property
    def deepseek_api(self):
        return (
            urlsplit(self.base_url).hostname in {"api.deepseek.com", "api.deepseek.cn"}
            or "deepseek" in (self.model or "").casefold()
        )

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
        endpoint = self._endpoint()
        endpoint_parts = urlsplit(endpoint)
        request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        current_url = endpoint
        redirect_target = None
        for attempt in range(_MODEL_REQUEST_ATTEMPTS):
            checkpoint()
            request = Request(current_url, data=request_data, headers=headers)
            try:
                with build_opener(_NoRedirect).open(request, timeout=self.timeout) as response:
                    checkpoint()
                    content_type = getattr(response, "headers", {}).get("Content-Type", "")
                    if is_stream and ("text/event-stream" in content_type.lower() or not content_type):
                        emitted_output = False

                        def emit(kind, text):
                            nonlocal emitted_output
                            emitted_output = emitted_output or bool(text)
                            on_chunk(kind, text)

                        try:
                            return _read_stream(response, emit)
                        except TaskCancelled:
                            raise
                        except (_RetryableModelResponse, _PermanentModelResponse):
                            raise
                        except (UnicodeError, ValueError, KeyError, IndexError, TypeError) as exc:
                            raise _InvalidStreamResponse(str(exc)) from exc
                        except (URLError, OSError, HTTPException) as exc:
                            if emitted_output:
                                raise _InvalidStreamResponse(
                                    "Model request failed: stream interrupted after partial output"
                                ) from exc
                            raise
                    raw = response.read(_MAX_RESPONSE_BYTES + 1)
                    checkpoint()
                    if len(raw) > _MAX_RESPONSE_BYTES:
                        # Retrying an oversized response cannot shrink it.
                        raise _PermanentModelResponse(
                            f"Model response exceeded the {_format_byte_limit(_MAX_RESPONSE_BYTES)} limit"
                        )
                    body = strict_json(raw.decode("utf-8"))
                    choice = body["choices"][0]
                    if not isinstance(choice, dict):
                        raise ValueError("Model response did not contain a message")
                    message = _apply_finish_reason(choice.get("message"), choice.get("finish_reason"))
                    if isinstance(body.get("usage"), dict):
                        message = dict(message)
                        message["usage"] = body["usage"]
                    return message
            except HTTPError as exc:
                follow_redirect = False
                try:
                    checkpoint()
                    if is_stream and _stream_unsupported(exc):
                        raise _StreamUnsupported("Model service does not support streaming") from None
                    location = exc.headers.get("Location") if exc.headers else None
                    if 300 <= exc.code < 400 and location:
                        candidate_url = urljoin(current_url, location)
                        candidate = urlsplit(candidate_url)
                        same_origin = (
                            candidate.scheme.casefold() == endpoint_parts.scheme.casefold()
                            and candidate.hostname
                            and candidate.hostname.casefold() == (endpoint_parts.hostname or "").casefold()
                            and candidate.port == endpoint_parts.port
                        )
                        if same_origin:
                            current_url = candidate_url
                            follow_redirect = True
                        elif candidate.hostname:
                            redirect_target = f"{candidate.hostname}{candidate.path[:160]}"
                finally:
                    if exc.fp is not None:
                        exc.close()
                if follow_redirect and attempt + 1 < _MODEL_REQUEST_ATTEMPTS:
                    continue
                if _retryable_http_status(exc.code) and attempt + 1 < _MODEL_REQUEST_ATTEMPTS:
                    self._prepare_retry(on_chunk, attempt)
                    self._wait_before_retry(attempt, getattr(exc, "headers", None))
                    continue
                detail = f" (cross-origin redirect refused: {redirect_target})" if redirect_target else ""
                raise ValueError(
                    f"Model service returned HTTP {exc.code} after {attempt + 1} attempts{detail}"
                ) from None
            except _RetryableModelResponse as exc:
                checkpoint()
                if attempt + 1 < _MODEL_REQUEST_ATTEMPTS:
                    self._prepare_retry(on_chunk, attempt)
                    self._wait_before_retry(attempt)
                    continue
                raise ValueError(
                    f"Model request failed: {exc} after {_MODEL_REQUEST_ATTEMPTS} attempts"
                ) from exc
            except _PermanentModelResponse as exc:
                raise ValueError(str(exc)) from exc
            except _InvalidStreamResponse as exc:
                raise ValueError(str(exc)) from exc
            except (URLError, OSError, HTTPException) as exc:
                checkpoint()
                if attempt + 1 < _MODEL_REQUEST_ATTEMPTS:
                    self._prepare_retry(on_chunk, attempt)
                    self._wait_before_retry(attempt)
                    continue
                raise ValueError(
                    f"Model request failed: {type(exc).__name__} after {_MODEL_REQUEST_ATTEMPTS} attempts"
                ) from exc
            except (UnicodeError, KeyError, IndexError, TypeError) as exc:
                if attempt + 1 < _MODEL_REQUEST_ATTEMPTS:
                    self._prepare_retry(on_chunk, attempt)
                    self._wait_before_retry(attempt)
                    continue
                raise ValueError(
                    f"Model request failed: {type(exc).__name__} after {_MODEL_REQUEST_ATTEMPTS} attempts"
                ) from exc
            except ValueError as exc:
                # A malformed or interrupted provider response can be transient.
                # Local configuration errors are raised before entering this loop.
                if attempt + 1 < _MODEL_REQUEST_ATTEMPTS:
                    self._prepare_retry(on_chunk, attempt)
                    self._wait_before_retry(attempt)
                    continue
                raise ValueError(
                    f"Model request failed: invalid response after {_MODEL_REQUEST_ATTEMPTS} attempts"
                ) from exc

    @staticmethod
    def _prepare_retry(on_chunk, attempt):
        if on_chunk:
            on_chunk("reset", {"attempt": attempt + 2, "max_attempts": _MODEL_REQUEST_ATTEMPTS})

    @staticmethod
    def _wait_before_retry(attempt, response_headers=None):
        delay = _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
        retry_after = response_headers.get("Retry-After") if response_headers else None
        if retry_after:
            try:
                delay = min(30.0, max(delay, float(retry_after.strip())))
            except (AttributeError, TypeError, ValueError):
                pass
        deadline = time.monotonic() + delay
        while True:
            checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    def complete(self, messages, tools, *, max_tokens=None, on_chunk=None):
        # DeepSeek requires each previous assistant reasoning field when tools
        # are present. Older StudyUI sessions did not persist it; an empty field
        # represents unavailable historical reasoning, never invented text.
        if self.deepseek_api or self.reasoning_effort in {"low", "high", "max"}:
            messages = [
                {**m, "reasoning_content": m.get("reasoning_content") or ""}
                if m.get("role") == "assistant"
                else m
                for m in messages
            ]
        else:
            messages = [{k: v for k, v in m.items() if k != "reasoning_content"} for m in messages]
        if max_tokens is None:
            max_tokens = self.max_output_tokens
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
        if self.deepseek_api and self.reasoning_effort in {"low", "high", "max"}:
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
                message = self._execute_http(payload, headers, is_stream=False, on_chunk=on_chunk)
        else:
            headers["Accept"] = "application/json"
            message = self._execute_http(payload, headers, is_stream=False, on_chunk=None)

        if not isinstance(message, dict):
            raise ValueError("Model response did not contain a message")
        message = normalize_reasoning_fields(message)
        _validate_chat_message(message)
        return message


def _validate_chat_message(message):
    """Reject provider messages whose field types would corrupt the agent conversation."""
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("Model response content is not text")
    tool_calls = message.get("tool_calls")
    if tool_calls is not None and (
        not isinstance(tool_calls, list) or not all(isinstance(call, dict) for call in tool_calls)
    ):
        raise ValueError("Model response tool calls are invalid")


def normalize_reasoning_fields(message):
    """Keep provider-specific analysis channels out of user-visible content."""
    normalized = dict(message)
    fragments = []
    for field in ("reasoning_content", "reasoning", "analysis"):
        value = normalized.pop(field, None)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"Invalid model {field} text")
        if value and value not in fragments:
            fragments.append(value)
    content = normalized.get("content")
    if isinstance(content, str):
        embedded = []

        def remove_thinking(match):
            thought = match.group(2).strip()
            if thought and thought not in embedded:
                embedded.append(thought)
            return ""

        normalized["content"] = re.sub(
            r"<(think|analysis)>([\s\S]*?)</\1>", remove_thinking, content, flags=re.IGNORECASE
        )
        for thought in embedded:
            if thought not in fragments:
                fragments.append(thought)
    if fragments:
        normalized["reasoning_content"] = "\n\n".join(fragments)
        normalized["content"] = _remove_reasoning_from_content(normalized.get("content"), fragments)
    return normalized


def _remove_reasoning_from_content(content, fragments):
    if not isinstance(content, str) or not content:
        return content
    visible = content
    for private in sorted((item.strip() for item in fragments if item.strip()), key=len, reverse=True):
        start = visible.find(private)
        if start < 0:
            continue
        end = start + len(private)
        before, after = visible[:start], visible[end:]
        if before.strip() and after.strip() and not (before[-1].isspace() and after[0].isspace()):
            continue
        visible = before.rstrip() + ("\n\n" if before.strip() and after.strip() else "") + after.lstrip()
    return visible.strip()


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
        self.thinking_tag = None
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
            if self.thinking:
                tag = f"</{self.thinking_tag}>"
                before, found, after = text.partition(tag)
                if found:
                    self.append("reasoning", before)
                    self.thinking = False
                    self.thinking_tag = None
                    text = after
                    continue
                for size in range(min(len(tag) - 1, len(text)), 0, -1):
                    if text.endswith(tag[:size]):
                        self.pending = text[-size:]
                        text = text[:-size]
                        break
                self.append("reasoning", text)
                break

            open_tags = (("<think>", "think"), ("<analysis>", "analysis"))
            matches = [(text.find(tag), tag, name) for tag, name in open_tags if text.find(tag) >= 0]
            if matches:
                start, tag, name = min(matches, key=lambda item: item[0])
                self.append("content", text[:start])
                self.thinking = True
                self.thinking_tag = name
                text = text[start + len(tag) :]
                continue
            max_size = min(max(len(tag) for tag, _ in open_tags) - 1, len(text))
            for size in range(max_size, 0, -1):
                suffix = text[-size:]
                if any(tag.startswith(suffix) for tag, _ in open_tags):
                    self.pending = suffix
                    text = text[:-size]
                    break
            self.append("content", text)
            break

    def message(self):
        if self.thinking:
            raise ValueError("Model stream ended inside a thinking block")
        self.append("content", self.pending)
        message = {"role": "assistant", "content": "".join(self.parts["content"]) or None}
        if self.parts["reasoning"]:
            message["reasoning_content"] = "".join(self.parts["reasoning"])
        return normalize_reasoning_fields(message)


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
        calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": fields["name"], "arguments": arguments},
            }
        )
        ids.add(call_id)
    return calls


def _iter_stream_lines(response):
    """Yield SSE lines as the transport delivers bytes.

    http.client normally returns complete lines, but gateways and alternative
    transports can hand back arbitrary fragments, and the SSE grammar accepts CR,
    LF and CRLF line endings.  Each yielded line keeps exactly one terminator byte
    so the documented byte limits stay meaningful.
    """
    buffer = bytearray()
    while True:
        checkpoint()
        remaining = _MAX_STREAM_LINE + 1 - len(buffer)
        chunk = response.readline(remaining if remaining > 0 else 1)
        if not chunk:
            if buffer:
                yield bytes(buffer)
            return
        buffer += chunk
        while True:
            positions = [index for index in (buffer.find(b"\n"), buffer.find(b"\r")) if index >= 0]
            if not positions:
                break
            index = min(positions)
            yield bytes(buffer[: index + 1])
            del buffer[: index + 1]
        if len(buffer) > _MAX_STREAM_LINE:
            # One line already exceeds the documented limit; the caller raises.
            yield bytes(buffer)
            return


def _decode_stream_json(payload):
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Model stream event is not valid UTF-8") from exc
    return strict_json(text)


def _stream_error_detail(error):
    if isinstance(error, dict):
        parts = [str(error[field]) for field in ("code", "type", "message") if error.get(field)]
        if parts:
            return ": ".join(parts)[:300]
    return str(error)[:300]


def _read_stream(response, on_chunk):
    text = _StreamText(on_chunk)
    tools = {}
    total_bytes = 0
    finish_reason = None
    usage = None
    done = False
    truncated = False
    data_lines = []

    def process_event(chunk):
        nonlocal finish_reason, usage, truncated
        if not isinstance(chunk, dict):
            raise ValueError("Model stream returned an invalid event")
        if "error" in chunk:
            raise _PermanentModelResponse(
                "Model stream returned an error event "
                f"({_stream_error_detail(chunk['error'])}); the request was stopped instead of "
                "being reported as successful. Retry later or check the provider status."
            )
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        choices = chunk.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise ValueError("Invalid model stream choices")
        if not choices:  # Usage-only chunk.
            return
        choice = choices[0]
        delta = choice.get("delta", {}) if isinstance(choice, dict) else None
        if not isinstance(delta, dict):
            raise ValueError("Invalid model stream delta")
        next_finish = choice.get("finish_reason")
        if finish_reason is not None:
            if next_finish is not None and next_finish != finish_reason:
                raise ValueError("Model stream returned conflicting finish reasons")
            if delta:
                raise ValueError("Invalid model stream delta")
            # Providers sometimes repeat the terminal chunk; ignore the duplicate.
            return
        finish_reason = next_finish
        for field in ("reasoning_content", "reasoning", "analysis", "content"):
            value = delta.get(field)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError("Invalid model stream text")
            if field in {"reasoning_content", "reasoning", "analysis"}:
                text.append("reasoning", value)
            else:
                text.content(value)
        if delta.get("tool_calls") is not None:
            _accumulate_tools(tools, delta["tool_calls"])
        if finish_reason is not None and finish_reason not in _FINISH_REASONS_COMPLETE:
            if finish_reason in _FINISH_REASONS_TRUNCATED:
                truncated = True
            elif not (text.parts["content"] or text.parts["reasoning"] or tools):
                # Nothing reached the caller yet, so the request can be retried safely.
                if finish_reason in _FINISH_REASONS_RETRYABLE:
                    raise _RetryableModelResponse(_finish_reason_error(finish_reason))
                raise _PermanentModelResponse(_finish_reason_error(finish_reason))
            elif finish_reason in _FINISH_REASONS_RETRYABLE:
                # Partial output was already streamed; retrying would duplicate it, so the
                # caller continues from the partial reply instead of failing the task.
                truncated = True
            else:
                raise _PermanentModelResponse(_finish_reason_error(finish_reason))

    def dispatch_buffered():
        nonlocal data_lines
        if not data_lines:
            return
        payload = b"\n".join(data_lines)
        data_lines = []
        if payload.strip():
            process_event(_decode_stream_json(payload))

    for raw_line in _iter_stream_lines(response):
        checkpoint()
        if len(raw_line) > _MAX_STREAM_LINE:
            raise ValueError(f"Model stream line exceeded the {_format_byte_limit(_MAX_STREAM_LINE)} limit")
        total_bytes += len(raw_line)
        if total_bytes > _MAX_RESPONSE_BYTES:
            raise ValueError(f"Model response exceeded the {_format_byte_limit(_MAX_RESPONSE_BYTES)} limit")
        line = raw_line.strip()
        if line.startswith(b"\xef\xbb\xbf"):
            # A gateway may prepend a UTF-8 BOM to the first event.
            line = line[3:].strip()
        if not line:
            dispatch_buffered()
            continue
        if not line.startswith(b"data:"):
            # SSE comments (": heartbeat") and unknown fields are ignored.
            continue
        data = line[5:].strip()
        if not data_lines and data == b"[DONE]":
            done = True
            break
        if not data_lines:
            try:
                chunk = _decode_stream_json(data)
            except ValueError:
                # Possibly a spec-compliant multi-line data field; buffer until dispatch.
                data_lines.append(data)
            else:
                process_event(chunk)
        else:
            data_lines.append(data)
    dispatch_buffered()

    if not done and finish_reason is None:
        raise ValueError("Model stream ended without a finish marker")
    if finish_reason == "tool_calls" and not tools:
        raise ValueError("Model stream ended without the indicated tool calls")
    if truncated and text.thinking:
        # A max-token cutoff can land inside a reasoning block; keep the partial reply.
        text.thinking = False
        text.thinking_tag = None
        text.pending = ""
    message = text.message()
    if usage is not None:
        message["usage"] = usage
    if tools:
        try:
            message["tool_calls"] = _complete_tools(tools)
        except ValueError:
            if not truncated:
                raise
            # finish_reason=length can cut the tool-call JSON itself; keep the
            # partial text so the turn can continue instead of failing the task.
            message["truncated_tool_calls"] = True
    if truncated:
        message["truncated"] = True
        message["finish_reason"] = finish_reason
    return message
