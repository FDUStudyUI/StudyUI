"""Project-scoped Harness permissions and one-shot action approvals."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from filelock import FileLock

PRESETS = {
    "read_only": {"label": "只读", "description": "检索、查看项目和调用无副作用的科研能力。"},
    "project_collaboration": {
        "label": "项目协作",
        "description": "在明确授权的研究任务内创建、修改和运行本项目工作流。",
    },
    "per_action": {"label": "逐项审批", "description": "每项工具操作都先等待本次审批。"},
    "skill_sandbox": {
        "label": "审核后沙箱 Skill",
        "description": "项目协作，并允许已审核版本的 Skill 在隔离目录执行。",
    },
}

READ_ACTIONS = {
    "data.inspect",
    "literature.search",
    "skill.list",
    "skill.read",
    "workflow.list",
    "workflow.inspect",
    "component.list",
    "method.recommend",
}
WRITE_ACTIONS = {
    "workflow.create",
    "workflow.edit",
    "workflow.propose",
    "workflow.run",
    "skill.invoke",
    "artifact.create",
    "ai.analyze",
}
ALWAYS_APPROVE = {
    "project.delete",
    "workflow.delete",
    "skill.install",
    "skill.update",
    "skill.trust",
    "skill.script",
    "permission.change",
    "external_data.send",
}


class PermissionStore:
    """Small JSON settings store; approval requests remain in the session event database."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock", timeout=10)

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "default_preset": "project_collaboration", "projects": {}, "models": {}}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("StudyUI settings file must contain a JSON object")
        value.setdefault("version", 1)
        value.setdefault("default_preset", "project_collaboration")
        value.setdefault("projects", {})
        value.setdefault("models", {})
        return value

    def _write(self, value):
        raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(
            dir=self.path.parent, prefix=".settings-", suffix=".tmp", delete=False
        ) as out:
            tmp = out.name
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def snapshot(self):
        with self.lock:
            return self._read()

    def get_preset(self, project_id: str | None):
        value = self.snapshot()
        selected = value["projects"].get(project_id, {}).get("permission_preset") if project_id else None
        preset = selected or value["default_preset"]
        return preset if preset in PRESETS else "project_collaboration"

    def set_preset(self, project_id: str | None, preset: str):
        if preset not in PRESETS:
            raise ValueError("Unknown permission preset")
        with self.lock:
            value = self._read()
            if project_id:
                project = value["projects"].setdefault(project_id, {})
                project["permission_preset"] = preset
            else:
                value["default_preset"] = preset
            self._write(value)
        return {"project_id": project_id, "preset": preset, **PRESETS[preset]}

    def authorize(
        self,
        *,
        project_id: str | None,
        action: str,
        task_authorized: bool = False,
        trusted_skill: bool = False,
        script_execution: bool = False,
    ):
        preset = self.get_preset(project_id)
        # Deterministic loading of enabled, read-only Skill instructions is a Harness
        # preflight step, not a model-requested tool action or code execution.
        if action == "skill.preflight":
            return {"allowed": True, "requires_approval": False, "preset": preset}
        if script_execution:
            allowed = preset == "skill_sandbox" and trusted_skill and task_authorized and bool(project_id)
            return {
                "allowed": allowed,
                "requires_approval": not allowed,
                "preset": preset,
                "reason": None if allowed else "Skill 脚本须按版本审核，并选择沙箱 Skill 档位。",
            }
        if preset != "per_action" and action in READ_ACTIONS:
            return {"allowed": True, "requires_approval": False, "preset": preset}
        if action in ALWAYS_APPROVE:
            return {"allowed": False, "requires_approval": True, "preset": preset}
        if preset == "read_only":
            return {"allowed": False, "requires_approval": True, "preset": preset}
        if preset == "per_action":
            return {"allowed": False, "requires_approval": True, "preset": preset}
        if action in WRITE_ACTIONS:
            if action == "skill.invoke" and not trusted_skill:
                return {
                    "allowed": False,
                    "requires_approval": True,
                    "preset": preset,
                    "reason": "此 Skill 尚未在当前版本下启用。",
                }
            return {
                "allowed": bool(task_authorized and project_id),
                "requires_approval": not bool(task_authorized and project_id),
                "preset": preset,
            }
        return {"allowed": False, "requires_approval": True, "preset": preset}


def new_approval_id():
    return str(uuid.uuid4())
