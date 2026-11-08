"""Boundary tests: portable archive refuses case-variant and *.env files."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BUILDER = ROOT / "scripts" / "build_portable.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("boundary_portable_builder", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_tree(root: Path, relative_files: list[str]) -> Path:
    for relative in relative_files:
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("payload", encoding="utf-8")
    return root


def collect(builder, root, monkeypatch):
    monkeypatch.setattr(builder, "ROOT", root)
    monkeypatch.setattr(builder, "INCLUDE_FILES", ("README.md",))
    monkeypatch.setattr(builder, "INCLUDE_DIRS", ("docs",))
    return builder.collect_files()


@pytest.mark.parametrize(
    "relative",
    [
        ".env",
        ".ENV",
        ".Env",
        "WORKSPACE.JSON",
        "Workspace.JSON.Lock",
        "Credentials.JSON",
        "SECRET.PEM",
        "DATA.DB",
    ],
)
def test_case_variant_forbidden_files_are_refused(tmp_path, monkeypatch, relative):
    root = make_tree(tmp_path, ["README.md", "docs/" + relative])
    with pytest.raises(ValueError):
        collect(load_builder(), root, monkeypatch)


@pytest.mark.parametrize("relative", ["prod.env", "PROD.ENV", "docs/PROD.ENV"])
def test_env_suffix_variants_are_refused(tmp_path, monkeypatch, relative):
    root = make_tree(tmp_path, ["README.md", "docs/" + relative])
    with pytest.raises(ValueError):
        collect(load_builder(), root, monkeypatch)


def test_plain_files_still_collect(tmp_path, monkeypatch):
    root = make_tree(tmp_path, ["README.md", "docs/ok.md"])
    found = collect(load_builder(), root, monkeypatch)
    relative = sorted(path.relative_to(root).as_posix() for path in found)
    assert relative == ["README.md", "docs/ok.md"]
