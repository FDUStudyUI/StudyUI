#!/usr/bin/env python3
"""Reproducible harness evaluation for StudyUI using only DeepSeek Flash.

The benchmark is a fixed, synthetic materials-science task set derived from the
public MatOS benchmark profile and its published task-pitfall note.  Scoring is
deterministic: every task declares numeric checks, evidence checks and a
tool-use check; no judge model is used.

Harnesses
---------
studyui
    The StudyUI Python agent harness (its registered tools, system prompt and
    skill preflight) against the same model route.
native_dsh
    The installed DeepSeek Harness headless profile with no StudyUI tools,
    prompts, MCP server or project instructions.
claude_code / codex
    The installed CLIs, when detected.  They are only recorded as available
    when the local installation and the DeepSeek route can actually run.
matos
    Detected but never installed or executed by this script.

Usage
-----
    python materials-quality/scripts/evaluate_harnesses.py probe
    python materials-quality/scripts/evaluate_harnesses.py run --repeats 2
    python materials-quality/scripts/evaluate_harnesses.py run \
        --harnesses studyui,native_dsh --tasks mechanics_modulus,xrd_dspacing --repeats 1
    python materials-quality/scripts/evaluate_harnesses.py run --studyui-source /path/to/old/src

Raw run logs and JSONL transcripts are written below
``materials-quality/artifacts/harness-bench/`` (gitignored).
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
MQ = ROOT / "materials-quality"
FIXTURES = MQ / "testfixtures" / "harness_bench"
TASKS_FILE = FIXTURES / "tasks.json"
DEFAULT_OUTPUT = MQ / "artifacts" / "harness-bench"

MODEL = "deepseek-flash"
MODEL_LABEL = "DeepSeek V4.1 Flash (official deepseek-flash)"
BASE_URL = "https://api.deepseek.com"
ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
MODEL_PROBE_URL = BASE_URL + "/chat/completions"

_DSH_BIN_ENV = os.environ.get("DSH_BIN", "").strip()
DEFAULT_DSH_BIN = (
    Path(_DSH_BIN_ENV)
    if _DSH_BIN_ENV
    else (
        Path.home()
        / "AppData"
        / "Local"
        / "StudyUI"
        / "runtime"
        / "dsh"
        / "node_modules"
        / "@deepseek-ai"
        / "dsh"
        / "lib"
        / "bin.js"
    )
)
NODE = os.environ.get("NODE_BIN") or shutil.which("node") or ""
CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or ""
CODEX = os.environ.get("CODEX_BIN") or shutil.which("codex") or ""

HARNESS_ORDER = ["studyui", "native_dsh", "claude_code", "codex", "matos"]
PRIMARY_HARNESSES = ["studyui", "native_dsh", "claude_code", "codex"]

SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


# ---------------------------------------------------------------------------
# Environment, credentials and model verification


def load_api_key() -> str:
    """Read the DeepSeek key from the environment or the DSH credential file."""
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return env_key
    credential_file = Path.home() / ".dsh" / ".credentials.yaml"
    if not credential_file.is_file():
        return ""
    text = credential_file.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^\s*DEEPSEEK_API_KEY:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1).strip().strip("'\"") if match else ""


def redacted_env() -> dict[str, str]:
    """A process environment with secrets removed; callers add what they need."""
    keep = {
        "PATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "OS",
        "LANG",
        "LC_ALL",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "CODEX_HOME",
        "DSH_HOME",
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if key in keep and not any(marker in key.upper() for marker in SECRET_MARKERS)
    }
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def deliverable_env(key: str) -> dict[str, str]:
    env = redacted_env()
    if key:
        env["DEEPSEEK_API_KEY"] = key
    return env


def probe_model(key: str) -> dict:
    """Verify the pinned model route without ever printing the key."""
    if not key:
        return {"available": False, "reason": "no DeepSeek API key in env or ~/.dsh/.credentials.yaml"}
    result: dict = {"available": False, "endpoint": BASE_URL, "model": MODEL}
    headers = {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StudyUI-harness-bench/1.0",
    }
    try:
        request = Request(BASE_URL + "/models", headers=headers)
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        ids = [row.get("id") for row in payload.get("data", []) if isinstance(row, dict)]
        result.update(status="ok", model_ids=ids, model_present=MODEL in ids)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        result.update(status="error", error=f"{type(exc).__name__}: {exc}")
        return result
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 32,
        "stream": False,
    }
    try:
        request = Request(
            MODEL_PROBE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started = time.perf_counter()
        with urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
        elapsed = round(time.perf_counter() - started, 2)
        message = (body.get("choices") or [{}])[0].get("message") or {}
        result.update(
            available=True,
            chat_status="ok",
            chat_latency_s=elapsed,
            returned_model=body.get("model"),
            finish_reason=(body.get("choices") or [{}])[0].get("finish_reason"),
            response_present=bool(message.get("content") or message.get("reasoning_content")),
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        result.update(status="error", error=f"{type(exc).__name__}: {exc}")
    return result


def detect_codex_model() -> dict:
    path = Path.home() / ".codex" / "config.toml"
    info: dict = {"config": str(path), "exists": path.is_file()}
    if not path.is_file():
        return info
    text = path.read_text(encoding="utf-8", errors="replace")
    model = re.search(r'^\s*model\s*=\s*"([^"]+)"', text, re.MULTILINE)
    provider = re.search(r'^\s*model_provider\s*=\s*"([^"]+)"', text, re.MULTILINE)
    info.update(
        model=model.group(1) if model else "",
        provider=provider.group(1) if provider else "",
    )
    return info


def git_state() -> dict:
    def run(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", "-C", str(ROOT), *args],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(run("status", "--porcelain")),
    }


@dataclass
class HarnessInfo:
    name: str
    available: bool
    detail: str
    reason: str = ""
    command: str = ""
    model: str = MODEL
    extras: dict = field(default_factory=dict)


def detect_harnesses(key: str, studyui_source: Path) -> list[HarnessInfo]:
    infos: list[HarnessInfo] = []
    source_ok = (studyui_source / "materials_quality").is_dir()
    infos.append(
        HarnessInfo(
            name="studyui",
            available=bool(source_ok and key),
            detail=f"StudyUI Python agent harness; source={studyui_source}",
            reason=""
            if source_ok and key
            else ("StudyUI source not found" if not source_ok else "no DeepSeek API key"),
            command=f"{sys.executable} (in-process agent)",
            extras={"source": str(studyui_source)},
        )
    )
    dsh_ok = bool(DEFAULT_DSH_BIN.is_file() and NODE and key)
    infos.append(
        HarnessInfo(
            name="native_dsh",
            available=dsh_ok,
            detail="DeepSeek Harness headless profile; no StudyUI tools/prompts/MCP",
            reason=""
            if dsh_ok
            else (
                "DSH CLI bundle not found"
                if not DEFAULT_DSH_BIN.is_file()
                else "Node.js not found"
                if not NODE
                else "no DeepSeek API key"
            ),
            command=f"{NODE} {DEFAULT_DSH_BIN} headless",
            extras={"dsh_bin": str(DEFAULT_DSH_BIN), "node": NODE},
        )
    )
    claude_ok = bool(CLAUDE and key)
    infos.append(
        HarnessInfo(
            name="claude_code",
            available=claude_ok,
            detail="Claude Code CLI (--bare) pointed at the DeepSeek Anthropic-compatible route",
            reason="" if claude_ok else ("claude CLI not found" if not CLAUDE else "no DeepSeek API key"),
            command=f"{CLAUDE} -p ... --bare --model {MODEL}",
            extras={"bin": CLAUDE},
        )
    )
    codex_info = detect_codex_model()
    codex_model = str(codex_info.get("model") or "")
    codex_ok = bool(CODEX and codex_info.get("exists") and "deepseek" in codex_model.casefold())
    infos.append(
        HarnessInfo(
            name="codex",
            available=codex_ok,
            detail="Codex CLI using its installed DeepSeek V4.1 Flash provider configuration",
            reason=""
            if codex_ok
            else (
                "codex CLI not found"
                if not CODEX
                else "no ~/.codex/config.toml"
                if not codex_info.get("exists")
                else "installed Codex model is not DeepSeek v4.1 flash"
            ),
            command=f"{CODEX} exec --json --ephemeral -m {codex_model}",
            model=codex_model or MODEL,
            extras={"bin": CODEX, "config": codex_info},
        )
    )
    matos_repo = os.environ.get("MATOS_REPO", "").strip()
    matos_bin = shutil.which("matos") or ""
    infos.append(
        HarnessInfo(
            name="matos",
            available=False,
            detail=(
                "MatOS source was cloned read-only for methodology only and was not "
                "installed or executed."
            ),
            reason=(
                "MatOS is not installed/authenticated on this machine; running it would require "
                "scripts/matos-setup.sh (bun bundle), its DSH runtime, public MatTools/SciAgentGym/"
                "ResearchClawBench data, and its own credentials. The task forbids installing/"
                "executing the cloned MatOS code."
            ),
            command=matos_bin or (matos_repo or "not installed"),
            extras={"repo": matos_repo, "bin": matos_bin},
        )
    )
    return infos


# ---------------------------------------------------------------------------
# Tasks, workspaces and deterministic scoring


def load_tasks(selected: list[str] | None = None) -> list[dict]:
    payload = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    tasks = payload["tasks"]
    if selected:
        wanted = set(selected)
        tasks = [task for task in tasks if task["id"] in wanted]
        missing = wanted - {task["id"] for task in tasks}
        if missing:
            raise SystemExit(f"unknown task ids: {', '.join(sorted(missing))}")
    return tasks


def render_prompt(task: dict, workspace: Path) -> str:
    def file_replacement(match: re.Match) -> str:
        return str((workspace / match.group(1)).resolve())

    prompt = task["prompt"].replace("{workspace}", str(workspace.resolve()))
    return re.sub(r"\{file:([^}]+)\}", file_replacement, prompt)


def prepare_workspace(task: dict, workspace: Path) -> None:
    source = FIXTURES / "fixtures" / task["fixture"]
    if not source.is_dir():
        raise SystemExit(f"fixture directory missing: {source}")
    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(source, workspace)


def extract_answer(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        return {}
    decoder = json.JSONDecoder()
    best: dict = {}
    index = 0
    while index < len(text):
        if text[index] != "{":
            index += 1
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(value, dict):
            best = value
        index += max(1, end)
    return best


def numeric_value(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        candidate = value.strip().replace(",", "")
        try:
            return float(candidate)
        except ValueError:
            return None
    return None


def run_check(check: dict, answer: dict) -> tuple[bool, str]:
    kind = check.get("type")
    key = check.get("key", "")
    if key not in answer:
        return False, f"missing:{key}"
    value = answer[key]
    if kind in {"number", "integer"}:
        number = numeric_value(value)
        if number is None:
            return False, f"not_numeric:{key}"
        expected = float(check["expected"])
        if kind == "integer":
            if not number.is_integer():
                return False, f"not_integer:{key}"
            return (int(number) == int(expected)), ("" if int(number) == int(expected) else f"wrong:{key}")
        tolerance = check.get("abs")
        if tolerance is None:
            tolerance = abs(expected) * float(check.get("rel", 0.0))
        passed = abs(number - expected) <= float(tolerance)
        return passed, "" if passed else f"wrong:{key}"
    if kind == "string":
        text = str(value).strip()
        allowed = check.get("one_of")
        if allowed:
            passed = text.casefold() in {str(item).casefold() for item in allowed}
        else:
            passed = text.casefold() == str(check.get("equals", "")).casefold()
        return passed, "" if passed else f"wrong:{key}"
    return False, f"unknown_check_type:{kind}"


def score_run(task: dict, result: dict) -> dict:
    final_text = str(result.get("final_text") or "")
    answer = extract_answer(final_text)
    tool_calls = result.get("tool_calls") or []
    tool_text = str(result.get("tool_text") or "")
    transcript = tool_text + "\n" + final_text

    failures: list[str] = []
    if result.get("status") != "ok":
        failures.append(f"harness_{result.get('status') or 'unknown'}")
    if not final_text.strip():
        failures.append("no_final")
    if not answer:
        failures.append("no_json")
    tool_errors = sum(
        1
        for call in tool_calls
        if call.get("ok") is False or "执行异常" in str(call.get("summary") or "")
    )

    check_results = []
    for check in task.get("checks") or []:
        passed, failure = run_check(check, answer)
        check_results.append({"check": check, "passed": passed, "failure": failure})
        if failure:
            failures.append(failure)

    evidence_results = []
    for pattern in task.get("evidence") or []:
        passed = bool(re.search(pattern, final_text, re.IGNORECASE))
        evidence_results.append({"pattern": pattern, "passed": passed})
        if not passed:
            failures.append(f"evidence:{pattern}")

    tool_patterns = task.get("tool_evidence") or []
    tool_hits = [bool(re.search(pattern, transcript, re.IGNORECASE)) for pattern in tool_patterns]
    tool_evidence_ok = bool(tool_patterns) and all(tool_hits) and bool(tool_calls)
    if not tool_calls:
        failures.append("no_tool_call")
    elif tool_patterns and not all(tool_hits):
        failures.append("tool_evidence")

    numeric_checks = [
        item
        for item in check_results
        if item["check"].get("type") in {"number", "integer", "string"}
    ]
    numerical = (
        sum(1 for item in numeric_checks if item["passed"]) / len(numeric_checks) if numeric_checks else 1.0
    )
    evidence_score = (
        sum(1 for item in evidence_results if item["passed"]) / len(evidence_results)
        if evidence_results
        else 1.0
    )
    all_checks = all(item["passed"] for item in check_results) and all(
        item["passed"] for item in evidence_results
    )
    success = bool(
        all_checks
        and result.get("status") == "ok"
        and final_text.strip()
        and answer
    )
    return {
        "task_success": success,
        "task_success_value": 1.0 if success else 0.0,
        "numerical_correctness": round(numerical, 4),
        "evidence_correctness": round(evidence_score, 4),
        "tool_use_correct": tool_evidence_ok,
        "tool_use_value": 1.0 if tool_evidence_ok else 0.0,
        "tool_error_count": tool_errors,
        "checks": check_results,
        "evidence": evidence_results,
        "tool_evidence_patterns": tool_patterns,
        "tool_evidence_hits": tool_hits,
        "answer": answer,
        "failure_modes": sorted(set(failures)),
        "failure_primary": failures[0] if failures else "",
    }


# ---------------------------------------------------------------------------
# Child harness runners


def tail_text(text: str, limit: int = 6000) -> str:
    text = str(text or "")
    return text[-limit:] if len(text) > limit else text


def parse_json_lines(text: str):
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def run_studyui(request: dict, result_dir: Path, key: str) -> dict:
    source = Path(request.get("studyui_source") or (MQ / "src")).resolve()
    workspace = Path(request["workspace"]).resolve()
    sys.path.insert(0, str(source))
    import materials_quality

    loaded_source = Path(materials_quality.__file__).resolve()
    expected_root = (source / "materials_quality").resolve()
    if not loaded_source.is_relative_to(expected_root):
        raise RuntimeError(
            f"StudyUI source did not take precedence: loaded {loaded_source}, expected under "
            f"{expected_root}. Check --studyui-source."
        )
    from materials_quality.agent.file_workflow_client import FileWorkflowClient
    from materials_quality.agent.harness import StudyUIAgent
    from materials_quality.agent.model import ChatModel
    from materials_quality.agent.store import SessionStore

    runtime = result_dir / "studyui-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    catalog = {
        "projects": [
            {
                "id": "bench",
                "name": "Harness benchmark",
                "workspace_id": "bench-workspace",
                "local_directories": [str(workspace)],
            }
        ],
        "workspaces": [
            {"id": "bench-workspace", "name": "benchmark", "path": str(workspace)}
        ],
        "variables": [],
    }
    (runtime / "workspace.json").write_text(json.dumps(catalog), encoding="utf-8")
    workflows = workspace / "workflows"
    workflows.mkdir(exist_ok=True)
    components = source.parent / "components"
    canvas = FileWorkflowClient(workflows, components) if components.is_dir() else None
    store = SessionStore(
        runtime / "agent.sqlite3",
        workspace_file=runtime / "workspace.json",
        workflow_root=workflows,
    )
    model = ChatModel(
        base_url=BASE_URL,
        model=MODEL,
        api_key=key,
        reasoning_effort="high",
        max_output_tokens=16384,
    )
    agent = StudyUIAgent(store, canvas=canvas, model=model)
    agent.permissions.set_preset("bench", "project_collaboration")
    session_id = agent.new_session(request["task_id"], project_id="bench")
    events: list[dict] = []
    started = time.perf_counter()
    try:
        response = agent.run_turn(session_id, request["prompt"], on_progress=events.append)
    except Exception as exc:  # Keep the failure visible instead of faking a result.
        return {
            "harness": "studyui",
            "task_id": request["task_id"],
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": tail_text(__import__("traceback").format_exc(), 8000),
            "final_text": "",
            "tool_calls": [],
            "tool_text": "",
            "turns": 0,
            "model_requests": 0,
            "usage": None,
            "latency_s": round(time.perf_counter() - started, 2),
            "model": MODEL,
        }
    latency = round(time.perf_counter() - started, 2)
    tool_steps = response.get("tool_steps") or []
    tool_calls = [
        {
            "name": step.get("name"),
            "args": step.get("arguments") or {},
            "summary": step.get("summary"),
            "ok": step.get("ok"),
        }
        for step in tool_steps
        if isinstance(step, dict)
    ]
    final_text = str(response.get("message") or "")
    tool_text = json.dumps(tool_calls, ensure_ascii=False) + "\n" + final_text
    performance = response.get("performance") or {}
    (result_dir / "studyui-result.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (result_dir / "studyui-events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return {
        "harness": "studyui",
        "task_id": request["task_id"],
        "status": "ok",
        "final_text": final_text,
        "tool_calls": tool_calls,
        "tool_text": tool_text,
        "turns": int(performance.get("request_count") or 0),
        "model_requests": int(performance.get("request_count") or 0),
        "usage": response.get("token_usage"),
        "task_status": response.get("task_status"),
        "latency_s": latency,
        "model": response.get("model") or MODEL,
        "session_id": session_id,
        "studyui_source_loaded": str(loaded_source),
    }


def run_native_dsh(request: dict, result_dir: Path, key: str) -> dict:
    workspace = Path(request["workspace"]).resolve()
    dsh_bin = Path(request.get("dsh_bin") or DEFAULT_DSH_BIN)
    node = request.get("node") or NODE
    if not (Path(node).is_file() or shutil.which(node)):
        raise RuntimeError("Node.js is not available for native DSH")
    if not dsh_bin.is_file():
        raise RuntimeError(f"DSH CLI bundle not found: {dsh_bin}")
    dsh_home = result_dir / "dsh-home"
    tmp = result_dir / "tmp"
    dsh_home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env = deliverable_env(key)
    env.update(
        DSH_HOME=str(dsh_home),
        DEEPSEEK_BASE_URL=ANTHROPIC_BASE_URL,
        DSH_TELEMETRY_DISABLED="1",
        TEMP=str(tmp),
        TMP=str(tmp),
        TMPDIR=str(tmp),
    )
    cmd = [
        node,
        str(dsh_bin),
        "headless",
        "--json",
        "--permission-mode",
        "workspace-write",
        "--approval-policy",
        "never",
        request["prompt"],
    ]
    started = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(request.get("timeout_s") or 600),
            check=False,
        )
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        code = 124
    latency = round(time.perf_counter() - started, 2)
    (result_dir / "dsh-stdout.jsonl").write_text(stdout or "", encoding="utf-8")
    (result_dir / "dsh-stderr.log").write_text(stderr or "", encoding="utf-8")
    events = list(parse_json_lines(stdout))
    text_parts: list[str] = []
    final_text = ""
    tool_calls: list[dict] = []
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    turns = 0
    steps = 0
    for event in events:
        kind = event.get("type")
        if kind == "status":
            phase = event.get("phase")
            if phase == "turn_start":
                turns += 1
            elif phase == "step_start":
                steps += 1
            elif phase == "step_end":
                row = event.get("usage") or {}
                for source_key, target_key in (
                    ("inputTokens", "input_tokens"),
                    ("outputTokens", "output_tokens"),
                    ("cacheReadTokens", "cache_read_tokens"),
                    ("cacheWriteTokens", "cache_write_tokens"),
                ):
                    with contextlib.suppress(TypeError, ValueError):
                        usage[target_key] += int(row.get(source_key) or 0)
        elif kind == "text":
            chunk = str(event.get("text") or "")
            if chunk:
                text_parts.append(chunk)
        elif kind == "tool_call":
            tool_calls.append(
                {"name": event.get("tool"), "args": event.get("input") or {}, "summary": "", "ok": None}
            )
        elif kind == "tool_result":
            if tool_calls:
                status_value = str(event.get("status") or "")
                tool_calls[-1]["summary"] = str(event.get("result") or "")[:2000]
                tool_calls[-1]["ok"] = status_value in {"completed", "success"}
        elif kind == "final":
            final_text = str(event.get("text") or "")
    if usage["input_tokens"] or usage["output_tokens"]:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    else:
        usage = None
    if not final_text:
        final_text = "".join(text_parts)
    tool_text = json.dumps(tool_calls, ensure_ascii=False) + "\n" + final_text
    status = "ok" if (code == 0 and final_text.strip()) else ("timeout" if timed_out else "error")
    error = ""
    if status != "ok":
        error = tail_text(stderr or stdout or f"exit code {code}", 4000)
    return {
        "harness": "native_dsh",
        "task_id": request["task_id"],
        "status": status,
        "error": error,
        "exit_code": code,
        "final_text": final_text,
        "tool_calls": tool_calls,
        "tool_text": tool_text,
        "turns": turns,
        "model_requests": steps,
        "usage": usage if (usage["input_tokens"] or usage["output_tokens"]) else None,
        "latency_s": latency,
        "model": MODEL,
    }


def run_claude_code(request: dict, result_dir: Path, key: str) -> dict:
    workspace = Path(request["workspace"]).resolve()
    claude = request.get("claude_bin") or CLAUDE
    if not claude:
        raise RuntimeError("claude CLI not found")
    config_dir = result_dir / "claude-home"
    tmp = result_dir / "tmp"
    config_dir.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env = deliverable_env(key)
    env.update(
        CLAUDE_CONFIG_DIR=str(config_dir),
        ANTHROPIC_API_KEY=key,
        ANTHROPIC_AUTH_TOKEN=key,
        ANTHROPIC_BASE_URL=ANTHROPIC_BASE_URL,
        TEMP=str(tmp),
        TMP=str(tmp),
    )
    cmd = [
        claude,
        "-p",
        request["prompt"],
        "--bare",
        "--dangerously-skip-permissions",
        "--disable-slash-commands",
        "--model",
        MODEL,
        "--effort",
        "high",
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        str(int(request.get("max_turns") or 12)),
    ]
    started = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(request.get("timeout_s") or 600),
            check=False,
        )
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        code = 124
    latency = round(time.perf_counter() - started, 2)
    (result_dir / "claude-stdout.jsonl").write_text(stdout or "", encoding="utf-8")
    (result_dir / "claude-stderr.log").write_text(stderr or "", encoding="utf-8")
    events = list(parse_json_lines(stdout))
    text_parts: list[str] = []
    final_text = ""
    tool_calls: list[dict] = []
    turns = 0
    usage = None
    result_event = None
    for event in events:
        kind = event.get("type")
        if kind == "assistant":
            turns += 1
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text") or ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "name": block.get("name"),
                            "args": block.get("input") or {},
                            "summary": "",
                            "ok": None,
                        }
                    )
        elif kind == "user":
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and tool_calls:
                    content = block.get("content")
                    tool_calls[-1]["summary"] = str(content)[:2000]
                    tool_calls[-1]["ok"] = not bool(block.get("is_error"))
        elif kind == "result":
            result_event = event
            final_text = str(event.get("result") or "")
            turns = int(event.get("num_turns") or turns)
            usage = event.get("usage")
    if not final_text:
        final_text = "".join(text_parts)
    mapped_usage = None
    if isinstance(usage, dict):
        mapped_usage = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_read_tokens": usage.get("cache_read_input_tokens"),
        }
    tool_text = json.dumps(tool_calls, ensure_ascii=False) + "\n" + final_text
    is_error = bool(result_event.get("is_error")) if isinstance(result_event, dict) else False
    status = "ok" if (code == 0 and final_text.strip() and not is_error) else (
        "timeout" if timed_out else "error"
    )
    return {
        "harness": "claude_code",
        "task_id": request["task_id"],
        "status": status,
        "error": "" if status == "ok" else tail_text(stderr or stdout or f"exit code {code}", 4000),
        "exit_code": code,
        "final_text": final_text,
        "tool_calls": tool_calls,
        "tool_text": tool_text,
        "turns": turns,
        "model_requests": turns,
        "usage": mapped_usage,
        "latency_s": latency,
        "model": MODEL,
        "cost_usd": (result_event or {}).get("total_cost_usd") if isinstance(result_event, dict) else None,
    }


def run_codex(request: dict, result_dir: Path, key: str) -> dict:
    workspace = Path(request["workspace"]).resolve()
    codex = request.get("codex_bin") or CODEX
    if not codex:
        raise RuntimeError("codex CLI not found")
    model = request.get("codex_model") or MODEL
    tmp = result_dir / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = deliverable_env(key)
    env.update(TEMP=str(tmp), TMP=str(tmp))
    cmd = [
        codex,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ephemeral",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        str(workspace),
        "-m",
        model,
        request["prompt"],
    ]
    started = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(request.get("timeout_s") or 600),
            check=False,
        )
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
        code = 124
    latency = round(time.perf_counter() - started, 2)
    (result_dir / "codex-stdout.jsonl").write_text(stdout or "", encoding="utf-8")
    (result_dir / "codex-stderr.log").write_text(stderr or "", encoding="utf-8")
    events = list(parse_json_lines(stdout))
    final_text = ""
    tool_calls: list[dict] = []
    turns = 0
    usage = None
    for event in events:
        kind = event.get("type")
        if kind == "turn.started":
            turns += 1
        elif kind == "item.completed":
            item = event.get("item") or {}
            item_type = item.get("type")
            if item_type == "agent_message":
                final_text = str(item.get("text") or "")
            elif item_type in {"command_execution", "tool_call", "mcp_tool_call"}:
                exit_code = item.get("exit_code")
                tool_calls.append(
                    {
                        "name": item.get("type"),
                        "args": item.get("command") or item.get("arguments") or {},
                        "summary": str(item.get("aggregated_output") or item.get("output") or "")[:2000],
                        "ok": None if exit_code is None else exit_code == 0,
                    }
                )
        elif kind == "turn.completed":
            row = event.get("usage") or {}
            usage = {
                "input_tokens": row.get("input_tokens"),
                "output_tokens": row.get("output_tokens"),
                "cache_read_tokens": row.get("cached_input_tokens"),
                "reasoning_tokens": row.get("reasoning_output_tokens"),
            }
    tool_text = json.dumps(tool_calls, ensure_ascii=False) + "\n" + final_text
    status = "ok" if (code == 0 and final_text.strip()) else ("timeout" if timed_out else "error")
    return {
        "harness": "codex",
        "task_id": request["task_id"],
        "status": status,
        "error": "" if status == "ok" else tail_text(stderr or stdout or f"exit code {code}", 4000),
        "exit_code": code,
        "final_text": final_text,
        "tool_calls": tool_calls,
        "tool_text": tool_text,
        "turns": turns,
        "model_requests": turns,
        "usage": usage,
        "latency_s": latency,
        "model": model,
    }


def run_matos(request: dict, result_dir: Path, key: str) -> dict:
    raise RuntimeError(
        "MatOS is not installed or authenticated on this machine; the benchmark never executes "
        "the read-only MatOS source clone."
    )


RUNNERS = {
    "studyui": run_studyui,
    "native_dsh": run_native_dsh,
    "claude_code": run_claude_code,
    "codex": run_codex,
    "matos": run_matos,
}


def cmd_run_one(request_path: Path, result_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result_dir = result_path.parent
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    runner = RUNNERS.get(request["harness"])
    if runner is None:
        result = {
            "harness": request.get("harness"),
            "task_id": request.get("task_id"),
            "status": "error",
            "error": f"unknown harness: {request.get('harness')}",
            "final_text": "",
            "tool_calls": [],
            "tool_text": "",
        }
    else:
        try:
            result = runner(request, result_dir, key)
        except Exception as exc:
            result = {
                "harness": request["harness"],
                "task_id": request.get("task_id"),
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": tail_text(__import__("traceback").format_exc(), 8000),
                "final_text": "",
                "tool_calls": [],
                "tool_text": "",
                "turns": 0,
                "model_requests": 0,
                "usage": None,
                "latency_s": 0.0,
                "model": request.get("model") or MODEL,
            }
    result.setdefault("harness", request.get("harness"))
    result.setdefault("task_id", request.get("task_id"))
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# Aggregation and reports


def aggregate(runs: list[dict]) -> dict:
    def summarize(group: list[dict]) -> dict:
        count = len(group)
        if not count:
            return {}
        failures = Counter()
        for run in group:
            failures.update(run["score"].get("failure_modes") or [])
        latencies = [
            run["result"].get("latency_s")
            for run in group
            if run["result"].get("latency_s") is not None
        ]
        turns = [run["result"].get("turns") for run in group if run["result"].get("turns") is not None]
        calls = [len(run["result"].get("tool_calls") or []) for run in group]
        input_tokens = [
            (run["result"].get("usage") or {}).get("input_tokens")
            for run in group
            if (run["result"].get("usage") or {}).get("input_tokens") is not None
        ]
        output_tokens = [
            (run["result"].get("usage") or {}).get("output_tokens")
            for run in group
            if (run["result"].get("usage") or {}).get("output_tokens") is not None
        ]

        def mean(values):
            return round(sum(values) / len(values), 2) if values else None

        return {
            "n": count,
            "success_rate": round(sum(run["score"]["task_success_value"] for run in group) / count, 4),
            "numerical_correctness": round(
                sum(run["score"]["numerical_correctness"] for run in group) / count, 4
            ),
            "evidence_correctness": round(
                sum(run["score"]["evidence_correctness"] for run in group) / count, 4
            ),
            "tool_use_rate": round(sum(run["score"]["tool_use_value"] for run in group) / count, 4),
            "mean_turns": mean(turns),
            "mean_tool_calls": mean(calls),
            "mean_tool_errors": mean(
                [run["score"].get("tool_error_count", 0) for run in group]
            ),
            "tool_error_runs": sum(
                1 for run in group if run["score"].get("tool_error_count", 0)
            ),
            "mean_latency_s": mean(latencies),
            "mean_input_tokens": mean(input_tokens),
            "mean_output_tokens": mean(output_tokens),
            "failure_modes": dict(failures.most_common()),
        }

    by_harness: dict[str, dict] = {}
    by_harness_task: dict[str, dict] = {}
    for harness in sorted({run["harness"] for run in runs}):
        group = [run for run in runs if run["harness"] == harness]
        by_harness[harness] = summarize(group)
        by_harness_task[harness] = {}
        for task_id in sorted({run["task_id"] for run in group}):
            by_harness_task[harness][task_id] = summarize(
                [run for run in group if run["task_id"] == task_id]
            )
    return {"overall": by_harness, "by_task": by_harness_task}


def _fmt(value, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def write_outputs(output: Path, runs: list[dict], manifest: dict, harnesses: list[HarnessInfo]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "runs.jsonl").write_text(
        "\n".join(json.dumps(run, ensure_ascii=False, default=str) for run in runs) + "\n",
        encoding="utf-8",
    )
    summary = aggregate(runs)
    payload = {
        **manifest,
        "harnesses": [asdict(info) for info in harnesses],
        "summary": summary,
        "runs": [
            {
                "harness": run["harness"],
                "task_id": run["task_id"],
                "repeat": run["repeat"],
                "score": run["score"],
                "result": {
                    key: run["result"].get(key)
                    for key in (
                        "status",
                        "error",
                        "turns",
                        "model_requests",
                        "usage",
                        "latency_s",
                        "model",
                    )
                },
                "paths": run["paths"],
            }
            for run in runs
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "harness",
                "task",
                "n",
                "success_rate",
                "numerical_correctness",
                "evidence_correctness",
                "tool_use_rate",
                "mean_turns",
                "mean_tool_calls",
                "mean_tool_errors",
                "mean_latency_s",
                "failure_modes",
            ]
        )
        for harness, tasks in summary["by_task"].items():
            for task_id, row in tasks.items():
                writer.writerow(
                    [
                        harness,
                        task_id,
                        row["n"],
                        row["success_rate"],
                        row["numerical_correctness"],
                        row["evidence_correctness"],
                        row["tool_use_rate"],
                        row["mean_turns"],
                        row["mean_tool_calls"],
                        row["mean_tool_errors"],
                        row["mean_latency_s"],
                        "; ".join(f"{k}={v}" for k, v in row["failure_modes"].items()),
                    ]
                )

    lines: list[str] = []
    lines.append("# StudyUI harness benchmark")
    lines.append("")
    lines.append(f"- Run id: `{manifest.get('run_id')}`")
    lines.append(f"- Timestamp: {manifest.get('timestamp')}")
    git = manifest.get("git", {})
    lines.append(
        f"- Git: `{str(git.get('commit', ''))[:12]}` on `{git.get('branch')}` "
        f"(dirty={git.get('dirty')})"
    )
    lines.append(f"- Model: **{MODEL_LABEL}** at `{BASE_URL}`")
    model_probe = manifest.get("model_probe") or {}
    lines.append(
        f"- Model probe: available={model_probe.get('available')} "
        f"model_ids={model_probe.get('model_ids')} chat_latency_s={model_probe.get('chat_latency_s')}"
    )
    lines.append(
        f"- Repeats: {manifest.get('repeats')} per task; fresh workspace and harness state per run"
    )
    lines.append(f"- Raw logs: `{output}`")
    lines.append("")
    lines.append("## Harness availability")
    lines.append("")
    lines.append("| Harness | Available | Detail | Reason if unavailable |")
    lines.append("|---|---|---|---|")
    for info in harnesses:
        lines.append(
            f"| {info.name} | {'yes' if info.available else 'no'} | {info.detail} | {info.reason or ''} |"
        )
    lines.append("")
    lines.append("## Overall")
    lines.append("")
    lines.append(
        "| Harness | Runs | Success | Numerical | Evidence | Tool use | "
        "Mean turns | Mean tool calls | Mean tool errors | Mean latency (s) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for harness in HARNESS_ORDER:
        row = summary["overall"].get(harness)
        if not row:
            continue
        lines.append(
            f"| {harness} | {row['n']} | {_fmt(row['success_rate'])} | "
            f"{_fmt(row['numerical_correctness'])} | {_fmt(row['evidence_correctness'])} | "
            f"{_fmt(row['tool_use_rate'])} | {_fmt(row['mean_turns'])} | "
            f"{_fmt(row['mean_tool_calls'])} | {_fmt(row['mean_tool_errors'])} | "
            f"{_fmt(row['mean_latency_s'])} |"
        )
    lines.append("")
    lines.append("## Per task")
    lines.append("")
    harnesses_run = [name for name in HARNESS_ORDER if name in summary["by_task"]]
    lines.append("| Task | " + " | ".join(harnesses_run) + " |")
    lines.append("|---|" + "---|" * len(harnesses_run))
    task_ids = sorted({run["task_id"] for run in runs})
    for task_id in task_ids:
        cells = []
        for harness in harnesses_run:
            row = summary["by_task"].get(harness, {}).get(task_id)
            cells.append("-" if not row else f"{row['success_rate']:.2f} ({row['n']})")
        lines.append(f"| {task_id} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("Cells show task success rate and run count.")
    lines.append("")
    lines.append("## Failure modes")
    lines.append("")
    for harness in HARNESS_ORDER:
        row = summary["overall"].get(harness)
        if not row:
            continue
        modes = row.get("failure_modes") or {}
        lines.append(f"- **{harness}**: " + (", ".join(f"`{k}`={v}" for k, v in modes.items()) or "none"))
    lines.append("")
    if "studyui" in summary["overall"] and "native_dsh" in summary["overall"]:
        study = summary["overall"]["studyui"]
        native = summary["overall"]["native_dsh"]
        lines.append("## StudyUI vs native DSH")
        lines.append("")
        lines.append(
            f"- Success: StudyUI {study['success_rate']:.3f} vs native DSH {native['success_rate']:.3f} "
            f"(delta {study['success_rate'] - native['success_rate']:+.3f})"
        )
        lines.append(
            f"- Tool use: StudyUI {study['tool_use_rate']:.3f} vs native DSH {native['tool_use_rate']:.3f}"
        )
        lines.append(
            f"- Mean turns: StudyUI {_fmt(study['mean_turns'])} vs native DSH {_fmt(native['mean_turns'])}"
        )
        lines.append(
            f"- Mean latency: StudyUI {_fmt(study['mean_latency_s'])} s vs native DSH "
            f"{_fmt(native['mean_latency_s'])} s"
        )
        lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append(
        "Tasks are fixed synthetic materials-science tasks derived from MatOS's published benchmark "
        "profile and task-pitfall note. Each task asks for one strict JSON answer. Scoring checks exact "
        "numeric/integer values within declared tolerances, required evidence terms, and a transcript "
        "tool-use regex. No model judge is used. Every repetition gets a fresh workspace and fresh "
        "harness state. StudyUI runs its own Python agent harness; native DSH runs the installed "
        "headless profile with no StudyUI tools, prompts or MCP server; Claude Code runs with `--bare` "
        "against DeepSeek's Anthropic-compatible route; Codex runs its installed DeepSeek V4.1 Flash "
        "profile. MatOS is never installed or executed."
    )
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "aggregate.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Commands


def cmd_probe(args: argparse.Namespace) -> int:
    key = load_api_key()
    studyui_source = Path(args.studyui_source).resolve()
    infos = detect_harnesses(key, studyui_source)
    probe = probe_model(key) if not args.skip_model_probe else {"available": None, "skipped": True}
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "git": git_state(),
        "model": MODEL,
        "model_label": MODEL_LABEL,
        "base_url": BASE_URL,
        "model_probe": probe,
        "harnesses": [asdict(info) for info in infos],
        "credentials": {
            "deepseek_key_present": bool(key),
            "source": "DEEPSEEK_API_KEY or ~/.dsh/.credentials.yaml",
        },
    }
    output = Path(args.output).resolve() if args.output else DEFAULT_OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    (output / "probe.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    key = load_api_key()
    if not key and any(name in PRIMARY_HARNESSES for name in args.harnesses):
        raise SystemExit(
            "No DeepSeek API key found (DEEPSEEK_API_KEY nor ~/.dsh/.credentials.yaml). "
            "The deterministic scoring/fixtures can still be inspected, but no harness can run."
        )
    studyui_source = Path(args.studyui_source).resolve()
    infos = {info.name: info for info in detect_harnesses(key, studyui_source)}
    requested = [name.strip() for name in args.harnesses.split(",") if name.strip()]
    unknown = [name for name in requested if name not in RUNNERS]
    if unknown:
        raise SystemExit(f"unknown harness(es): {', '.join(unknown)}")
    selected_infos = [infos[name] for name in requested]
    runnable = [info for info in selected_infos if info.available]
    skipped = [info for info in selected_infos if not info.available]
    if not runnable:
        print(
            json.dumps(
                {"error": "no requested harness is available", "skipped": [asdict(i) for i in skipped]},
                indent=2,
            )
        )
        return 2
    selected_tasks = [item.strip() for item in args.tasks.split(",") if item.strip()] if args.tasks else None
    tasks = load_tasks(selected_tasks)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(args.output).resolve() if args.output else DEFAULT_OUTPUT / f"run-{timestamp}"
    output.mkdir(parents=True, exist_ok=True)
    model_probe = probe_model(key)
    manifest = {
        "run_id": output.name,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": git_state(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "model": MODEL,
        "model_label": MODEL_LABEL,
        "base_url": BASE_URL,
        "model_probe": model_probe,
        "repeats": args.repeats,
        "tasks": [task["id"] for task in tasks],
        "harnesses_requested": requested,
        "harnesses_run": [info.name for info in runnable],
        "harnesses_skipped": [asdict(info) for info in skipped],
        "studyui_source": str(studyui_source),
        "max_turns": args.max_turns,
    }
    if not model_probe.get("available"):
        manifest["model_probe_note"] = (
            "The pinned model route did not answer a tiny probe. Harness runs are still attempted, "
            "but their failures must be treated as quota/route failures, not benchmark results."
        )
    print(
        f"run_id={output.name} model={MODEL} repeats={args.repeats} "
        f"harnesses={','.join(info.name for info in runnable)}"
        + (f" skipped={','.join(info.name for info in skipped)}" if skipped else "")
    )
    runs: list[dict] = []
    total = len(tasks) * args.repeats * len(runnable)
    completed = 0
    for task in tasks:
        for repeat in range(1, args.repeats + 1):
            for info in runnable:
                completed += 1
                run_dir = output / "runs" / info.name / task["id"] / f"rep-{repeat}"
                run_dir.mkdir(parents=True, exist_ok=True)
                workspace = run_dir / "workspace"
                prepare_workspace(task, workspace)
                prompt = render_prompt(task, workspace)
                request = {
                    "harness": info.name,
                    "task_id": task["id"],
                    "prompt": prompt,
                    "workspace": str(workspace),
                    "timeout_s": int(task.get("timeout_s") or 600),
                    "max_turns": args.max_turns,
                    "model": MODEL,
                    "studyui_source": str(studyui_source),
                    "dsh_bin": str(DEFAULT_DSH_BIN),
                    "node": NODE,
                    "claude_bin": CLAUDE,
                    "codex_bin": CODEX,
                    "codex_model": info.model,
                }
                request_path = run_dir / "request.json"
                request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
                result_path = run_dir / "result.json"
                child_env = deliverable_env(key)
                started = time.perf_counter()
                status = "ok"
                error = ""
                try:
                    proc = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "run-one",
                            str(request_path),
                            "--result",
                            str(result_path),
                        ],
                        cwd=str(ROOT),
                        env=child_env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=float(request["timeout_s"]) + 120,
                        check=False,
                    )
                    if proc.stdout:
                        (run_dir / "runner-stdout.log").write_text(proc.stdout, encoding="utf-8")
                    if proc.stderr:
                        (run_dir / "runner-stderr.log").write_text(proc.stderr, encoding="utf-8")
                    if proc.returncode != 0:
                        status = "error"
                        error = tail_text((proc.stderr or "") + "\n" + (proc.stdout or ""), 4000)
                except subprocess.TimeoutExpired:
                    status = "timeout"
                    error = "parent subprocess timeout"
                parent_latency = round(time.perf_counter() - started, 2)
                if result_path.is_file():
                    with contextlib.suppress(json.JSONDecodeError, OSError):
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                else:
                    result = {
                        "harness": info.name,
                        "task_id": task["id"],
                        "status": status,
                        "error": error,
                        "final_text": "",
                        "tool_calls": [],
                        "tool_text": "",
                        "turns": 0,
                        "model_requests": 0,
                        "usage": None,
                        "latency_s": parent_latency,
                        "model": info.model,
                    }
                result.setdefault("latency_s", parent_latency)
                result.setdefault("status", status)
                if result.get("status") == "ok" and status != "ok":
                    result["status"] = status
                score = score_run(task, result)
                score_path = run_dir / "score.json"
                score_path.write_text(
                    json.dumps(score, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
                )
                runs.append(
                    {
                        "harness": info.name,
                        "task_id": task["id"],
                        "repeat": repeat,
                        "result": result,
                        "score": score,
                        "paths": {
                            "run_dir": str(run_dir),
                            "result": str(result_path),
                            "score": str(score_path),
                        },
                    }
                )
                verdict = "PASS" if score["task_success"] else "FAIL"
                print(
                    f"[{completed}/{total}] {info.name:10s} {task['id']:28s} rep-{repeat} "
                    f"{verdict} num={score['numerical_correctness']:.2f} "
                    f"tool={int(score['tool_use_correct'])} {result.get('latency_s')}s "
                    f"{','.join(score['failure_modes'][:2])}"
                )
    write_outputs(output, runs, manifest, selected_infos)
    summary = aggregate(runs)
    print()
    print(f"wrote {output / 'summary.md'}")
    for harness in HARNESS_ORDER:
        row = summary["overall"].get(harness)
        if row:
            print(
                f"{harness:12s} success={row['success_rate']:.3f} "
                f"numerical={row['numerical_correctness']:.3f} tool={row['tool_use_rate']:.3f} "
                f"turns={row['mean_turns']} latency={row['mean_latency_s']}s"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="Detect harnesses, credentials and the pinned model route")
    probe.add_argument("--studyui-source", default=str(MQ / "src"))
    probe.add_argument("--output", default=None)
    probe.add_argument("--skip-model-probe", action="store_true")

    run = sub.add_parser("run", help="Run the fixed benchmark")
    run.add_argument("--harnesses", default=",".join(PRIMARY_HARNESSES))
    run.add_argument("--tasks", default=None, help="Comma-separated task ids; default all")
    run.add_argument("--repeats", type=int, default=2)
    run.add_argument("--output", default=None)
    run.add_argument("--studyui-source", default=str(MQ / "src"))
    run.add_argument("--max-turns", type=int, default=12)
    run.add_argument("--seed", type=int, default=42, help="Recorded only; fixtures are deterministic")

    run_one = sub.add_parser("run-one", help=argparse.SUPPRESS)
    run_one.add_argument("request", type=Path)
    run_one.add_argument("--result", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "probe":
        return cmd_probe(args)
    if args.command == "run":
        return cmd_run(args)
    return cmd_run_one(args.request, args.result)


if __name__ == "__main__":
    raise SystemExit(main())
