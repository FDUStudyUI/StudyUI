"""Provision the DeepSeek Harness (DSH) engine for StudyUI.

Installs a pinned DSH package into ``.demo-runtime/dsh`` (under the project
runtime directory), creates the StudyUI DSH profile, and verifies that the
engine answers ``--version``. Node.js 24 must be available on PATH or via
``STUDYUI_NODE_BIN``.

Usage:
    python scripts/setup_dsh.py [--runtime-root .demo-runtime] [--check] [--web]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "materials-quality" / "src"
sys.path.insert(0, str(SRC))

from materials_quality.agent import dsh_engine, dsh_web  # noqa: E402

DSH_PACKAGE = os.environ.get("STUDYUI_DSH_PACKAGE", dsh_engine.DEFAULT_DSH_PACKAGE)


def find_node(runtime_root: Path | None = None):
    override = os.environ.get("STUDYUI_NODE_BIN", "").strip()
    if override:
        return override
    found = shutil.which("node") or shutil.which("node.exe")
    if found:
        return found
    if runtime_root is not None:
        bundled = runtime_root.parent / "runtime" / "dsh" / "node" / "node.exe"
        if bundled.is_file():
            return str(bundled)
    return None


def run(cmd, cwd=None, check=True):
    print("+", " ".join(str(part) for part in cmd))
    return subprocess.run(cmd, cwd=cwd, check=check)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", default=str(ROOT / ".demo-runtime"))
    parser.add_argument("--check", action="store_true", help="only report readiness")
    parser.add_argument("--skip-install", action="store_true", help="reuse an existing node_modules")
    parser.add_argument("--web", action="store_true", help="provision the StudyUI DSH Web profile")
    args = parser.parse_args(argv)

    runtime_root = Path(args.runtime_root).expanduser().resolve()
    dsh_root = runtime_root / "dsh"
    settings_path = runtime_root / "studyui-settings.json"
    node = find_node(runtime_root)
    npm = shutil.which("npm")
    if not node:
        print("Node.js 24 is required (STUDYUI_NODE_BIN or PATH).", file=sys.stderr)
        return 2
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    print(f"node: {node} ({version})")

    bin_js = dsh_engine._bundled_dsh_bin(runtime_root)
    if not bin_js.is_file():
        if args.check:
            print(f"DSH is not installed at {bin_js}")
            return 1
        if npm is None:
            print("npm is required to install DSH.", file=sys.stderr)
            return 2
        if not args.skip_install:
            dsh_root.mkdir(parents=True, exist_ok=True)
            package_json = dsh_root / "package.json"
            if not package_json.is_file():
                package_json.write_text(
                    json.dumps({"name": "studyui-dsh", "private": True}, indent=2), encoding="utf-8"
                )
            run([npm, "install", "--no-audit", "--no-fund", DSH_PACKAGE], cwd=dsh_root)
    if not bin_js.is_file():
        print(f"DSH entrypoint missing after install: {bin_js}", file=sys.stderr)
        return 1

    result = subprocess.run([node, str(bin_js), "--version"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return 1
    print("dsh:", result.stdout.strip() or result.stderr.strip())

    if args.check:
        if args.web:
            profile_dir = dsh_web.web_profile_dir(settings_path)
            state = "exists" if profile_dir.is_dir() else "missing"
            print(f"web profile: {profile_dir} ({state})")
            return 0 if profile_dir.is_dir() else 1
        print(f"DSH is installed at {bin_js}")
        return 0

    if args.web:
        profile_dir = dsh_web.ensure_web_profile(settings_path)
        print("web profile:", profile_dir)
        try:
            plugin_dir = dsh_web.install_studyui_plugin(
                settings_path,
                source=ROOT / "dsh-plugins" / "studyui-dsh",
            )
            print("brand plugin:", plugin_dir)
        except (dsh_web.DshWebError, OSError) as exc:
            print("warning:", exc, file=sys.stderr)
        warning = dsh_web.stale_credentials_warning(dsh_engine.resolve_dsh_home(settings_path))
        if warning:
            print("warning:", warning, file=sys.stderr)
        try:
            profile = dsh_web.select_model(settings_path)
            dsh_web.validate_official_model(profile, available=dsh_web.official_models(settings_path))
        except dsh_web.DshWebError as exc:
            print("warning:", exc, file=sys.stderr)
        print("DSH Web is ready.")
        return 0

    profile_dir = dsh_engine.ensure_profile(settings_path)
    print("profile:", profile_dir)
    sdk_profile_dir = dsh_engine.ensure_profile(settings_path, profile="studyui-sdk", sdk=True)
    print("sdk profile:", sdk_profile_dir)
    try:
        import deepseek_harness  # noqa: F401

        print("Python SDK: installed (engine=dsh-sdk)")
    except Exception:
        print("Python SDK: not installed; engine falls back to dsh (headless)")
    print("DSH is ready. Agent engine will be selected automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
