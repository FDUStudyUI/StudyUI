"""DeepSeek Harness (DSH) headless engine host for StudyUI.

Spawns the DSH CLI per turn, parses its NDJSON events and maps them onto
StudyUI progress/results. Credentials come from StudyUI's model profiles, and
permission presets map to DSH sandbox presets. Session ids are persisted so a
turn can resume after a restart.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_DSH_PACKAGE = "@deepseek-ai/dsh@0.2.2-rc.5"
DEFAULT_PROFILE = "studyui"
DEFAULT_TURN_TIMEOUT_SECONDS = 30 * 60
MAX_EVENT_BYTES = 4_000_000

PROFILE_TEMPLATE = """{
  "name": "dsh-profile-studyui",
  "private": true,
  "dependencies": %(dependencies)s,
  "dsh": {
    "profile": {
      "bundles": %(bundles)s
    }
  }
}
"""

PROFILE_PATCH_HEADER = """# StudyUI DSH profile overrides.
# DeepSeek-proprietary request extensions only work against the official
# DeepSeek endpoint, so they are disabled for compatible gateways.
"""


class DshUnavailable(RuntimeError):
    """Raised when the DSH engine cannot be located or provisioned."""


@dataclass(frozen=True)
class DshCommand:
    argv: list[str]
    dsh_home: Path
    profile: str


def _runtime_root(settings_path: Path) -> Path:
    return Path(settings_path).parent


def resolve_dsh_home(settings_path: Path) -> Path:
    configured = os.environ.get("STUDYUI_DSH_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (_runtime_root(settings_path) / "dsh-home").resolve()


def _dsh_roots(runtime_root: Path) -> list[Path]:
    """DSH install roots: runtime data (source setup) and portable program dir."""
    roots = [runtime_root / "dsh"]
    portable = runtime_root.parent / "runtime" / "dsh"
    if portable not in roots:
        roots.append(portable)
    return roots


def _bundled_node(runtime_root: Path) -> Path:
    for root in _dsh_roots(runtime_root):
        candidates = [
            root / "node" / "node.exe",
            root / "node" / "node",
            root / "node" / "bin" / "node",
        ]
        found = next((p for p in candidates if p.is_file()), None)
        if found is not None:
            return found
    return Path()


def _bundled_dsh_bin(runtime_root: Path) -> Path:
    for root in _dsh_roots(runtime_root):
        candidate = root / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
        if candidate.is_file():
            return candidate
    return _dsh_roots(runtime_root)[0] / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"


def resolve_command(settings_path: Path, profile: str = DEFAULT_PROFILE) -> DshCommand | None:
    """Locate a runnable DSH. Returns None when DSH is not provisioned."""
    runtime_root = _runtime_root(settings_path)
    override = os.environ.get("STUDYUI_DSH_BIN", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.suffix.lower() == ".js":
            node = os.environ.get("STUDYUI_NODE_BIN", "").strip() or shutil.which("node") or ""
            if not node:
                return None
            return DshCommand([str(node), str(path)], resolve_dsh_home(settings_path), profile)
        return DshCommand([str(path)], resolve_dsh_home(settings_path), profile)
    bundled = _bundled_dsh_bin(runtime_root)
    if bundled.is_file():
        node = _bundled_node(runtime_root)
        node_bin = (
            str(node) if node.is_file() else (os.environ.get("STUDYUI_NODE_BIN") or shutil.which("node"))
        )
        if node_bin:
            return DshCommand([str(node_bin), str(bundled)], resolve_dsh_home(settings_path), profile)
    which = shutil.which("dsh")
    if which:
        return DshCommand([which], resolve_dsh_home(settings_path), profile)
    return None


def available(settings_path: Path) -> bool:
    return resolve_command(settings_path) is not None


def map_base_url(base_url: str, *, allow_env_override: bool = True) -> str:
    """Map a StudyUI model base URL to an Anthropic-compatible endpoint."""
    explicit = os.environ.get("STUDYUI_DSH_BASE_URL", "").strip() if allow_env_override else ""
    if explicit:
        return explicit.rstrip("/")
    raw = (base_url or "").strip()
    if not raw:
        return "https://api.deepseek.com/anthropic"
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower()
    if host in {"api.deepseek.com", "api.deepseek.cn"}:
        # OpenAI-compatible /v1 is not part of the Messages API base path.
        return parsed._replace(path="/anthropic", query="", fragment="").geturl()
    return raw.rstrip("/")


def ensure_profile(
    settings_path: Path,
    *,
    profile: str = DEFAULT_PROFILE,
    sdk: bool = False,
) -> Path:
    """Create the StudyUI DSH profile on first use and return its directory."""
    home = resolve_dsh_home(settings_path)
    profile_dir = home / "profiles" / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    package_path = profile_dir / "package.json"
    app_bundle = "@deepseek-ai/dsh-sdk-app" if sdk else "@deepseek-ai/dsh-headless"
    bundles = ["@deepseek-ai/dsh-base", app_bundle]
    package_path.write_text(
        PROFILE_TEMPLATE
        % {
            "dependencies": json.dumps({}, indent=4),
            "bundles": json.dumps(bundles, indent=6),
        },
        encoding="utf-8",
    )
    patch = [PROFILE_PATCH_HEADER]
    patch.append("- id: session-log-deepseek\n  disabled: true\n")
    patch.append("- id: plugin-package-inventory-deepseek\n  disabled: true\n")
    model = os.environ.get("STUDYUI_DSH_MODEL", "").strip()
    if model:
        patch.append(
            f"- id: agent-default-model\n  config:\n    provider: deepseek-official\n    model: {model}\n"
        )
    (profile_dir / "cordis.patch.yml").write_text("".join(patch), encoding="utf-8")
    instructions = home / "AGENTS.md"
    if not instructions.is_file():
        instructions.write_text(studyui_instructions(), encoding="utf-8")
    return profile_dir


def studyui_instructions() -> str:
    return """# StudyUI agent instructions

