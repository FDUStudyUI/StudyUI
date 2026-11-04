#!/usr/bin/env python3
"""Start a project-isolated Langflow demo; --check is strictly read-only."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "materials-quality"
FLOW_FILES = ("spectra.json", "mechanics.json", "contrast.json")


def venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements(package: Path, *, optional: bool = False) -> list[str]:
    """Read the project's dependency arrays without importing project dependencies."""
    text = (package / "pyproject.toml").read_text(encoding="utf-8")
    result = [] if optional else ["langflow-base==1.13.0", "lfx==1.13.0"]
    keys = ("instruments",) if optional else ("dependencies", "langflow", "science")
    for key in keys:
        match = re.search(
            r"^" + key + r"\s*=\s*(\[.*?\])", text, re.MULTILINE | re.DOTALL
        )
        if match is None:
            raise ValueError(
                f"Missing dependency array {key} in {package / 'pyproject.toml'}"
            )
        result.extend(ast.literal_eval(match.group(1)))
    return list(dict.fromkeys(result))


def probe_environment(python: Path, package: Path = PACKAGE) -> dict:
    # Metadata inspection avoids importing Langflow, creating config, or initializing its database.
    code = r"""
import importlib.metadata as metadata
import json, platform, sys
report = {"required_missing": [], "optional_missing": [], "python": platform.python_version()}
try:
    from packaging.requirements import Requirement
except ImportError:
    report["required_missing"] = ["packaging (dependency validation unavailable)"]
    print(json.dumps(report))
    sys.exit(0)
for group, values in json.loads(sys.stdin.read()).items():
    for value in values:
        requirement = Requirement(value)
        try:
            installed = metadata.version(requirement.name)
            if requirement.specifier and installed not in requirement.specifier:
                report[group].append(value + " (installed " + installed + ")")
        except metadata.PackageNotFoundError:
            report[group].append(value)
print(json.dumps(report))
"""
    result = subprocess.run(
        [str(python), "-I", "-X", "utf8", "-B", "-c", code],
        input=json.dumps(
            {
                "required_missing": requirements(package),
                "optional_missing": requirements(package, optional=True),
            }
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=True,
    )
    report = json.loads(result.stdout)
    if not report["python"].startswith("3.10."):
        report["required_missing"].insert(
            0, "Python 3.10 required (found " + report["python"] + ")"
        )
    return report


def runtime_environment(runtime: Path) -> dict[str, str]:
    # Discard inherited Langflow settings so another workspace's DB/.env cannot leak into this demo.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("LANGFLOW_", "PIP_"))
        and key.upper() not in {"PYTHONHOME", "PYTHONUSERBASE", "VIRTUAL_ENV"}
    }
    paths = {
        "LANGFLOW_CONFIG_DIR": "config",
        "LANGFLOW_COMPONENTS_PATH": "components",
        "LANGFLOW_LOG_FILE": "logs/langflow.log",
        "PIP_CACHE_DIR": "pip-cache",
        "TEMP": "tmp",
        "TMP": "tmp",
        "TMPDIR": "tmp",
        "XDG_CACHE_HOME": "cache",
        "HF_HOME": "cache/huggingface",
        "MPLCONFIGDIR": "cache/matplotlib",
        "NUMBA_CACHE_DIR": "cache/numba",
        "TORCH_HOME": "cache/torch",
    }
    env.update({key: str(runtime / value) for key, value in paths.items()})
    env.update(
        {
            "LANGFLOW_DATABASE_URL": "sqlite:///"
            + (runtime / "langflow.db").as_posix(),
            "LANGFLOW_HOST": "127.0.0.1",
            "LANGFLOW_OPEN_BROWSER": "false",
            "LANGFLOW_AUTO_LOGIN": "true",
            "LANGFLOW_DO_NOT_TRACK": "true",
            "LANGFLOW_SAVE_DB_IN_CONFIG_DIR": "false",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(PACKAGE / "src"),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "PYTHONNOUSERSITE": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MPLBACKEND": "Agg",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "DO_NOT_TRACK": "true",
        }
    )
    return env


