"""Boundary tests: demo launcher dependency reading across pyproject shapes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts" / "start_demo.py"
PACKAGE = ROOT / "packages" / "materials-quality"


def load_launcher():
    spec = importlib.util.spec_from_file_location("boundary_demo_launcher_requirements", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_pyproject(folder: Path, dependencies_line: str) -> Path:
    lines = [
        "[project]",
        dependencies_line,
        "",
        "[project.optional-dependencies]",
        'langflow = ["lfx==1.13.0"]',
        'science = ["scipy>=1.15,<1.16"]',
        'instruments = ["h5py>=3.10,<4"]',
    ]
    text = "".join(line + chr(10) for line in lines)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pyproject.toml").write_text(text, encoding="utf-8")
    return folder


def test_nested_brackets_in_dependency_spec_are_read(tmp_path):
    folder = write_pyproject(
        tmp_path / "nested",
        'dependencies = ["uvicorn[standard]>=0.30", "pandas>=2.0"]',
    )
    result = load_launcher().requirements(folder)
    assert "uvicorn[standard]>=0.30" in result
    assert result[:2] == ["langflow-base==1.13.0", "lfx==1.13.0"]


def test_comment_lines_inside_dependency_array_are_read(tmp_path):
    block = chr(10).join(
        [
            "dependencies = [",
            "  # core data stack",
            '  "pandas>=2.0",  # pinned major',
            '  "pint==0.24.4",',
            "]",
        ]
    )
    folder = write_pyproject(tmp_path / "comments", block)
    result = load_launcher().requirements(folder)
    assert "pandas>=2.0" in result
    assert "pint==0.24.4" in result


def test_missing_dependency_array_is_clean_error(tmp_path):
    folder = tmp_path / "missing"
    folder.mkdir()
    text = "[project]" + chr(10) + 'name = "x"' + chr(10)
    (folder / "pyproject.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_launcher().requirements(folder)


def test_empty_arrays_still_return_runtime_pins(tmp_path):
    lines = [
        "[project]",
        "dependencies = []",
        "",
        "[project.optional-dependencies]",
        "langflow = []",
        "science = []",
        "instruments = []",
    ]
    folder = tmp_path / "empty"
    folder.mkdir()
    (folder / "pyproject.toml").write_text("".join(line + chr(10) for line in lines), encoding="utf-8")
    result = load_launcher().requirements(folder)
    assert result == ["langflow-base==1.13.0", "lfx==1.13.0"]


def test_real_project_dependencies_are_read():
    demo = load_launcher()
    result = demo.requirements(PACKAGE)
    assert result[:2] == ["langflow-base==1.13.0", "lfx==1.13.0"]
    assert any(item.startswith("pandas") for item in result)
    optional = demo.requirements(PACKAGE, optional=True)
    assert any(item.startswith("h5py") for item in optional)