You are StudyUI's research agent for materials science. Work inside the project
directory you are given; keep every result traceable to inputs, parameters and
warnings.

## Deterministic science tools

Prefer StudyUI's registered science operations over re-implementing analysis
code. Run them with the project Python:

    python -m materials_quality.science_tools list
    python -m materials_quality.science_tools show <operation>
    python -m materials_quality.science_tools run <operation> --config '<json>' --table <csv>

Operations are strict: they reject missing units, ambiguous columns and
unconfirmed destructive interpretations instead of guessing. Read the error
message and supply the missing scientific premise.

## Reporting

- Report numbers with units and the method/parameters that produced them.
- Distinguish observations, literature evidence and hypotheses.
- When a required premise is unknown (e.g. strain units), state the ambiguity
  and ask the researcher instead of assuming.
"""


def permission_flags(preset: str) -> list[str]:
    """Map a StudyUI permission preset to DSH headless flags."""
    preset = (preset or "project_collaboration").strip()
    if preset == "read_only":
        return ["--permission-mode", "read-only", "--approval-policy", "never"]
    if preset == "per_action":
        return ["--permission-mode", "workspace-write", "--approval-policy", "ask"]
    if preset == "full_access":
        return ["--permission-mode", "danger-full-access", "--approval-policy", "never"]
    return ["--permission-mode", "workspace-write", "--approval-policy", "never"]


def _agent_temp_dir(working_directory: Path) -> Path | None:
    """A writable temp root outside the agent's workspace grant."""
    candidates = []
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        candidates.append(Path(base) / "StudyUI" / "dsh-tmp")
    candidates.append(Path(os.path.expanduser("~")) / ".studyui" / "dsh-tmp")
    workspace = working_directory.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved == workspace or workspace in resolved.parents:
            continue
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            return resolved
        except OSError:
            continue
    return None


def _is_secret_env(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))


def build_env(
    *,
    base_url: str,
    api_key: str,
    working_directory: Path,
    dsh_home: Path | None = None,
    extra: dict | None = None,
    allow_env_override: bool = True,
) -> dict:
    # Keep unrelated provider credentials out of the agent runtime; the model
    # key itself is injected explicitly below.
    env = {key: value for key, value in os.environ.items() if not _is_secret_env(key)}
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    if dsh_home is not None:
        env["DSH_HOME"] = str(dsh_home)
    env["DEEPSEEK_BASE_URL"] = map_base_url(base_url, allow_env_override=allow_env_override)
    if api_key:
        env["DEEPSEEK_API_KEY"] = api_key
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # DSH's Windows sandbox refuses a temp directory inside the workspace grant,
    # and StudyUI's launcher points TEMP at .demo-runtime/tmp (inside the
    # project). Give the agent a temp root that is guaranteed outside the
    # workspace.
    dsh_tmp = _agent_temp_dir(working_directory)
    if dsh_tmp is not None:
        env["TEMP"] = str(dsh_tmp)
        env["TMP"] = str(dsh_tmp)
        env["TMPDIR"] = str(dsh_tmp)
    # Make the StudyUI Python (with materials_quality installed) the default
    # `python` for the agent's Bash/exec tools.
    python_dir = str(Path(sys.executable).resolve().parent)
    env["PATH"] = python_dir + os.pathsep + env.get("PATH", "")
    env["STUDYUI_PROJECT_DIR"] = str(working_directory)
    return env


