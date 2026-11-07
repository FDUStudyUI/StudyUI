"""OpenAI-compatible chat-completions client with bounded tool calling."""

from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


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
        request = Request(
            self._endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        for attempt in range(2):
            try:
                with build_opener(_NoRedirect).open(request, timeout=self.timeout) as response:
                    content_type = response.headers.get("Content-Type", "") if hasattr(response, "headers") else ""
                    if is_stream and ("text/event-stream" in content_type or not content_type):
                        accumulated_content = []
                        accumulated_reasoning = []
                        accumulated_tools = []
                        total_bytes = 0
                        in_thinking = False
                        for line in response:
                            total_bytes += len(line)
                            if total_bytes > 2_000_000:
                                raise ValueError("Model response exceeded 2 MB")
                            line = line.strip()
                            if not line.startswith(b"data:"):
                                continue
                            data_str = line[5:].strip().decode("utf-8")
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk_obj = json.loads(data_str)
                                choices = chunk_obj.get("choices") or []
                                if not choices:
                                    continue
                                choice = choices[0]
                                delta = choice.get("delta") or {}
                                if delta.get("reasoning_content"):
                                    r_delta = delta["reasoning_content"]
                                    accumulated_reasoning.append(r_delta)
                                    if on_chunk:
                                        on_chunk("reasoning", r_delta)
                                if delta.get("content"):
                                    c_delta = delta["content"]
                                    if "<think>" in c_delta and not in_thinking:
                                        in_thinking = True
                                        parts = c_delta.split("<think>", 1)
                                        if parts[0]:
                                            accumulated_content.append(parts[0])
                                            if on_chunk:
                                                on_chunk("content", parts[0])
                                        c_delta = parts[1]
                                    if in_thinking:
                                        if "</think>" in c_delta:
                                            in_thinking = False
                                            parts = c_delta.split("</think>", 1)
                                            if parts[0]:
                                                accumulated_reasoning.append(parts[0])
                                                if on_chunk:
                                                    on_chunk("reasoning", parts[0])
                                            if parts[1]:
                                                accumulated_content.append(parts[1])
                                                if on_chunk:
                                                    on_chunk("content", parts[1])
                                        else:
                                            accumulated_reasoning.append(c_delta)
                                            if on_chunk:
                                                on_chunk("reasoning", c_delta)
                                    else:
                                        accumulated_content.append(c_delta)
                                        if on_chunk:
                                            on_chunk("content", c_delta)
                                if delta.get("tool_calls"):
                                    for tc in delta["tool_calls"]:
                                        idx = tc.get("index", 0)
                                        while len(accumulated_tools) <= idx:
                                            accumulated_tools.append({
                                                "id": "",
                                                "type": "function",
                                                "function": {"name": "", "arguments": ""},
                                            })
                                        if tc.get("id"):
                                            accumulated_tools[idx]["id"] += tc["id"]
                                        fn = tc.get("function", {})
                                        if fn.get("name"):
                                            accumulated_tools[idx]["function"]["name"] += fn["name"]
                                        if fn.get("arguments"):
                                            accumulated_tools[idx]["function"]["arguments"] += fn["arguments"]
                            except Exception:
                                continue
                        message = {
                            "role": "assistant",
                            "content": "".join(accumulated_content) if accumulated_content else None,
                        }
                        if accumulated_reasoning:
                            message["reasoning_content"] = "".join(accumulated_reasoning)
                        if accumulated_tools:
                            message["tool_calls"] = accumulated_tools
                        return message
                    else:
                        raw = response.read(2_000_001)
                        if len(raw) > 2_000_000:
                            raise ValueError("Model response exceeded 2 MB")
                        body = strict_json(raw.decode("utf-8"))
                        return body["choices"][0]["message"]
            except HTTPError as exc:
                if attempt == 0 and (exc.code == 429 or 500 <= exc.code < 600):
                    time.sleep(0.4)
                    continue
                raise ValueError(f"Model service returned HTTP {exc.code}") from None
            except (URLError, OSError) as exc:
                if attempt == 0:
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
                msg = self._execute_http(payload, headers, is_stream=True, on_chunk=on_chunk)
                if isinstance(msg, dict) and (msg.get("content") is not None or msg.get("tool_calls") or msg.get("reasoning_content")):
                    return msg
            except Exception:
                pass
            # Streaming failed on this endpoint or returned empty; cleanly fallback to non-streaming HTTP
            payload.pop("stream", None)
            headers["Accept"] = "application/json"
            message = self._execute_http(payload, headers, is_stream=False, on_chunk=None)
        else:
            headers["Accept"] = "application/json"
            message = self._execute_http(payload, headers, is_stream=False, on_chunk=None)

        if not isinstance(message, dict):
            raise ValueError("Model response did not contain a message")
        return message