def setup_environment(venv: Path, package: Path, env: dict[str, str]) -> None:
    """Only this dedicated venv is ever an installation target."""
    if venv.is_symlink() or venv.resolve() != venv.absolute():
        raise ValueError(
            "Refusing a redirected .demo-venv; use a real project-local directory"
        )
    python = venv_python(venv)
    if not python.is_file():
        if sys.version_info[:2] != (3, 10):
            raise ValueError("Run setup using Python 3.10 (Windows: py -3.10)")
        subprocess.run(
            [sys.executable, "-B", "-m", "venv", str(venv)], env=env, check=True
        )
    config = venv / "pyvenv.cfg"
    if not config.is_file():
        raise ValueError(
            "Refusing an existing interpreter without .demo-venv/pyvenv.cfg"
        )
    if re.search(
        r"include-system-site-packages\s*=\s*true", config.read_text(), re.IGNORECASE
    ):
        raise ValueError("Refusing a .demo-venv that includes shared system packages")
    identity = subprocess.run(
        [
            str(python),
            "-I",
            "-X",
            "utf8",
            "-B",
            "-c",
            "import sys,json; print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix}))",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    prefixes = json.loads(identity.stdout)
    if (
        Path(prefixes["prefix"]).resolve() != venv.resolve()
        or prefixes["prefix"] == prefixes["base_prefix"]
    ):
        raise ValueError(
            "Refusing installation: interpreter prefix is not the dedicated .demo-venv"
        )
    subprocess.run(
        [
            str(python),
            "-I",
            "-X",
            "utf8",
            "-B",
            "-m",
            "pip",
            "install",
            "--no-user",
            "--prefix",
            str(venv),
            "--cache-dir",
            env["PIP_CACHE_DIR"],
            "-e",
            str(package) + "[langflow,science,instruments]",
            "langflow-base==1.13.0",
        ],
        env=env,
        check=True,
    )


def port_available(port: int) -> bool:
    with socket.socket() as candidate:
        try:
            candidate.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def json_request(url: str, token: str | None = None, payload: dict | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    # The demo's own loopback HTTP calls must never pass through a system proxy.
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(url, data=body, headers=headers), timeout=15) as response:
        return json.load(response)


def seed_flows(url: str, flow_dir: Path) -> dict[str, list[str]]:
    token = json_request(url + "/api/v1/auto_login")["access_token"]
    existing = json_request(url + "/api/v1/flows/", token)
    if isinstance(existing, dict):
        existing = existing["items"]
    names = {flow["name"] for flow in existing}
    result: dict[str, list[str]] = {"imported": [], "preserved": []}
    for filename in FLOW_FILES:
        payload = json.loads((flow_dir / filename).read_text(encoding="utf-8"))
        name = payload["name"]
        if name in names:
            result["preserved"].append(name)
            continue
        # IDs/ownership from an exported flow must never retarget an existing record.
        allowed = {
            key: payload[key]
            for key in ("name", "description", "data", "is_component")
            if key in payload
        }
        json_request(url + "/api/v1/flows/", token, allowed)
        names.add(name)
        result["imported"].append(name)
    return result


def import_instructions(flow_dir: Path) -> None:
    print(
        "Manual import: Langflow -> New flow / Upload flow; choose these JSON files:",
        flush=True,
    )
    for filename in FLOW_FILES:
        print("  " + str(flow_dir / filename), flush=True)


def prepare_runtime(runtime: Path) -> None:
    for subdirectory in ("config", "components", "logs", "tmp", "pip-cache", "cache"):
        (runtime / subdirectory).mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        PACKAGE / "components",
        runtime / "components",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def start_server(python: Path, runtime: Path, port: int, ready_timeout: float) -> int:
    url = f"http://127.0.0.1:{port}"
    log_path = runtime / "logs" / "launcher-server.log"
    flow_dir = PACKAGE / "examples" / "skill_flows"
    env = runtime_environment(runtime)
    env["LANGFLOW_PORT"] = str(port)
    command = [
        str(python),
        "-B",
        "-m",
        "langflow",
        "run",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--components-path",
        str(runtime / "components"),
        "--log-file",
        str(runtime / "logs/langflow.log"),
        "--no-open-browser",
    ]
    print(
        f"Starting demo: {url}\nLogs: {log_path}\nPress Ctrl+C here to stop this demo.",
        flush=True,
    )
    with log_path.open("a", encoding="utf-8") as log:
        # A new process group permits Ctrl+C to stop our child without signaling unrelated services.
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = subprocess.Popen(
            command,
            cwd=runtime,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            **options,
        )
        try:
            deadline = time.monotonic() + ready_timeout
            ready = False
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    opener = build_opener(ProxyHandler({}))
                    with opener.open(url + "/health", timeout=2) as response:
                        ready = response.status == 200
                    if ready:
                        break
                except (URLError, OSError):
                    pass
                time.sleep(0.5)
            if not ready:
                print(
                    "Server did not become ready. Read the log above; no flows were preloaded.",
                    flush=True,
                )
                import_instructions(flow_dir)
                return process.returncode or 2
            print(f"Demo ready: {url}", flush=True)
            try:
                result = seed_flows(url, flow_dir)
                print(
                    "Preloaded flows: " + ", ".join(result["imported"] or ["none"]),
                    flush=True,
                )
                print(
                    "Existing flows preserved: "
                    + ", ".join(result["preserved"] or ["none"]),
                    flush=True,
                )
            except (
                HTTPError,
                URLError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
            ) as exc:
                print(
                    f"Automatic flow import incomplete ({type(exc).__name__}); use manual import.",
                    flush=True,
                )
                import_instructions(flow_dir)
            # An indefinite Windows wait can defer Python's KeyboardInterrupt handler.
            while process.poll() is None:
                time.sleep(0.5)
            return process.returncode
        except KeyboardInterrupt:
            print("Stopping this demo...", flush=True)
            return 0
        finally:
            stop_server(process)


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    if os.name == "nt":
        # A venv executable may launch the real interpreter as a descendant.
        # Restrict fallback termination to the process tree we just created.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=20,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def valid_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Create/update ONLY this project's .demo-venv (network required)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Inspect prerequisites only; never create/install/start/import",
    )
    parser.add_argument(
        "--python",
        type=Path,
        help="Use an existing Python 3.10 environment read-only; incompatible with --setup",
    )
    parser.add_argument("--port", type=valid_port, default=7880)
    parser.add_argument("--runtime", type=Path, default=ROOT / ".demo-runtime")
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=240,
        help="Startup deadline in seconds (default: 240)",
    )
    args = parser.parse_args(argv)
    runtime = args.runtime.expanduser().resolve()
    python = (
        args.python.expanduser().resolve()
        if args.python
        else venv_python(ROOT / ".demo-venv")
    )
    print(
        f"Python: {python}\nRuntime: {runtime}\nDemo URL: http://127.0.0.1:{args.port}",
        flush=True,
    )
    if args.setup and args.python and not args.check:
        print(
            "--setup cannot be combined with --python: external environments are never installation targets."
        )
        return 2
    if args.ready_timeout <= 0:
        print("--ready-timeout must be positive.")
        return 2
    try:
        if args.setup and not args.check:
            existing = probe_environment(python) if python.is_file() else None
            if (
                existing
                and not existing["required_missing"]
                and not existing["optional_missing"]
            ):
                print(
                    "Existing dedicated environment is complete; reusing it without network installation."
                )
            else:
                print(
                    "SETUP: installing the current package [langflow,science,instruments] "
                    "+ langflow-base==1.13.0"
                )
                print("Installation target: " + str(ROOT / ".demo-venv"), flush=True)
                prepare_runtime(runtime)
                setup_environment(
                    ROOT / ".demo-venv", PACKAGE, runtime_environment(runtime)
                )
        if not python.is_file():
            print(
                "Python environment missing. First run: start_demo.bat --setup (or ./start_demo.sh --setup)."
            )
            return 2
        report = probe_environment(python)
        print("Detected Python " + report["python"])
        print("required_missing: " + json.dumps(report["required_missing"]))
        print("optional_missing: " + json.dumps(report["optional_missing"]))
        if report["optional_missing"]:
            print(
                "Optional instrument-array support is incomplete; the three core demo flows remain available."
            )
        if report["required_missing"]:
            print(
                "Use --setup for the dedicated .demo-venv, or provide a complete Python 3.10 with --python."
            )
            return 2
        if not port_available(args.port):
            print(
                f"Port {args.port} is in use. Choose --port with a free port; "
                "no existing service will be reused."
            )
            return 2
        print("Prerequisites OK. Loopback port is available.")
        if args.check:
            print(
                "Read-only check complete; no runtime directories, dependencies, "
                "services or flows were changed."
            )
            return 0
        prepare_runtime(runtime)
        return start_server(python, runtime, args.port, args.ready_timeout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Demo launcher failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
