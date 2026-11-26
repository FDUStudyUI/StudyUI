#!/usr/bin/env python3
"""Build the Windows x64 demo archive, optionally with a complete Python runtime."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def load_branding():
    """Import the sibling branding.py by file path (see scripts/start_demo.py).

    "from scripts.branding" resolves to materials-quality/scripts
    whenever that package shadows the repository root on sys.path, so neither
    it nor a bare "from branding" import is reliable.
    """
    path = Path(__file__).resolve().with_name("branding.py")
    spec = importlib.util.spec_from_file_location("studyui_branding", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load branding helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


strip_vendor_branding = load_branding().strip_vendor_branding

ROOT = Path(__file__).resolve().parents[1]
VERSION = "beta-demo"
ARCHIVE_ROOT = f"StudyUI-{VERSION}"
ZIP_TIMESTAMP = (2026, 11, 8, 0, 0, 0)
DEFAULT_FULL_OUTPUT = ROOT / "dist" / f"StudyUI-{VERSION}-windows-x64-portable.zip"
DEFAULT_SOURCE_OUTPUT = ROOT / "dist" / f"StudyUI-{VERSION}-source.zip"
VENV = ROOT / ".demo-venv"

# Node 24 LTS Windows x64 — pinned for reproducibility
NODE_VERSION = "24.22.1"
NODE_DOWNLOAD_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-win-x64.zip"
NODE_SHASUMS_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/SHASUMS256.txt"

INCLUDE_FILES = (
    "README.md",
    "LICENSE",
    ".python-version",
    "start_demo.bat",
    "start_demo.sh",
    "scripts/start_demo.py",
    "scripts/branding.py",
    "scripts/setup_dsh.py",
    "materials-quality/README.md",
    "materials-quality/pyproject.toml",
    "materials-quality/requirements.lock",
    "materials-quality/requirements-tested-py310.txt",
    "materials-quality/requirements-ui-tested-py310.txt",
    "materials-quality/THIRD_PARTY_NOTICES.md",
)
INCLUDE_DIRS = (
    "docs",
    "demo_datasets",
    "dsh-plugins",
    "scripts/assets",
    "materials-quality/components",
    "materials-quality/docs",
    "materials-quality/src",
    "materials-quality/examples/science_flows",
    "materials-quality/examples/skill_flows",
    "materials-quality/examples/research_flows",
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
    ".env",
}
FORBIDDEN_NAMES = {".env", "credentials.json", "workspace.json", "workspace.json.lock"}
FORBIDDEN_NAMES_CASEFOLD = {name.casefold() for name in FORBIDDEN_NAMES}

FULL_TEXT = f"""StudyUI {VERSION} - Windows x64 portable
==========================================

No installation is required.

1. Extract this folder to a writable location.
2. Run start_demo.bat.
3. Open http://127.0.0.1:7880

This bundle includes Python 3.10.22, Node.js {NODE_VERSION}, and all runtime
dependencies. The five home-page demo cases work without network access or a model
API key. Configure a model in StudyUI only when you want natural-language Agent
exploration.

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
    if path.name.casefold() in FORBIDDEN_NAMES_CASEFOLD or path.suffix.casefold() in FORBIDDEN_SUFFIXES:
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
    (site_packages / "_editable_impl_studyui_materials_quality.pth").unlink(missing_ok=True)
    vendor_frontend = site_packages / "langflow" / "frontend"
    if vendor_frontend.is_dir():
        strip_vendor_branding(vendor_frontend)
    if not (python_dir / "python.exe").is_file():
        raise FileNotFoundError("Portable runtime does not contain python.exe")
    return python_dir


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_node_sha256(archive_name: str) -> str:
    try:
        with urllib.request.urlopen(NODE_SHASUMS_URL, timeout=60) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download Node checksums: {exc}") from exc
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == archive_name:
            return parts[0].lower()
    raise ValueError(f"No checksum for {archive_name} in {NODE_SHASUMS_URL}")


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    root = target.resolve()
    for member in archive.infolist():
        destination = (root / member.filename).resolve()
        if destination != root and root not in destination.parents:
            raise ValueError(f"Unsafe path in Node.js archive: {member.filename}")
    archive.extractall(root)


