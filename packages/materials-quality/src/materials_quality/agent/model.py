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
    def __init__(self, *, base_url=None, model=None, api_key=None, timeout=60):
        self.base_url = base_url or os.environ.get("STUDYUI_MODEL_BASE_URL", "")
        self.model = model or os.environ.get("STUDYUI_MODEL", "")
        self.api_key = api_key if api_key is not None else os.environ.get("STUDYUI_MODEL_API_KEY", "")
        self.timeout = timeout

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
        return self.base_url.rstrip("/") + "/chat/completions"

    def complete(self, messages, tools, *, max_tokens=3000):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = Request(
            self._endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        for attempt in range(2):
            try:
                with build_opener(_NoRedirect).open(request, timeout=self.timeout) as response:
                    raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("Model response exceeded 2 MB")
                body = strict_json(raw.decode("utf-8"))
                message = body["choices"][0]["message"]
                break
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
        if not isinstance(message, dict):
            raise ValueError("Model response did not contain a message")
        return message
