#!/usr/bin/env python3
"""Build a deterministic, lean portable demo archive for GitHub Releases."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "beta-demo"
DEFAULT_OUTPUT = ROOT / "dist" / f"StudyUI-{VERSION}-portable.zip"
ARCHIVE_ROOT = f"StudyUI-{VERSION}"
ZIP_TIMESTAMP = (2026, 11, 8, 0, 0, 0)

INCLUDE_FILES = (
    "README.md",
    ".python-version",
    "start_demo.bat",
    "start_demo.sh",
    "scripts/start_demo.py",
    "packages/materials-quality/README.md",
    "packages/materials-quality/pyproject.toml",
    "packages/materials-quality/requirements.lock",
    "packages/materials-quality/requirements-tested-py310.txt",
    "packages/materials-quality/requirements-ui-tested-py310.txt",
    "packages/materials-quality/THIRD_PARTY_NOTICES.md",
)
INCLUDE_DIRS = (
    "docs",
    "demo_datasets",
    "packages/materials-quality/components",
    "packages/materials-quality/docs",
    "packages/materials-quality/src",
    "packages/materials-quality/examples/science_flows",
    "packages/materials-quality/examples/skill_flows",
    "packages/materials-quality/examples/research_flows",
)
SKIP_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    ".demo-venv",
    ".demo-runtime",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "node_modules",
    "uploads",
    "workflows",
    "StudyUI_outputs",
}
SKIP_SUFFIXES = {
    ".db",
    ".db-shm",
    ".db-wal",
    ".log",
    ".pyc",
    ".pyo",
    ".tmp",
    ".bak",
    ".backup",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".tmp",
    ".bak",
    ".backup",
    ".pem",
    ".key",
    ".p12",
}
FORBIDDEN_NAMES = {".env", "credentials.json", "workspace.json", "workspace.json.lock"}

PORTABLE_TEXT = f"""StudyUI {VERSION} portable
============================

Requirements
- Python 3.10.x
- Network access for the first dependency install
- A free local port (default: 7880)

Windows
  start_demo.bat --setup
  start_demo.bat

macOS / Linux
  sh ./start_demo.sh --setup
  sh ./start_demo.sh

Then open http://127.0.0.1:7880

The five home-page demo cases run without a model API key. Configure a model
only when you want natural-language Agent exploration.

Keep credentials, .demo-runtime/, workflows/, uploads/, and StudyUI_outputs/
out of this directory when sharing it. See README.md and docs/ for details.
"""


def _skip(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in relative.parts):
        return True
    if path.name in FORBIDDEN_NAMES or path.suffix.casefold() in FORBIDDEN_SUFFIXES:
        raise ValueError(f"Forbidden portable file: {relative.as_posix()}")
    return path.suffix.casefold() in SKIP_SUFFIXES


def collect_files() -> list[Path]:
    files: dict[str, Path] = {}
    for relative in INCLUDE_FILES:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Portable input is missing: {relative}")
        if not _skip(path):
            files[relative] = path
    for relative in INCLUDE_DIRS:
        directory = ROOT / relative
        if not directory.is_dir():
            raise FileNotFoundError(f"Portable directory is missing: {relative}")
        for path in directory.rglob("*"):
            if path.is_file() and not _skip(path):
                files[path.relative_to(ROOT).as_posix()] = path
    if not files:
        raise ValueError("Portable archive would be empty")
    return [files[key] for key in sorted(files)]


def _add(zf: zipfile.ZipFile, archive_name: str, data: bytes, mode: int) -> None:
    info = zipfile.ZipInfo(archive_name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = mode << 16
    zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(output: Path) -> tuple[int, str]:
    files = collect_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output.parent, suffix=".zip.tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zf:
            _add(
                zf, f"{ARCHIVE_ROOT}/PORTABLE.txt", PORTABLE_TEXT.encode("utf-8"), 0o644
            )
            for path in files:
                archive_name = f"{ARCHIVE_ROOT}/{path.relative_to(ROOT).as_posix()}"
                mode = 0o755 if path.suffix == ".sh" else 0o644
                _add(zf, archive_name, path.read_bytes(), mode)
        with zipfile.ZipFile(temporary) as check:
            if check.testzip() is not None:
                raise ValueError("Portable archive failed its ZIP integrity check")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii", newline="\n")
    return len(files) + 1, digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    count, digest = build(output)
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"Built {output} ({count} files, {size_mb:.1f} MB)")
    print(f"SHA256 {digest}")


if __name__ == "__main__":
    main()
