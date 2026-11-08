"""Regression tests: launcher scripts must load their sibling branding helper.

Baseline HEAD failed all 20 tests in tests/test_demo_launcher.py with
ModuleNotFoundError: "from scripts.branding" resolved to
packages/materials-quality/scripts (the package under test has its own
regular "scripts" package) and the fallback "from branding" could not see the
repository-root scripts/ directory because the repository root is not on
sys.path when pytest runs with rootdir packages/materials-quality.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts" / "start_demo.py"
BUILDER = ROOT / "scripts" / "build_portable.py"
BRANDING = ROOT / "scripts" / "branding.py"


def load_module(path: Path, name: str):
    """Load a script by file path, exactly like tests/test_demo_launcher.py."""
    assert path.is_file(), f"Missing script: {path}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_start_demo_loads_sibling_branding_helper():
    demo = load_module(LAUNCHER, "bugfix_demo_launcher_import")
    branding = demo.load_branding()
    assert Path(branding.__file__).resolve() == BRANDING.resolve()
    helper = demo.strip_langflow_branding
    assert Path(helper.__code__.co_filename).resolve() == BRANDING.resolve()
    assert helper.__module__ == "studyui_branding"
    assert callable(helper)


def test_portable_builder_loads_sibling_branding_helper():
    builder = load_module(BUILDER, "bugfix_portable_builder_import")
    helper = builder.strip_langflow_branding
    assert Path(helper.__code__.co_filename).resolve() == BRANDING.resolve()
    # The portable archive must keep shipping the helper the launcher imports.
    assert "scripts/branding.py" in builder.INCLUDE_FILES


def test_launcher_entry_points_resolve_branding_without_starting_anything():
    # --help executes the module imports but performs no setup, install or
    # network work, so it proves both documented entry points still load.
    for command, cwd in (
        ([sys.executable, "-B", str(LAUNCHER), "--help"], ROOT),
        ([sys.executable, "-B", "-m", "scripts.start_demo", "--help"], ROOT),
    ):
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr
        assert "--check" in completed.stdout
