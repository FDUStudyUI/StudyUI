"""Boundary tests: demo launcher argument validation (timeout, runtime, ports)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts" / "start_demo.py"


def load_launcher():
    assert LAUNCHER.is_file(), "demo launcher must exist"
    spec = importlib.util.spec_from_file_location("boundary_demo_launcher_args", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness(monkeypatch):
    demo = load_launcher()
    ports: list[int] = []
    complete = {"required_missing": [], "optional_missing": [], "python": "3.10.11"}
    monkeypatch.setattr(demo, "probe_environment", lambda *a, **k: dict(complete))
    monkeypatch.setattr(demo, "port_available", lambda port: (ports.append(port), True)[1])
    for name in (
        "setup_environment",
        "prepare_runtime",
        "initialize_file_workflows",
        "apply_studyui_langflow_theme",
    ):
        monkeypatch.setattr(demo, name, lambda *a, **k: None)
    monkeypatch.setattr(demo, "start_system", lambda *a, **k: 0)
    return demo, ports


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "Infinity", "1e400", "-inf", "0", "-1", "abc"])
def test_ready_timeout_must_be_positive_and_finite(harness, value):
    demo, _ = harness
    with pytest.raises(SystemExit) as excinfo:
        demo.main(["--check", "--python", sys.executable, "--ready-timeout", value])
    assert excinfo.value.code == 2


def test_ready_timeout_accepts_positive_values(harness):
    demo, ports = harness
    assert demo.main(["--check", "--python", sys.executable, "--ready-timeout", "0.001"]) == 0
    assert demo.main(["--check", "--python", sys.executable, "--ready-timeout", "240"]) == 0
    assert ports == [7880, 7880]


@pytest.mark.parametrize("value", ["", "   ", " "])
def test_runtime_must_not_be_blank(harness, value):
    demo, ports = harness
    with pytest.raises(SystemExit) as excinfo:
        demo.main(["--check", "--python", sys.executable, "--runtime", value])
    assert excinfo.value.code == 2
    assert ports == []


def test_runtime_explicit_path_still_works(harness, tmp_path):
    demo, ports = harness
    runtime = tmp_path / "runtime"
    argv = ["--check", "--python", sys.executable, "--port", "65535", "--runtime", str(runtime)]
    assert demo.main(argv) == 0
    assert ports == [65535]
    assert not runtime.exists()


def test_check_mode_does_not_create_runtime(harness, tmp_path):
    demo, _ = harness
    runtime = tmp_path / "readonly-runtime"
    assert demo.main(["--check", "--python", sys.executable, "--runtime", str(runtime)]) == 0
    assert not runtime.exists()