def build_argv(
    command: DshCommand,
    *,
    message: str,
    permission_preset: str,
    session_id: str | None = None,
    max_turns: int | None = None,
    permission_mode: str | None = None,
) -> list[str]:
    argv = list(command.argv)
    argv += ["--profile", command.profile, "--json"]
    if permission_mode == "danger-full-access":
        argv += ["--permission-mode", "danger-full-access", "--approval-policy", "never"]
    else:
        argv += permission_flags(permission_preset)
    if max_turns:
        argv += ["--max-turns", str(int(max_turns))]
    if session_id:
        argv += ["--session-id", session_id]
    argv.append(message)
    return argv


def _iter_json_lines(stream):
    buffer = b""
    total = 0
    for chunk in iter(lambda: stream.read(4096), b""):
        total += len(chunk)
        if total > MAX_EVENT_BYTES:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.strip()
            if line:
                try:
                    yield json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
    if buffer.strip():
        with contextlib.suppress(json.JSONDecodeError):
            yield json.loads(buffer.decode("utf-8", "replace"))


def run_turn(
    *,
    settings_path: Path,
    message: str,
    working_directory: Path,
    permission_preset: str,
    base_url: str,
    api_key: str,
    model: str,
    session_id: str | None = None,
    on_progress=None,
    on_session_id=None,
    timeout_seconds: int | None = None,
    max_turns: int | None = None,
    _force_mode: str | None = None,
) -> dict:
    """Run one agent turn through DSH and return a StudyUI-compatible result."""
    command = resolve_command(settings_path)
    if command is None:
        raise DshUnavailable("DeepSeek Harness is not provisioned")
    os.environ.setdefault("STUDYUI_DSH_MODEL", model)
    ensure_profile(settings_path, profile=command.profile)
    argv = build_argv(
        command,
        message=message,
        permission_preset=permission_preset,
        session_id=session_id,
        max_turns=max_turns,
        permission_mode=_force_mode,
    )
    env = build_env(
        base_url=base_url,
        api_key=api_key,
        working_directory=working_directory,
        dsh_home=command.dsh_home,
    )
    timeout = timeout_seconds or int(
        os.environ.get("STUDYUI_DSH_TIMEOUT_SECONDS", DEFAULT_TURN_TIMEOUT_SECONDS)
    )
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        argv,
        cwd=str(working_directory),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    deadline = time.monotonic() + timeout
    timed_out = threading.Event()

    def _kill():
        timed_out.set()
        with contextlib.suppress(Exception):
            proc.kill()

    timer = threading.Timer(max(1.0, timeout), _kill)
    timer.daemon = True
    timer.start()

    text_parts: list[str] = []
    tool_steps: list[dict] = []
    usage_total = {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0}
    dsh_session_id = session_id or ""
    final_text = ""
    failure = ""
    sandbox_blocked = False
    pending_calls: dict[str, dict] = {}

    def emit(event_type, payload=None):
        if on_progress:
            try:
                data = {"type": event_type, "model": model or "DSH"}
                if payload:
                    data.update(payload)
                on_progress(data)
            except Exception:
                pass

    try:
        assert proc.stdout is not None
        for event in _iter_json_lines(proc.stdout):
            if time.monotonic() > deadline:
                _kill()
                break
            kind = event.get("type")
            if kind == "session":
                dsh_session_id = str(event.get("sessionId") or dsh_session_id)
                if on_session_id and dsh_session_id:
                    with contextlib.suppress(Exception):
                        on_session_id(dsh_session_id)
            elif kind == "status":
                phase = event.get("phase")
                if phase == "step_start":
                    emit("step_start", {"round": event.get("step")})
                elif phase == "step_end":
                    usage = event.get("usage") or {}
                    for key in usage_total:
                        with contextlib.suppress(TypeError, ValueError):
                            usage_total[key] += int(usage.get(key) or 0)
                    emit(
                        "usage",
                        {
                            "token_usage": {
                                "input_tokens": usage_total["inputTokens"],
                                "output_tokens": usage_total["outputTokens"],
                                "cache_read_tokens": usage_total["cacheReadTokens"],
                                "cache_write_tokens": usage_total["cacheWriteTokens"],
                            }
                        },
                    )
                    emit("step_end")
                elif phase == "turn_end":
                    reason = event.get("reason") or {}
                    if reason.get("kind") not in (None, "completed"):
                        failure = str(
                            (reason.get("error") or {}).get("message")
                            or f"DSH turn ended with {reason.get('kind')}"
                        )
            elif kind == "thinking":
                text = str(event.get("text") or "")
                if text:
                    emit("reasoning", {"delta": text})
            elif kind == "text":
                chunk = str(event.get("text") or "")
                if chunk:
                    text_parts.append(chunk)
                    emit("content_chunk", {"delta": chunk})
            elif kind == "tool_call":
                call_id = str(event.get("callId") or "")
                name = str(event.get("tool") or "")
                step = {
                    "id": call_id,
                    "name": name,
                    "title": name,
                    "icon": "Wrench",
                    "arguments": event.get("input"),
                    "status": "running",
                }
                pending_calls[call_id] = step
                tool_steps.append(step)
                emit(
                    "tool_start",
                    {
                        "id": call_id,
                        "name": name,
                        "title": name,
                        "icon": "Wrench",
                        "summary": str(event.get("input") or "")[:200],
                    },
                )
            elif kind == "tool_result":
                call_id = str(event.get("callId") or "")
                step = pending_calls.pop(call_id, None)
                status = str(event.get("status") or "")
                result = event.get("result")
                result_text = str(result) if result is not None else ""
                if (
                    "workspace grant failed" in result_text
                    or "windows-acl" in result_text
                    or "grantWrite(" in result_text
                ):
                    sandbox_blocked = True
                if step is not None:
                    step["status"] = (
                        "completed" if status in ("completed", "success") else status or "completed"
                    )
                    step["summary"] = result_text[:500]
                emit(
                    "tool_end",
                    {
                        "step": {
                            "id": call_id,
                            "name": (step or {}).get("name", ""),
                            "status": (step or {}).get("status", "completed"),
                            "summary": result_text[:500],
                        }
                    },
                )
            elif kind == "final":
                final_text = str(event.get("text") or "")
                dsh_session_id = str(event.get("sessionId") or dsh_session_id)
                reason = event.get("reason") or {}
                if reason.get("kind") not in (None, "completed") and not failure:
                    failure = f"DSH turn ended with {reason.get('kind')}"
    finally:
        timer.cancel()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        stderr_text = ""
        try:
            if proc.stderr is not None:
                stderr_text = proc.stderr.read().decode("utf-8", "replace")[-4000:]
        except Exception:
            pass

    message_text = final_text or "".join(text_parts).strip()
    if timed_out.is_set():
        failure = f"DSH turn timed out after {timeout}s"
    elif not message_text and not failure:
        detail = "\n".join(stderr_text.strip().splitlines()[-15:]) if stderr_text.strip() else ""
        suffix = "\n" + detail if detail else ""
        failure = "DSH returned no answer:" + suffix
    emit("done", {"status": "failed" if failure else "completed"})
    sandbox_blocked = sandbox_blocked or bool(
        failure
        and ("workspace grant failed" in failure or "windows-acl" in failure or "grantWrite(" in failure)
    )
    if sandbox_blocked and _force_mode != "danger-full-access" and permission_preset != "read_only":
        # MatOS-style fallback: when the OS sandbox cannot be applied on this
        # host, rerun with full access and record the degradation.
        fallback = run_turn(
            settings_path=settings_path,
            message=message,
            working_directory=working_directory,
            permission_preset=permission_preset,
            base_url=base_url,
            api_key=api_key,
            model=model,
            session_id=dsh_session_id or session_id,
            on_progress=on_progress,
            timeout_seconds=timeout_seconds,
            max_turns=max_turns,
            _force_mode="danger-full-access",
        )
        fallback["permission_fallback"] = "danger-full-access"
        return fallback
    return {
        "status": "failed" if failure else "completed",
        "message": message_text,
        "error": failure,
        "session_id": dsh_session_id,
        "tool_steps": tool_steps,
        "usage": usage_total,
        "stderr": stderr_text if failure else "",
        "exit_code": proc.returncode,
        "permission_fallback": "danger-full-access" if _force_mode == "danger-full-access" else "",
    }
