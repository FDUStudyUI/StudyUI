"""Official DSH Python SDK engine host for StudyUI.

Keeps one DSH runtime per session, resumes persisted sessions, projects SDK
events onto StudyUI progress, and bridges approval requests onto the one-shot
approval store. Selected as ``dsh-sdk``; falls back to headless or legacy when
unavailable.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import dsh_engine

SDK_PROFILE = "studyui-sdk"
DEFAULT_TIMEOUT_SECONDS = 30 * 60
APPROVAL_TIMEOUT_SECONDS = 15 * 60

_WAITERS: dict[str, dict] = {}
_WAITERS_LOCK = threading.Lock()


def register_waiter(approval_id: str) -> None:
    """Register the approval waiter before the approval row becomes visible."""
    with _WAITERS_LOCK:
        _WAITERS.setdefault(approval_id, {"event": threading.Event(), "outcome": None})


def wait_for_decision(approval_id: str, timeout: float = APPROVAL_TIMEOUT_SECONDS) -> str | None:
    """Block until the approval is decided; returns approved/rejected/cancelled or None."""
    with _WAITERS_LOCK:
        entry = _WAITERS.setdefault(approval_id, {"event": threading.Event(), "outcome": None})
    try:
        entry["event"].wait(timeout)
        return entry["outcome"]
    finally:
        with _WAITERS_LOCK:
            _WAITERS.pop(approval_id, None)


def signal_decision(approval_id: str, outcome: str = "approved") -> None:
    """Wake the waiter with the terminal outcome (approved/rejected/cancelled)."""
    with _WAITERS_LOCK:
        entry = _WAITERS.get(approval_id)
    if entry is not None:
        entry["outcome"] = outcome
        entry["event"].set()


def sdk_available() -> bool:
    try:
        import deepseek_harness  # noqa: F401
    except Exception:
        return False
    return True


def available(settings_path: Path) -> bool:
    if not sdk_available():
        return False
    return dsh_engine.resolve_command(settings_path) is not None


@dataclass
class _Runtime:
    harness: object
    owner_session_id: str = ""
    pump: threading.Thread | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    cancel: threading.Event = field(default_factory=threading.Event)


class _RuntimePool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runtimes: dict[str, _Runtime] = {}

    def get(self, key: str) -> _Runtime | None:
        with self._lock:
            return self._runtimes.get(key)

    def put(self, key: str, runtime: _Runtime) -> None:
        with self._lock:
            self._runtimes[key] = runtime

    def discard(self, key: str) -> None:
        with self._lock:
            self._runtimes.pop(key, None)

    def for_owner(self, owner_session_id: str) -> list[tuple[str, _Runtime]]:
        with self._lock:
            return [
                (key, runtime)
                for key, runtime in self._runtimes.items()
                if runtime.owner_session_id == owner_session_id
            ]


POOL = _RuntimePool()


def _launch_args(command: dsh_engine.DshCommand) -> tuple[str, ...]:
    return (*command.argv, "--profile", SDK_PROFILE)


def _build_runtime(
    *,
    settings_path: Path,
    command: dsh_engine.DshCommand,
    working_directory: Path,
    base_url: str,
    api_key: str,
    model: str,
    on_permission,
    owner_session_id: str = "",
) -> _Runtime:
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

    env = dsh_engine.build_env(
        base_url=base_url,
        api_key=api_key,
        working_directory=working_directory,
        dsh_home=command.dsh_home,
    )
    dsh_engine.ensure_profile(settings_path, base_url=base_url, profile=SDK_PROFILE, sdk=True)
    config = DeepSeekHarnessConfig(
        provider="deepseek-official",
        model=model,
        cwd=str(working_directory),
        dsh_home=str(command.dsh_home),
        env=env,
        approval_requests=True,
        initialize_timeout_seconds=60.0,
        request_timeout_seconds=None,
    )
    harness = DeepSeekHarness(config, _launch_args=_launch_args(command))
    try:
        harness.start()
    except Exception as exc:
        raise dsh_engine.DshUnavailable(f"DSH SDK start failed: {exc}") from exc
    runtime = _Runtime(harness=harness, owner_session_id=owner_session_id)

    def pump() -> None:
        client = harness.client
        while not runtime.stop.is_set():
            try:
                request = client.next_request()
            except Exception:
                return
            method = getattr(request, "method", "")
            request_id = getattr(request, "id", None)
            params = getattr(request, "payload", None) or getattr(request, "params", None) or {}
            if method == "approval/request":
                outcome = "rejected"
                try:
                    outcome = str(on_permission(params) or "rejected")
                except Exception:
                    outcome = "rejected"
                try:
                    client.respond(
                        request_id,
                        {"outcome": "allowed-once" if outcome == "approved" else "rejected"},
                    )
                except Exception:
                    return
            else:
                try:
                    client.respond_error(request_id, -32601, f"unsupported request: {method}")
                except Exception:
                    return

    runtime.pump = threading.Thread(target=pump, name="dsh-approval-pump", daemon=True)
    runtime.pump.start()
    return runtime


def _message_text(message) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _project_event(event: dict, calls: dict[str, str], streamed: set[str]) -> tuple[list[dict], dict | None]:
    """Map one DSH session event to StudyUI progress events and optional usage."""
    kind = str(event.get("type") or "")
    data = event.get("data") or {}
    out: list[dict] = []
    usage = None
    if kind == "agent/assistant-stream":
        chunk = data.get("chunk") or data
        text = chunk.get("text") if isinstance(chunk, dict) else None
        if isinstance(text, str) and text:
            step_key = f"{data.get('turn')}:{data.get('step')}"
            streamed.add(step_key)
            out.append({"type": "content_chunk", "delta": text})
    elif kind == "assistant/message":
        step_key = f"{data.get('turn')}:{data.get('step')}"
        text = _message_text(data.get("message"))
        if text and step_key not in streamed:
            out.append({"type": "content_chunk", "delta": text})
        reasoning = "".join(
            str(part)
            for record in data.get("stream") or []
            if isinstance(record, dict) and record.get("type") == "reasoning-chunks"
            for part in record.get("texts") or []
        )
        if reasoning:
            out.append({"type": "reasoning", "delta": reasoning})
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    elif kind == "tool/call":
        call_id = str(data.get("callId") or "")
        name = str(data.get("name") or "")
        if call_id:
            calls[call_id] = name
        out.append(
            {
                "type": "tool_start",
                "id": call_id,
                "name": name,
                "title": name,
                "icon": "Wrench",
                "summary": str(data.get("arguments") or "")[:200],
            }
        )
    elif kind == "tool/result":
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        call_id = str(message.get("toolCallId") or "")
        out.append(
            {
                "type": "tool_end",
                "step": {
                    "id": call_id,
                    "name": calls.get(call_id, ""),
                    "status": "failed" if message.get("isError") else "completed",
                    "summary": "",
                },
            }
        )
    return out, usage


def _summarize_run(result) -> tuple[dict, list[dict]]:
    """Build token usage and tool steps from the SDK's durable root events."""
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    calls: dict[str, dict] = {}
    steps: list[dict] = []
    for event in getattr(result, "events", []) or []:
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        data = event.get("data") or {}
        if kind == "assistant/message":
            item = data.get("usage") or {}
            for source, target in (
                ("inputTokens", "input_tokens"),
                ("outputTokens", "output_tokens"),
                ("cacheReadTokens", "cache_read_tokens"),
                ("cacheWriteTokens", "cache_write_tokens"),
            ):
                with contextlib.suppress(TypeError, ValueError):
                    usage[target] += int(item.get(source) or 0)
        elif kind == "tool/call":
            call_id = str(data.get("callId") or "")
            step = {
                "id": call_id,
                "name": str(data.get("name") or ""),
                "arguments": str(data.get("arguments") or "")[:500],
                "status": "completed",
            }
            calls[call_id] = step
            steps.append(step)
        elif kind == "tool/result":
            message = data.get("message") if isinstance(data.get("message"), dict) else {}
            step = calls.get(str(message.get("toolCallId") or ""))
            if step is not None and message.get("isError"):
                step["status"] = "failed"
    return usage, steps