def _download_node() -> Path:
    """Download the pinned Node.js Windows x64 zip, verify its checksum, extract it."""
    archive_name = f"node-v{NODE_VERSION}-win-x64.zip"
    extract_dir = Path(tempfile.mkdtemp(prefix="studyui-node-"))
    zip_path = extract_dir / archive_name
    print(f"Downloading Node.js v{NODE_VERSION} from {NODE_DOWNLOAD_URL}…", flush=True)
    try:
        urllib.request.urlretrieve(NODE_DOWNLOAD_URL, zip_path)
        expected = _expected_node_sha256(archive_name)
        actual = _sha256_file(zip_path)
        if actual != expected:
            raise ValueError(f"Node.js checksum mismatch: expected {expected}, got {actual}")
        with zipfile.ZipFile(zip_path) as archive:
            if archive.testzip() is not None:
                raise ValueError("Node.js archive failed integrity check")
            _safe_extract(archive, extract_dir)
        zip_path.unlink()
        node_dir = extract_dir / f"node-v{NODE_VERSION}-win-x64"
        if not (node_dir / "node.exe").is_file():
            raise FileNotFoundError(f"node.exe not found in extracted Node.js archive at {node_dir}")
        return node_dir
    except Exception:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise


def _install_dsh(target_dir: Path, *, node_exe: Path | None = None, node_dir: Path | None = None) -> None:
    """Install the pinned DSH package with the bundled Node/npm when available."""
    package_json = target_dir / "package.json"
    package_json.write_text(json.dumps({"name": "studyui-dsh", "private": True}, indent=2), encoding="utf-8")
    command: list[str]
    env = None
    npm_cli = node_dir / "node_modules" / "npm" / "bin" / "npm-cli.js" if node_dir else None
    if node_exe is not None and npm_cli is not None and npm_cli.is_file():
        command = [str(node_exe), str(npm_cli)]
        env = os.environ.copy()
        env["PATH"] = str(node_dir) + os.pathsep + env.get("PATH", "")
    else:
        npm = shutil.which("npm")
        if not npm:
            raise FileNotFoundError("npm is required to install DSH; ensure Node.js is available on PATH")
        command = [npm]
    subprocess.run(
        [
            *command,
            "install",
            "--no-audit",
            "--no-fund",
            "--ignore-scripts",
            "@deepseek-ai/dsh@0.2.2-rc.5",
        ],
        cwd=target_dir,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        env=env,
    )


def stage_dsh(stage: Path) -> Path:
    """Download Node 24 and pre-install DSH into the portable staging directory.

    Layout (matching _bundled_node / _bundled_dsh_bin expectations):
        stage/runtime/dsh/node/node.exe   (and supporting DLLs + LICENSE)
        stage/runtime/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js
    """
    dsh_dir = stage / "runtime" / "dsh"
    node_dir = dsh_dir / "node"
    node_dir.mkdir(parents=True, exist_ok=True)

    downloaded_node = _download_node()
    try:
        for item in downloaded_node.iterdir():
            if item.suffix.lower() in (".exe", ".dll") or item.name in ("nodevars.bat", "LICENSE"):
                shutil.copy2(item, node_dir / item.name)
        node_exe = node_dir / "node.exe"
        if not node_exe.is_file():
            raise FileNotFoundError("node.exe was not copied to the staging directory")
        _install_dsh(dsh_dir, node_exe=downloaded_node / "node.exe", node_dir=downloaded_node)
    finally:
        shutil.rmtree(downloaded_node.parent, ignore_errors=True)

    bin_js = dsh_dir / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    if not bin_js.is_file():
        raise FileNotFoundError(f"DSH entrypoint missing after install: {bin_js}")

    result = subprocess.run(
        [str(node_exe), str(bin_js), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    version = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        raise RuntimeError(f"Bundled DSH smoke test failed (exit {result.returncode}): {version}")
    print(f"DSH bundled: {version}", flush=True)
    return dsh_dir


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
    dsh_dir = stage_dsh(stage_root) if full else None
    runtime_files = [path for path in sorted(runtime_dir.rglob("*")) if path.is_file()] if runtime_dir else []
    dsh_files = [path for path in sorted(dsh_dir.rglob("*")) if path.is_file()] if dsh_dir else []
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
            for path in dsh_files:
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
    return len(files) + len(runtime_files) + len(dsh_files) + 1, digest


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
