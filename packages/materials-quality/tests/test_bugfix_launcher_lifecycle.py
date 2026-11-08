"""Regression tests: demo-launcher child-process lifecycle and decoding.

The launcher spawns the StudyUI server in a new process group so a console
Ctrl+C only stops the launcher. That separation means any startup error must
explicitly stop the child, or the server keeps the loopback port busy with no
visible owner.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts" / "start_demo.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("bugfix_demo_launcher_lifecycle", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_keyboard_interrupt_during_startup_stops_spawned_server(tmp_path, monkeypatch):
    demo = load_launcher()
    (tmp_path / "logs").mkdir()

    class Process:
        pid = 424242
        returncode = None
        stopped = 0

        def poll(self):
            return None

        def terminate(self):
            self.stopped += 1

        def kill(self):
            self.stopped += 1

        def wait(self, timeout=None):
            return 0

    process = Process()
    monkeypatch.setattr(demo.subprocess, "Popen", lambda *args, **kwargs: process)

    class InterruptingOpener:
        def open(self, *args, **kwargs):
            raise KeyboardInterrupt

    monkeypatch.setattr(demo, "build_opener", lambda *args, **kwargs: InterruptingOpener())

    interrupted = False
    try:
        demo.start_studyui_service(Path(sys.executable), tmp_path, 7880, ready_timeout=5)
    except KeyboardInterrupt:
        interrupted = True
    assert interrupted
    assert process.stopped, "Ctrl+C during startup orphaned the StudyUI server process"


def test_startup_failure_reports_the_requested_runtime_log(tmp_path, monkeypatch):
    demo = load_launcher()
    runtime = tmp_path / "评委 演示" / "runtime"
    (runtime / "logs").mkdir(parents=True)

    class ExitedProcess:
        pid = 11
        returncode = 1

        def poll(self):
            return 1

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 1

    monkeypatch.setattr(demo.subprocess, "Popen", lambda *args, **kwargs: ExitedProcess())
    with pytest.raises(RuntimeError) as excinfo:
        demo.start_studyui_service(Path(sys.executable), runtime, 7880, ready_timeout=5)
    log_path = runtime / "logs" / "studyui-server.log"
    assert str(log_path) in str(excinfo.value), (
        "startup failure pointed at .demo-runtime instead of the runtime that failed"
    )


def test_theme_probe_decodes_child_output_as_utf8(tmp_path, monkeypatch):
    demo = load_launcher()
    vendor = tmp_path / "vendor frontend"
    vendor.mkdir()
    (vendor / "index.html").write_text("<html><head></head></html>", encoding="utf-8")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if kwargs.get("text") and not kwargs.get("encoding"):
            # subprocess text mode without an explicit codec decodes with the
            # ANSI code page (cp936 on Chinese Windows, ASCII under LANG=C); a
            # UTF-8 install path containing Chinese characters raises exactly
            # this UnicodeDecodeError, so the launcher dies on such paths.
            raise UnicodeDecodeError(
                "cp936",
                "D:\\评委 演示\\StudyUI\\frontend".encode("utf-8"),
                0,
                1,
                "invalid start byte",
            )
        return subprocess.CompletedProcess(command, 0, stdout=str(vendor))

    monkeypatch.setattr(demo.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="base URL"):
        demo.apply_studyui_langflow_theme(Path(sys.executable), tmp_path / "runtime")
    _, options = calls[0]
    assert options.get("encoding") == "utf-8"
    env = options.get("env") or {}
    assert env.get("PYTHONUTF8") == "1"
    assert env.get("PYTHONIOENCODING") == "utf-8"