def _preset_mode(preset: str) -> str:
    if preset in {"read_only", "per_action"}:
        return "read-only"
    return "workspace-write"


def _apply_permission(session, mode: str) -> tuple[bool, str]:
    try:
        result = session.run(f"/permission {mode}")
    except Exception as exc:
        return False, str(exc)
    reason = getattr(result, "finish_reason", None)
    if reason not in (None, "completed"):
        return False, f"finish_reason={reason}"
    return True, ""


def _dispose(key: str, runtime: _Runtime) -> None:
    POOL.discard(key)
    runtime.stop.set()
    with contextlib.suppress(Exception):
        runtime.harness.close()


def request_cancel(owner_session_id: str) -> None:
    """Cancel the active turn for a StudyUI session (watchdog closes its runtime)."""
    for _key, runtime in POOL.for_owner(owner_session_id):
        runtime.cancel.set()


def release(owner_session_id: str) -> None:
    """Stop and remove every runtime owned by a StudyUI session."""
    for key, runtime in POOL.for_owner(owner_session_id):
        _dispose(key, runtime)


def run_turn(
    *,
    settings_path: Path,
    message: str,
    working_directory: Path,
    permission_preset: str,
    base_url: str,
    api_key: str,
    model: str,
    session_id: str | None,
    owner_session_id: str | None = None,
    on_progress=None,
    on_permission=None,
    on_session_id=None,
    timeout_seconds: int | None = None,
) -> dict:
    """Run one StudyUI turn through the DSH SDK engine with a hard deadline."""
    if not sdk_available():
        raise dsh_engine.DshUnavailable("deepseek-harness-sdk is not installed")
    command = dsh_engine.resolve_command(settings_path)
    if command is None:
        raise dsh_engine.DshUnavailable("DeepSeek Harness is not provisioned")
    timeout = timeout_seconds or int(os.environ.get("STUDYUI_DSH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    owner = owner_session_id or session_id or ""
    key = json.dumps([owner, str(working_directory), base_url, model], ensure_ascii=False)
    try:
        runtime = POOL.get(key)
        if runtime is None:
            runtime = _build_runtime(
                settings_path=settings_path,
                command=command,
                working_directory=working_directory,
                base_url=base_url,
                api_key=api_key,
                model=model,
                on_permission=lambda params: on_permission(
                    str(params.get("toolName") or ""), str(params.get("reason") or "")
                ),
                owner_session_id=owner,
            )
            POOL.put(key, runtime)
    except dsh_engine.DshUnavailable:
        raise
    except Exception as exc:
        raise dsh_engine.DshUnavailable(f"DSH SDK start failed: {exc}") from exc

    harness = runtime.harness
    runtime.cancel.clear()

    def emit(event_type, payload=None):
        if on_progress:
            with contextlib.suppress(Exception):
                data = {"type": event_type, "model": model or "DSH"}
                if payload:
                    data.update(payload)
                on_progress(data)

    def attempt(session, prompt: str) -> dict:
        state = {
            "parts": [],
            "final": "",
            "failure": "",
            "blocked": False,
            "sid": session_id or "",
            "usage": {},
            "tool_steps": [],
            "cancelled": False,
            "timed_out": False,
        }
        calls: dict[str, str] = {}
        streamed: set[str] = set()

        def note(notification) -> None:
            method = getattr(notification, "method", "")
            payload = getattr(notification, "payload", None) or {}
            if method == "session.status":
                if payload.get("status") == "running":
                    emit("step_start")
                return
            if method != "session.event":
                return
            event = payload.get("event")
            if not isinstance(event, dict):
                return
            blob = json.dumps(event, ensure_ascii=False)
            if "workspace grant failed" in blob or "windows-acl" in blob or "grantWrite(" in blob:
                state["blocked"] = True
            projected, usage = _project_event(event, calls, streamed)
            for item in projected:
                kind = item.pop("type")
                if kind == "content_chunk":
                    state["parts"].append(item.get("delta", ""))
                emit(kind, item)
            if usage:
                for source, target in (
                    ("inputTokens", "input_tokens"),
                    ("outputTokens", "output_tokens"),
                    ("cacheReadTokens", "cache_read_tokens"),
                    ("cacheWriteTokens", "cache_write_tokens"),
                ):
                    with contextlib.suppress(TypeError, ValueError):
                        state["usage"][target] = state["usage"].get(target, 0) + int(usage.get(source) or 0)
            if event.get("type") == "turn/end":
                reason = (event.get("data") or {}).get("reason") or {}
                if reason.get("kind") not in (None, "completed"):
                    state["failure"] = str(
                        (reason.get("error") or {}).get("message")
                        or f"DSH turn ended with {reason.get('kind')}"
                    )

        outcome: dict = {}
        done = threading.Event()

        def run() -> None:
            try:
                outcome["result"] = session.run(prompt, on_notification=note)
            except Exception as exc:
                outcome["error"] = exc
            finally:
                done.set()

        threading.Thread(target=run, name="dsh-sdk-turn", daemon=True).start()
        deadline = time.monotonic() + timeout
        while not done.wait(0.5):
            if runtime.cancel.is_set():
                state["cancelled"] = True
                state["failure"] = "DSH turn cancelled"
                _dispose(key, runtime)
                return state
            if time.monotonic() > deadline:
                state["timed_out"] = True
                state["failure"] = f"DSH turn timed out after {timeout}s"
                _dispose(key, runtime)
                return state
        error = outcome.get("error")
        if error is not None:
            state["failure"] = f"{type(error).__name__}: {error}"
            return state
        result = outcome.get("result")
        if result is None:
            state["failure"] = "DSH returned no result"
            return state
        state["final"] = result.final_response or ""
        state["sid"] = result.session_id
        if result.finish_reason not in (None, "completed") and not state["failure"]:
            state["failure"] = f"DSH turn ended with {result.finish_reason}"
        summary_usage, summary_steps = _summarize_run(result)
        if any(summary_usage.values()):
            state["usage"] = summary_usage
        if summary_steps:
            state["tool_steps"] = summary_steps
        if state["usage"]:
            emit("usage", {"token_usage": state["usage"]})
        return state

    resume_reset = False
    try:
        try:
            session = harness.resume_session(session_id) if session_id else harness.start_session()
        except Exception:
            resume_reset = True
            session = harness.start_session()
        if on_session_id:
            with contextlib.suppress(Exception):
                on_session_id(session.id)
        mode = _preset_mode(permission_preset)
        ok, detail = _apply_permission(session, mode)
        if not ok:
            _dispose(key, runtime)
            return {
                "status": "failed",
                "message": "",
                "error": f"DSH permission preset {mode} could not be applied: {detail}",
                "session_id": session.id,
                "tool_steps": [],
                "usage": {},
                "resume_reset": resume_reset,
                "permission_failed": True,
            }
        state = attempt(session, message)
        if state["blocked"] and permission_preset != "read_only":
            fallback_ok, _ = _apply_permission(session, "danger-full-access")
            if fallback_ok:
                state = attempt(session, message)
                state["permission_fallback"] = "danger-full-access"
    except Exception as exc:
        _dispose(key, runtime)
        return {
            "status": "failed",
            "message": "",
            "error": f"{type(exc).__name__}: {exc}",
            "session_id": session_id or "",
            "tool_steps": [],
            "usage": {},
            "resume_reset": resume_reset,
        }

    failure = state["failure"]
    status = "cancelled" if state.get("cancelled") else ("failed" if failure else "completed")
    emit("done", {"status": "failed" if status != "completed" else "completed"})
    return {
        "status": status,
        "message": state["final"] or "".join(state["parts"]).strip(),
        "error": failure,
        "session_id": state["sid"],
        "tool_steps": state["tool_steps"],
        "usage": state["usage"],
        "permission_fallback": state.get("permission_fallback", ""),
        "resume_reset": resume_reset,
        "timed_out": state.get("timed_out", False),
    }


def shutdown() -> None:
    """Stop all pooled DSH SDK runtimes (called on service shutdown/tests)."""
    with POOL._lock:
        runtimes = list(POOL._runtimes.values())
        POOL._runtimes.clear()
    for runtime in runtimes:
        runtime.stop.set()
        with contextlib.suppress(Exception):
            runtime.harness.close()
