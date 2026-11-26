"""Execute a reviewed Skill script in an offline, resource-limited Docker container."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_INPUT_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 1_000_000
DEFAULT_IMAGE = "python:3.12-slim"


class SkillSandbox:
    def __init__(self, registry, *, image=None, timeout=60):
        self.registry = registry
        self.image = image or os.environ.get("STUDYUI_SKILL_SANDBOX_IMAGE", DEFAULT_IMAGE)
        self.timeout = max(1, min(int(timeout), 300))

    def run(self, name, script_name, value):
        skill = self.registry.get(name)
        if skill.get("builtin") or not skill.get("enabled") or not skill.get("trusted"):
            raise PermissionError("只有已启用并按当前版本审核的 Skill 脚本才能运行。")
        script_name = str(script_name or "")
        if script_name not in skill.get("scripts", []) or not script_name.lower().endswith(".py"):
            raise ValueError("当前仅支持显式列出的 Python Skill 脚本。")
        source = (self.registry.root / skill["name"] / script_name).resolve()
        if not source.is_relative_to((self.registry.root / skill["name"]).resolve()) or not source.is_file():
            raise ValueError("Skill script path is invalid")
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(payload) > MAX_INPUT_BYTES:
            raise ValueError("Skill input exceeds 1 MB")
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("隔离运行需要本机 Docker；未找到 Docker，已拒绝在主机进程中运行 Skill。")
        subprocess.run(
            [docker, "image", "inspect", self.image], check=True, capture_output=True, timeout=20, text=True
        )
        with tempfile.TemporaryDirectory(prefix="studyui-skill-run-") as work:
            workdir = Path(work)
            (workdir / "input.json").write_bytes(payload)
            command = [
                docker,
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=512m",
                "--cpus=1",
                "--pids-limit=64",
                "--user=65534:65534",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
                "-v",
                f"{source.parent}:/skill:ro",
                "-v",
                f"{workdir}:/workspace:rw",
                "-w",
                "/workspace",
                self.image,
                "python",
                f"/skill/{source.name}",
                "/workspace/input.json",
                "/workspace/result.json",
            ]
            result = subprocess.run(command, check=False, capture_output=True, timeout=self.timeout)
            stdout = result.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            stderr = result.stderr[:4000].decode("utf-8", errors="replace")
            if result.returncode:
                raise RuntimeError(f"Sandboxed Skill failed ({result.returncode}): {stderr[:1000]}")
            output = workdir / "result.json"
            if output.exists():
                raw = output.read_bytes()
                if len(raw) > MAX_OUTPUT_BYTES:
                    raise ValueError("Skill output exceeds 1 MB")
                return {
                    "result": json.loads(raw.decode("utf-8")),
                    "stdout": stdout,
                    "skill": skill["name"],
                    "skill_sha256": skill["sha256"],
                    "sandbox": "docker-offline",
                }
            return {
                "result": None,
                "stdout": stdout,
                "skill": skill["name"],
                "skill_sha256": skill["sha256"],
                "sandbox": "docker-offline",
            }
