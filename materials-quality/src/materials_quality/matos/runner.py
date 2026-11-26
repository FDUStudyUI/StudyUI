"""Runtime adapter for MatOS tool assets.

StudyUI does not vendor or reimplement MatOS executors. External MatOS tools are
invoked through the `matos assets run-tool <tool-ref> --input-file - --json`
contract (stdin JSON object, stdout JSON object). Builtin packs are not
executable through that CLI and are reported as unavailable instead of being
silently emulated.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import catalog

MAX_STDOUT_CHARS = 16 * 1024 * 1024
MAX_STDERR_CHARS = 4000
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_TIMEOUT_SECONDS = 3600.0
CLI_ENV_VARS = ("STUDYUI_MATOS_CLI", "MATOS_CLI")
WORKDIR_ENV_VARS = ("STUDYUI_MATOS_WORKDIR", "MATOS_WORKDIR")
BUILTIN_REASON = (
    "This MatOS asset is a builtin tool pack. It runs only inside the MatOS "
    "asset MCP server (`matos_asset`, e.g. mcp__matos_asset__<tool>), not "
    "through `matos assets run-tool`."
)


def install_hint() -> str:
    return str(catalog.catalog_source().get("install_hint") or "")


def find_matos_cli() -> str | None:
    """Locate the user-installed ``matos`` CLI without executing it."""
    for name in CLI_ENV_VARS:
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return str(candidate)
        resolved = shutil.which(raw)
        if resolved:
            return resolved
    home = os.environ.get("MATOS_HOME", "").strip()
    if home:
        for name in ("matos", "matos.cmd", "matos.bat", "matos.exe"):
            candidate = Path(home).expanduser() / "bin" / name
            if candidate.is_file():
                return str(candidate)
    return shutil.which("matos")


def runtime_status() -> dict[str, Any]:
    source = catalog.catalog_source()
    cli = find_matos_cli()
    return {
        "available": bool(cli),
        "status": "available" if cli else "unavailable",
        "cli": cli or "",
        "call_method": "matos assets run-tool <tool-ref> --input-file - --json",
        "install_hint": "" if cli else install_hint(),
        "repository": source.get("repository", ""),
        "license": source.get("license", ""),
        "checked_env": list(CLI_ENV_VARS),
    }


def tool_availability(tool: dict[str, Any]) -> dict[str, Any]:
    """Return live availability for one catalog record without running it."""
    if tool.get("kind") == "builtin-pack":
        return {
            "available": False,
            "status": "matos_runtime_only",
            "reason": BUILTIN_REASON,
            "install_hint": "",
            "call_method": tool.get("call_method", ""),
        }
    runtime = runtime_status()
    if not runtime["available"]:
        return {
            "available": False,
            "status": "unavailable",
            "reason": "The `matos` CLI was not found on PATH or in STUDYUI_MATOS_CLI/MATOS_CLI.",
            "install_hint": runtime["install_hint"],
            "call_method": tool.get("call_method", ""),
        }
    return {
        "available": True,
        "status": "available",
        "reason": (
            "`matos` CLI found. External solver/package availability is checked by "
            "the MatOS tool itself at run time."
        ),
        "install_hint": "",
        "call_method": tool.get("call_method", ""),
        "cli": runtime["cli"],
    }


def list_matos_tools(
    *,
    family: str | None = None,
    kind: str | None = None,
    tool_id: str | None = None,
    available_only: bool = False,
) -> dict[str, Any]:
    """List MatOS tools with live availability."""
    items: list[dict[str, Any]] = []
    for tool in catalog.list_tools(family=family, kind=kind, tool_id=tool_id):
        availability = tool_availability(tool)
        if available_only and not availability["available"]:
            continue
        items.append(
            {
                "id": tool["id"],
                "ref": tool["ref"],
                "name": tool["name"],
                "version": tool["version"],
                "description": tool["description"],
                "kind": tool["kind"],
                "family": tool["family"],
                "tags": tool["tags"],
                "call_method": tool["call_method"],
                "input_field_count": len((tool.get("input_schema") or {}).get("properties") or {}),
                "required_binaries": tool["required_binaries"],
                "probed_binaries": tool["probed_binaries"],
                "required_env": tool["required_env"],
                "network_required": tool["network_required"],
                "availability": availability,
            }
        )
    return {
        "count": len(items),
        "runtime": runtime_status(),
        "source": catalog.catalog_source(),
        "tools": items,
    }


def describe_matos_tool(tool: str) -> dict[str, Any]:
    """Return the full catalog record plus live availability."""
    record = catalog.resolve_tool(tool)
    return {**record, "availability": tool_availability(record)}


def _resolve_timeout(tool: dict[str, Any], timeout_seconds: Any) -> float:
    if timeout_seconds is not None:
        try:
            requested = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise catalog.MatOSInputError("timeout_seconds must be a positive number") from exc
        if requested <= 0:
            raise catalog.MatOSInputError("timeout_seconds must be a positive number")
        return min(requested, MAX_TIMEOUT_SECONDS)
    timeout_ms = tool.get("timeout_ms")
    seconds = float(timeout_ms) / 1000.0 if isinstance(timeout_ms, (int, float)) else DEFAULT_TIMEOUT_SECONDS
    return min(max(seconds + 5.0, 5.0), MAX_TIMEOUT_SECONDS)


def _workdir() -> str | None:
    for name in WORKDIR_ENV_VARS:
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_dir():
            return str(path)
    return None


def _tail(text: str | None, limit: int = MAX_STDERR_CHARS) -> str:
    value = str(text or "")
    return value[-limit:] if len(value) > limit else value


def _command(cli: str, ref: str) -> list[str]:
    command = [cli, "assets", "run-tool", ref, "--input-file", "-", "--json"]
    if os.name == "nt" and Path(cli).suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/c", *command]
    return command


def _execute(
    command: list[str],
    *,
    input_text: str,
    timeout: float,
    cwd: str | None,
) -> subprocess.CompletedProcess[str]:
    """Run the MatOS CLI. Kept isolated so tests can mock the process boundary."""
    return subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=cwd,
        check=False,
    )


def _unavailable(tool: dict[str, Any], availability: dict[str, Any]) -> dict[str, Any]:
    if availability["status"] == "matos_runtime_only":
        hint = availability.get("install_hint") or (
            "Use the MatOS asset MCP server (`matos_asset`) instead of `matos assets run-tool`."
        )
    else:
        hint = availability.get("install_hint") or install_hint()
    return {
        "ok": False,
        "status": availability["status"],
        "tool": tool["id"],
        "tool_ref": tool["ref"],
        "call_method": tool["call_method"],
        "error": availability.get("reason") or "MatOS tool is unavailable",
        "install_hint": hint,
        "required_binaries": tool["required_binaries"],
        "required_env": tool["required_env"],
        "availability": availability,
    }


def run_matos_tool(
    tool: str,
    input_value: Any = None,
    *,
    timeout_seconds: Any = None,
) -> dict[str, Any]:
    """Validate input and invoke one MatOS external tool through its CLI.

    Returns ``ok: False`` with an explicit ``status`` for unavailable tools,
    invalid input, process timeouts and tool failures. It never fabricates a
    successful result.
    """
    record = catalog.resolve_tool(tool)
    if input_value is None:
        input_value = {}
    catalog.validate_tool_input(record, input_value)

    availability = tool_availability(record)
    if not availability["available"]:
        return _unavailable(record, availability)

    timeout = _resolve_timeout(record, timeout_seconds)
    command = _command(str(availability["cli"]), record["ref"])
    try:
        completed = _execute(
            command,
            input_text=json.dumps(input_value, ensure_ascii=False),
            timeout=timeout,
            cwd=_workdir(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "ok": False,
            "status": "timeout",
            "tool": record["id"],
            "tool_ref": record["ref"],
            "call_method": record["call_method"],
            "timeout_seconds": timeout,
            "error": f"MatOS tool timed out after {timeout:g}s",
            "stdout": _tail(stdout),
            "stderr": _tail(stderr),
        }
    except OSError as exc:
        return {
            "ok": False,
            "status": "unavailable",
            "tool": record["id"],
            "tool_ref": record["ref"],
            "call_method": record["call_method"],
            "error": f"Could not execute the MatOS CLI: {exc}",
            "install_hint": install_hint(),
        }

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    parsed: dict[str, Any] | None = None
    try:
        candidate = json.loads(stdout.strip() or "{}")
        if isinstance(candidate, dict):
            parsed = candidate
    except json.JSONDecodeError:
        parsed = None

    if parsed is None:
        return {
            "ok": False,
            "status": "failed",
            "tool": record["id"],
            "tool_ref": record["ref"],
            "call_method": record["call_method"],
            "exit_code": completed.returncode,
            "error": "MatOS CLI did not return a JSON object on stdout.",
            "stdout": _tail(stdout),
            "stderr": _tail(stderr),
        }

    parsed_ok = parsed.get("ok")
    ok = completed.returncode == 0 and (parsed_ok is not False)
    if parsed.get("timedOut"):
        status = "timeout"
    elif ok:
        status = "completed"
    else:
        status = "failed"
    payload: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "tool": record["id"],
        "tool_ref": record["ref"],
        "call_method": record["call_method"],
        "exit_code": completed.returncode,
        "timed_out": bool(parsed.get("timedOut")),
        "stderr": _tail(parsed.get("stderr") or stderr),
    }
    if "result" in parsed:
        payload["result"] = parsed["result"]
    elif "stdout" in parsed:
        payload["stdout"] = _tail(parsed.get("stdout"), MAX_STDOUT_CHARS)
    if not ok:
        error = parsed.get("error")
        if not error and isinstance(parsed.get("result"), dict):
            error = parsed["result"].get("error")
        payload["error"] = error or _tail(stderr) or "MatOS tool reported failure."
    return payload
