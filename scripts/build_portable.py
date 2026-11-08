#!/usr/bin/env python3
"""Build the Windows x64 demo archive, optionally with a complete Python runtime."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

try:
    from scripts.branding import strip_langflow_branding
except ImportError:  # Running as a script from scripts/.
    from branding import strip_langflow_branding

ROOT = Path(__file__).resolve().parents[1]
VERSION = "beta-demo"
ARCHIVE_ROOT = f"StudyUI-{VERSION}"
ZIP_TIMESTAMP = (2026, 11, 8, 0, 0, 0)
DEFAULT_FULL_OUTPUT = ROOT / "dist" / f"StudyUI-{VERSION}-windows-x64-portable.zip"
DEFAULT_SOURCE_OUTPUT = ROOT / "dist" / f"StudyUI-{VERSION}-source.zip"
VENV = ROOT / ".demo-venv"

INCLUDE_FILES = (
    "README.md",
    ".python-version",
    "start_demo.bat",
    "start_demo.sh",
    "scripts/start_demo.py",
    "scripts/branding.py",
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
    "scripts/assets",
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

FULL_TEXT = f"""StudyUI {VERSION} - Windows x64 portable
==========================================

No installation is required.

1. Extract this folder to a writable location.
2. Run start_demo.bat.
3. Open http://127.0.0.1:7880

This bundle includes Python 3.10.22 and all runtime dependencies. The five
home-page demo cases work without network access or a model API key. Configure
a model in StudyUI only when you want natural-language Agent exploration.

Keep credentials, .demo-runtime/, workflows/, uploads/, and StudyUI_outputs/
out of this directory when sharing it. See README.md and docs/ for details.
"""
SOURCE_TEXT = f"""StudyUI {VERSION} - source portable
====================================

Requirements: Python 3.10.x and network access for the first dependency install.

Windows: start_demo.bat --setup, then start_demo.bat
macOS/Linux: sh ./start_demo.sh --setup, then sh ./start_demo.sh

Then open http://127.0.0.1:7880. See README.md for details.
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


def base_prefix() -> Path:
    python = VENV / "Scripts" / "python.exe"
    if not python.is_file():
        raise FileNotFoundError("Build the .demo-venv environment before building the full portable")
    result = subprocess.run(
        [str(python), "-c", "import sys; print(sys.base_prefix)"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    prefix = Path(result.stdout.strip())
    if not (prefix / "python.exe").is_file():
        raise FileNotFoundError(f"Base Python runtime is incomplete: {prefix}")
    return prefix


def _copy_tree(source: Path, target: Path, *, exclude_dirs=(), exclude_files=()) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        shutil.copytree(
            source,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*exclude_dirs, *exclude_files),
        )
        return
    command = [
        "robocopy",
        str(source),
        str(target),
        "/E",
        "/MT:16",
        "/R:1",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP",
    ]
    for directory in exclude_dirs:
        command.extend(["/XD", str(source / directory) if "/" in directory else directory])
    if exclude_files:
        command.extend(["/XF", *exclude_files])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode > 7:
        raise RuntimeError(f"robocopy failed ({result.returncode}): {result.stderr or result.stdout}")


def stage_runtime(stage: Path) -> Path:
    prefix = base_prefix()
    python_dir = stage / "runtime" / "python"
    _copy_tree(
        prefix,
        python_dir,
        exclude_dirs=(
            "Lib/site-packages",
            "conda-meta",
            "pkgs",
            "include",
            "share",
            "Tools",
            "etc",
            "__pycache__",
        ),
        exclude_files=("*.pyc", "*.pyo", "*.whl"),
    )
    site_packages = python_dir / "Lib" / "site-packages"
    if site_packages.exists():
        shutil.rmtree(site_packages)
    _copy_tree(
        VENV / "Lib" / "site-packages",
        site_packages,
        exclude_dirs=("__pycache__",),
        exclude_files=("*.pyc", "*.pyo", "*.whl", "PyWin32.chm"),
    )
    (site_packages / "_editable_impl_langflow_materials_quality.pth").unlink(missing_ok=True)
    langflow_frontend = site_packages / "langflow" / "frontend"
    if langflow_frontend.is_dir():
        strip_langflow_branding(langflow_frontend)
    if not (python_dir / "python.exe").is_file():
        raise FileNotFoundError("Portable runtime does not contain python.exe")
    return python_dir


def _add(zf: zipfile.ZipFile, archive_name: str, data: bytes, mode: int) -> None:
    info = zipfile.ZipInfo(archive_name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = mode << 16
    zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)


def build(output: Path, *, full: bool) -> tuple[int, str]:
    files = collect_files()
    output.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix="studyui-portable-", dir=output.parent))
    runtime_dir = stage_runtime(stage_root) if full else None
    runtime_files = [path for path in sorted(runtime_dir.rglob("*")) if path.is_file()] if runtime_dir else []
    temporary = output.with_name(output.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            text = FULL_TEXT if full else SOURCE_TEXT
            _add(zf, f"{ARCHIVE_ROOT}/PORTABLE.txt", text.encode("utf-8"), 0o644)
            for path in files:
                archive_name = f"{ARCHIVE_ROOT}/{path.relative_to(ROOT).as_posix()}"
                mode = 0o755 if path.suffix == ".sh" else 0o644
                _add(zf, archive_name, path.read_bytes(), mode)
            for path in runtime_files:
                relative = path.relative_to(stage_root).as_posix()
                _add(zf, f"{ARCHIVE_ROOT}/{relative}", path.read_bytes(), 0o644)
        with zipfile.ZipFile(temporary) as check:
            if check.testzip() is not None:
                raise ValueError("Portable archive failed its ZIP integrity check")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
        shutil.rmtree(stage_root, ignore_errors=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii", newline="\n")
    return len(files) + len(runtime_files) + 1, digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Build the small source archive instead of the self-contained Windows runtime",
    )
    args = parser.parse_args()
    full = not args.source_only
    output = (args.output or (DEFAULT_FULL_OUTPUT if full else DEFAULT_SOURCE_OUTPUT)).resolve()
    count, digest = build(output, full=full)
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"Built {output} ({count} files, {size_mb:.1f} MB)")
    print(f"SHA256 {digest}")


if __name__ == "__main__":
    main()
